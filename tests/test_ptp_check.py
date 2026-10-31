from a7iii.ptp.check import run
from a7iii.ptp.session import SonyCamera
from a7iii.sim import SimTransport, VirtualA7III, walking_subject_scene


def test_ptp_check_on_simulated_body_reads_writes_and_restores():
    cam = VirtualA7III(walking_subject_scene())
    checks = {c.name: c for c in run(SonyCamera(SimTransport(cam)), write=True, frames=3, settle_s=0)}
    assert checks["read properties"].ok and checks["live view"].ok
    for name in ("shutter_speed", "iso", "f_number"):
        assert checks[f"write {name}"].ok, checks[f"write {name}"].detail
    assert cam.state.iso == 100  # restored to where it started
    assert checks["prop touch_af_position"].ok is None  # unreported codes are skips, not passes
