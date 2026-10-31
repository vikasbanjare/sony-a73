import math

import numpy as np
import pytest

from a7iii.optics.af_guard import check_aperture, f_number_from_ptp
from a7iii.optics.breathing import BreathingProfile, fit_breathing
from a7iii.optics.dof import depth_of_field, focus_bracket_plan, hyperfocal
from a7iii.optics.rack_focus import EASE_IN_OUT, cubic_bezier_ease, rack_schedule
from a7iii.optics.rolling_shutter import readout_ms, skew_pixels


def test_hyperfocal_50mm_f8():
    # 50^2 / (8 * 0.03) + 50 = 10466.7 mm
    assert hyperfocal(50, 8, 0.03) == pytest.approx(10466.67, rel=1e-4)


def test_dof_at_hyperfocal_reaches_infinity():
    H = hyperfocal(35, 11)
    dof = depth_of_field(35, 11, H)
    assert math.isinf(dof.far)
    assert dof.near == pytest.approx(H / 2, rel=0.01)


def test_dof_brackets_focus_distance():
    dof = depth_of_field(85, 1.8, 2000)
    assert dof.near < 2000 < dof.far
    assert dof.total < 100  # shallow


def test_focus_bracket_plan_covers_range_with_overlap():
    plan = focus_bracket_plan(90, 5.6, 300, 600, overlap=0.1)
    assert len(plan) > 3
    assert plan == sorted(plan)
    first = depth_of_field(90, 5.6, plan[0], 0.019)
    assert first.near == pytest.approx(300, rel=1e-6)
    for a, b in zip(plan, plan[1:]):
        assert depth_of_field(90, 5.6, b, 0.019).near <= depth_of_field(90, 5.6, a, 0.019).far
    assert depth_of_field(90, 5.6, plan[-1], 0.019).far >= 600
    # steps grow with distance
    gaps = np.diff(plan)
    assert gaps[-1] > gaps[0]


def test_focus_bracket_ends_at_hyperfocal():
    plan = focus_bracket_plan(24, 8, 1000, 1e9, coc_mm=0.03)
    assert plan[-1] == pytest.approx(hyperfocal(24, 8, 0.03))


def test_bezier_endpoints_and_monotonic():
    x = np.linspace(0, 1, 101)
    y = EASE_IN_OUT(x)
    assert y[0] == pytest.approx(0) and y[-1] == pytest.approx(1)
    assert np.all(np.diff(y) >= -1e-12)
    linear = cubic_bezier_ease(1 / 3, 1 / 3, 2 / 3, 2 / 3)
    np.testing.assert_allclose(linear(x), x, atol=1e-9)


def test_rack_schedule_sums_and_eases():
    steps = rack_schedule(120, 2.0, tick_hz=30)
    assert sum(steps) == 120 and len(steps) == 60
    assert steps[0] < steps[30]  # slow start, fast middle
    assert sum(rack_schedule(-40, 1.0)) == -40


def test_breathing_fit_and_compensation():
    truth = BreathingProfile(50, k1=-0.12, k2=0.01)
    d = np.array([450, 600, 1000, 2000, 5000, 20000])
    fitted = fit_breathing(50, d, truth.magnification(d))
    assert fitted.k1 == pytest.approx(-0.12, abs=1e-9)
    scale = fitted.compensation_scale(d, near_mm=450)
    assert np.all(scale >= 1.0 - 1e-12)
    # after scaling, every frame has the same magnification
    np.testing.assert_allclose(scale * fitted.magnification(d), (scale * fitted.magnification(d))[0])


def test_af_guard():
    assert check_aperture(11, movie_mode=True).ok
    assert not check_aperture(13, movie_mode=True).ok
    assert check_aperture(16, movie_mode=False).ok
    assert f_number_from_ptp(560) == 5.6


def test_rolling_shutter():
    assert readout_ms("s35_4k_24p") < readout_ms("ff_4k_24p")
    # 30 deg/s pan, 54 deg hfov, 3840 px: ~52 px skew in FF 4K
    assert skew_pixels("ff_4k_24p", 30, 54, 3840) == pytest.approx(52.05, abs=0.1)
