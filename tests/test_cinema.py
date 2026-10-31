from fractions import Fraction

import numpy as np
import pytest

from a7iii.cinema.cine_ei import CineEI
from a7iii.cinema.false_color import ZONES, false_color, zone_histogram, zone_index
from a7iii.cinema.ring_buffer import PreRollBuffer
from a7iii.cinema.shutter import is_flicker_free, solve_shutter, sony_ptp_shutter_value
from a7iii.color.transfer import encode


def test_180_degree_at_24p():
    s = solve_shutter(23.976, 180)
    assert s.speed == Fraction(1, 50)
    assert s.effective_angle == pytest.approx(172.6, abs=0.1)


def test_roadmap_example_50hz():
    s = solve_shutter(23.976, 180, mains_hz=50)
    assert s.speed == Fraction(1, 50) and s.flicker_free


def test_60hz_at_24p_picks_nearest_flicker_free():
    # 1/120 does not exist on the a7 III. Of the flicker-free speeds, 1/40
    # (3 x 1/120) is +0.26 stops from 180 deg, closer than 1/60 at -0.32.
    s = solve_shutter(23.976, 180, mains_hz=60)
    assert s.speed == Fraction(1, 40)
    assert s.flicker_free and s.warnings


def test_movie_mode_never_slower_than_frame():
    s = solve_shutter(60, 360)
    assert float(s.speed) <= 1 / 60


def test_flicker_rules():
    assert is_flicker_free(1 / 100, 50)
    assert is_flicker_free(1 / 50, 50)
    assert not is_flicker_free(1 / 125, 50)
    assert not is_flicker_free(1 / 200, 50)  # shorter than one flicker period


def test_ptp_shutter_encoding():
    assert sony_ptp_shutter_value(Fraction(1, 50)) == 0x00010032
    assert sony_ptp_shutter_value(Fraction(13, 10)) == (13 << 16) | 10
    assert sony_ptp_shutter_value(Fraction(2)) == (2 << 16) | 1


def test_cine_ei():
    ei = CineEI("slog3", "low")
    assert ei.recording_iso == 800
    assert ei.monitor_offset_ev(1600) == pytest.approx(1.0)
    assert CineEI("hlg3", "high").recording_iso == 800
    with pytest.raises(ValueError):
        ei.monitor_offset_ev(6400)


def test_false_color_middle_grey_is_grey_in_every_curve():
    grey_idx = next(i for i, z in enumerate(ZONES) if "middle grey" in z[2])
    for curve in ("slog3", "slog2", "hlg", "rec709"):
        frame = np.full((2, 2, 3), float(encode(curve, 0.18)))
        assert (zone_index(np.zeros(1)) == grey_idx).all()
        out = false_color(frame, curve)
        assert tuple(out[0, 0]) == ZONES[grey_idx][1], curve


def test_false_color_stops():
    # +3.5 stops over grey in S-Log3 -> "bright highlight" zone.
    frame = np.full((1, 1, 3), float(encode("slog3", 0.18 * 2**3.5)))
    hist = zone_histogram(frame, "slog3")
    assert hist["+3 to +5: bright highlight"] == 1.0


def test_preroll_buffer_keeps_window():
    buf = PreRollBuffer(seconds=2.0)
    for i in range(100):
        buf.push(i / 24, i, size_bytes=10)
    frames = buf.flush()
    assert frames[-1].payload == 99
    assert frames[-1].timestamp - frames[0].timestamp <= 2.0
    assert len(frames) == 49
    assert len(buf) == 0 and buf.nbytes == 0


def test_preroll_byte_cap():
    buf = PreRollBuffer(seconds=10.0, max_bytes=50)
    for i in range(20):
        buf.push(i, i, size_bytes=10)
    assert buf.nbytes <= 50 and len(buf) == 5
    with pytest.raises(ValueError):
        buf.push(0, "late")
