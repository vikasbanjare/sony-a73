from fractions import Fraction

import numpy as np
import pytest

from a7iii.af import AFConfig, AFController, FrameGeometry
from a7iii.ptp.automation import (
    ApertureGuard,
    FocusMotorModel,
    LensFocusMap,
    PtpAFSink,
    apply_cine_ei,
    apply_shutter_angle,
    focus_bracket,
    rack_focus,
)
from a7iii.sim import GroundTruthDetector, Lens, Scene, SimClock, connect_simulated, macro_scene, walking_subject_scene


def test_shutter_angle_and_cine_ei_pushed_over_ptp():
    drv, cam = connect_simulated(Scene())
    sol = apply_shutter_angle(drv, 23.976, 180, mains_hz=50)
    assert cam.state.shutter == Fraction(1, 50) == sol.speed
    cam.state.gamma = "S-Log3"
    ei = apply_cine_ei(drv, "slog3", "high")
    assert cam.state.iso == 5000 and cam.conversion_gain == "HCG"
    assert ei.monitor_offset_ev(10000) == pytest.approx(1.0)


def test_aperture_guard_alerts_on_transition():
    drv, cam = connect_simulated(Scene())
    events = []
    guard = ApertureGuard(drv, on_change=events.append)
    drv.set_prop("f_number", 800)
    assert guard.poll().ok
    drv.set_prop("f_number", 1300)
    assert not guard.poll().ok
    guard.poll()
    assert [e.ok for e in events] == [True, False]
    statuses = guard.run(SimClock(cam), 1.0, rate_hz=10)
    assert len(statuses) == 10 and not any(s.ok for s in statuses)


def test_motor_decomposition():
    m = FocusMotorModel()
    assert sum(m.step_sizes[abs(c)] for c in m.decompose(257)) == 257
    assert all(c < 0 for c in m.decompose(-15))
    assert m.decompose(0) == []


def test_focus_bracket_on_simulated_macro():
    lens = Lens(focal_mm=90, min_focus_mm=280, max_f_number=2.8)
    drv, cam = connect_simulated(macro_scene(0.30, 0.36), lens=lens)
    cam.state.movie_mode = False
    lens_map = LensFocusMap(lens.distance_for_step, lens.step_for_distance)
    plan = focus_bracket(drv, SimClock(cam), 90, 5.6, 300, 360, lens_map)
    assert len(cam.captured) == len(plan) >= 4
    shot_focus = [f.meta["focus_mm"] for f in cam.captured]
    np.testing.assert_allclose(shot_focus, plan, rtol=0.01)


def test_rack_focus_reaches_target_smoothly():
    drv, cam = connect_simulated(Scene())
    drv.set_prop("focus_mode", 1)
    start = cam.state.focus_step
    n0 = len(cam.focus_log)
    rack_focus(drv, SimClock(cam, record=False), -200, 1.0, tick_hz=24)
    assert cam.state.focus_step == start - 200
    moves = np.diff([s for _, s in cam.focus_log[n0:]])
    assert moves[0] > moves[len(moves) // 2]  # eased: small first, bigger in the middle (negative values)


def test_closed_loop_ai_af_tracks_walking_subject():
    """Detector -> AFController -> PTP Touch-AF -> simulated PDAF: subject stays sharp."""
    drv, cam = connect_simulated(walking_subject_scene(speed_mps=0.5, depth=2.0), seed=3)
    drv.set_prop("f_number", 180)
    det = GroundTruthDetector(seed=1)
    ctl = AFController(PtpAFSink(drv), FrameGeometry(cam.W, cam.H), AFConfig(latency_s=0.03))
    errors = []
    for _ in range(48):  # 2 s
        cam.advance(1 / cam.state.fps, record=False)
        frame = cam.render(noise=False)
        ctl.step(cam.t, det.detect(frame))
        errors.append(abs(cam.focus_distance_mm - frame.keypoints["depth"] * 1000))
    # after acquisition the focus stays on the subject (within DoF at f/1.8, ~ +/- 60 mm at 2 m)
    assert np.median(errors[12:]) < 60
