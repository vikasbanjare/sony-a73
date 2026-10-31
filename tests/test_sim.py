from fractions import Fraction

import numpy as np
import pytest

from a7iii.color.transfer import middle_grey_signal
from a7iii.ptp import PTPError, SonyCamera
from a7iii.ptp.liveview import FocusFrame, pack_liveview, parse_liveview
from a7iii.ptp.props import FORM_ENUM, PropDesc, pack_props, parse_props
from a7iii.ptp.codes import DataType, decode_touch_af, encode_touch_af
from a7iii.sim import Scene, SimTransport, VirtualA7III, connect_simulated, walking_subject_scene


def grey_scene():
    return Scene(background_depth=3.0, texture_scale=None, ev100=9.0)  # featureless wall


def test_correct_exposure_lands_on_profile_middle_grey():
    for gamma, iso, curve in (("Cine4", 100, "rec709"), ("S-Log3", 800, "slog3"), ("HLG3", 125, "hlg")):
        scene = Scene(background_depth=3.0, texture_scale=None, ev100=9.0, background_tint=(0.36, 0.36, 0.36))
        cam = VirtualA7III(scene, seed=1)
        cam.state.gamma, cam.state.iso, cam.state.f_number = gamma, iso, 4.0
        cam.state.shutter = Fraction(100, iso) * Fraction(16) / Fraction(2**9)  # exact correct exposure
        cam.state.af_mode = "MF"
        f = cam.render()
        # texture mean is 0.5, tint 0.36 -> reflectance 0.18
        assert f.signal[..., 1].mean() == pytest.approx(middle_grey_signal(curve), abs=0.02), gamma


@pytest.mark.parametrize("gamma,iso,expected", [
    ("Cine4", 500, "LCG"), ("Cine4", 640, "HCG"), ("S-Log3", 3200, "LCG"), ("S-Log3", 5000, "HCG"),
    ("HLG3", 640, "LCG"), ("HLG3", 800, "HCG"),
])
def test_dual_conversion_gain_switch_points(gamma, iso, expected):
    cam = VirtualA7III(grey_scene())
    cam.state.gamma, cam.state.iso = gamma, iso
    assert cam.conversion_gain == expected


def test_read_noise_drops_at_hcg():
    cam = VirtualA7III(grey_scene())
    cam.state.iso = 500
    rn500 = cam.read_noise_e
    cam.state.iso = 640
    assert cam.read_noise_e < rn500 / 1.8


def _banding(shutter, mains=50.0):
    cam = VirtualA7III(Scene(background_depth=3.0, texture_scale=None, ev100=9, flicker_hz=mains), seed=2)
    cam.state.shutter, cam.state.af_mode = shutter, "MF"
    rows = cam.render(noise=False).linear[..., 1].mean(axis=1)
    return rows.std() / rows.mean()


def test_flicker_banding_depends_on_shutter():
    assert _banding(Fraction(1, 50)) < 0.002
    assert _banding(Fraction(1, 100)) < 0.002
    assert _banding(Fraction(1, 125)) > 0.02
    assert _banding(Fraction(1, 60), mains=60) < 0.002


def test_defocus_softens_off_plane_detail():
    cam = VirtualA7III(walking_subject_scene(), seed=0)
    cam.state.af_mode = "MF"
    cam.state.f_number = 1.8
    cam.state.focus_step = cam.lens.step_for_distance(6000)
    sharp_bg = np.var(np.diff(cam.render(noise=False).linear[:40, 200:, 1], axis=1))
    cam.state.focus_step = cam.lens.step_for_distance(700)
    soft_bg = np.var(np.diff(cam.render(noise=False).linear[:40, 200:, 1], axis=1))
    assert soft_bg < 0.2 * sharp_bg


def _settled_travel(cam, settle_s=1.0, window_s=1.0):
    cam.advance(settle_s, record=False)
    n = len(cam.focus_log)
    cam.advance(window_s, record=False)
    steps = [s for _, s in cam.focus_log[n - 1:]]
    return float(np.abs(np.diff(steps)).sum())


def test_pdaf_vs_cdaf_in_movie():
    pdaf = VirtualA7III(Scene(background_depth=3.0), seed=0)
    pdaf.state.f_number, pdaf.state.focus_step = 8, 100
    assert _settled_travel(pdaf) < 1.0  # locks and stays put
    assert pdaf.focus_distance_mm == pytest.approx(3000, rel=0.02)
    cdaf = VirtualA7III(Scene(background_depth=3.0), seed=0)
    cdaf.state.f_number, cdaf.state.focus_step = 16, 100
    assert not cdaf.pdaf_available
    assert _settled_travel(cdaf) > 100  # keeps hunting after it should have settled


def test_rolling_shutter_skews_moving_subject():
    fast = walking_subject_scene(speed_mps=6.0)
    still = VirtualA7III(fast, seed=0)
    still.state.af_mode = "MF"
    d_still = still.render(still=True, noise=False).depth
    rs = VirtualA7III(fast, seed=0)
    rs.state.af_mode = "MF"
    d_rs = rs.render(noise=False).depth

    def left_edge(d, row):
        cols = np.where(d[row] < 3)[0]
        return cols.min()

    skew_still = left_edge(d_still, 170) - left_edge(d_still, 75)
    skew_rs = left_edge(d_rs, 170) - left_edge(d_rs, 75)
    assert skew_rs - skew_still > 3


def test_ptp_device_protocol_rules():
    cam = VirtualA7III(grey_scene())
    drv = SonyCamera(SimTransport(cam))
    drv.open()
    with pytest.raises(PTPError):
        drv.set_prop("iso", 800)  # before SDIO handshake
    drv.sdio_handshake()
    drv.set_prop("iso", 800)
    with pytest.raises(PTPError):
        drv.set_prop("iso", 777)  # not a valid ISO
    with pytest.raises(PTPError):
        drv.press("shutter_release", hold_s=0)  # movie mode
    assert cam.state.iso == 800


def test_driver_controls_simulated_camera():
    drv, cam = connect_simulated(Scene(background_depth=3.0))
    drv.set_prop("shutter_speed", (1 << 16) | 100)
    drv.set_prop("f_number", 560)
    assert cam.state.shutter == Fraction(1, 100) and cam.state.f_number == 5.6
    assert drv.get_value("f_number") == 560
    before = cam.state.focus_step
    drv.set_prop("focus_mode", 1)  # MF
    drv.focus_step(-3)
    assert cam.state.focus_step == before - 10
    drv.press("movie_record", hold_s=0)
    cam.advance(0.5)
    assert cam.state.recording and len(cam.recorded) == 11  # 0.5 s at 23.976 fps
    lv = drv.liveview()
    assert lv.jpeg[:2] == b"\xff\xd8" and lv.focus_frames


def test_codec_round_trips():
    blob = pack_liveview(b"\xff\xd8jpg\xff\xd9", [FocusFrame(0.25, 0.5, 0.1, 0.1, "eye")], 7, 1234)
    lv = parse_liveview(blob)
    assert lv.sequence == 7 and lv.timestamp_ms == 1234 and lv.focus_frames[0].status == "eye"
    props = parse_props(pack_props([PropDesc(0xD21E, DataType.UINT32, 640, form=FORM_ENUM, values=[100, 640])]))
    assert props[0xD21E].value == 640 and props[0xD21E].values == [100, 640]
    assert decode_touch_af(encode_touch_af(0.123, 0.987)) == pytest.approx((0.123, 0.987), abs=1e-4)
