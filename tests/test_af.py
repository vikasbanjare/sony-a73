import numpy as np
import pytest

from a7iii.af import AFConfig, AFController, Detection, FrameGeometry, PointKalman, choose_subject, focus_point
from a7iii.af.types import L_EYE, L_SHOULDER, NOSE, R_EYE, R_HIP, R_SHOULDER, L_HIP


def person(x, y, tid=1, size=0.2, eyes=True, head=True, score=0.9):
    kp = np.zeros((17, 3))
    if eyes:
        kp[L_EYE] = (x - 0.01, y, 0.9)
        kp[R_EYE] = (x + 0.01, y, 0.6)
    if head:
        kp[NOSE] = (x, y + 0.01, 0.9)
    for i, (dx, dy) in {L_SHOULDER: (-0.03, 0.05), R_SHOULDER: (0.03, 0.05), L_HIP: (-0.02, 0.15), R_HIP: (0.02, 0.15)}.items():
        kp[i] = (x + dx, y + dy, 0.9)
    return Detection((x - size / 2, y - 0.05, x + size / 2, y - 0.05 + size * 2), score, "person", tid, kp)


def test_focus_point_priority():
    assert focus_point(person(0.5, 0.3)).part == "eye"
    assert focus_point(person(0.5, 0.3)).x == pytest.approx(0.49)  # more confident eye
    assert focus_point(person(0.5, 0.3, eyes=False)).part == "head"
    assert focus_point(person(0.5, 0.3, eyes=False, head=False)).part == "torso"
    box = Detection((0.2, 0.2, 0.4, 0.8), 0.9, "person")
    fp = focus_point(box)
    assert fp.part == "box" and fp.y == pytest.approx(0.4)


def test_choose_subject_keeps_lock_and_filters():
    big = person(0.3, 0.3, tid=1, size=0.4)
    small = person(0.7, 0.3, tid=2, size=0.1)
    car = Detection((0, 0, 1, 1), 0.99, "car", 3)
    assert choose_subject([big, small, car], labels=("person",)).track_id == 1
    assert choose_subject([big, small], locked_id=2).track_id == 2
    assert choose_subject([car], labels=("person",)) is None


def test_kalman_predicts_ahead_of_moving_subject():
    kf = PointKalman()
    for i in range(30):
        t = i / 30
        kf.update(t, 0.2 + 0.3 * t, 0.5)  # 0.3 frame-widths per second
    x, _ = kf.predict(29 / 30 + 0.1)
    assert x == pytest.approx(0.2 + 0.3 * (29 / 30 + 0.1), abs=0.01)
    assert kf.velocity[0] == pytest.approx(0.3, abs=0.02)


def test_geometry_pillarbox():
    g = FrameGeometry.fit(1920, 1080, 3 / 2)  # 3:2 live view in 16:9
    assert g.active_w == 1620 and g.active_x == 150
    assert g.to_image(0.5, 0.5) == pytest.approx((0.5, 0.5))
    assert g.to_image(0.02, 0.5) is None
    assert g.to_image(150 / 1920, 0.0) == pytest.approx((0.0, 0.0))


def make_controller(**cfg):
    sent = []
    ctl = AFController(lambda u, v: sent.append((u, v)), FrameGeometry(1920, 1080), AFConfig(**cfg))
    return ctl, sent


def test_controller_rate_limit_and_deadband():
    ctl, sent = make_controller(max_rate_hz=10, latency_s=0.0)
    for i in range(30):  # 1 s of 30 fps, subject moving
        ctl.step(i / 30, [person(0.2 + 0.01 * i, 0.4)])
    assert 8 <= len(sent) <= 11
    ctl2, sent2 = make_controller(max_rate_hz=100, latency_s=0.0)
    for i in range(30):  # stationary subject
        ctl2.step(i / 30, [person(0.5, 0.4)])
    assert len(sent2) == 1


def test_controller_suppressed_past_f11_in_movie():
    ctl, sent = make_controller()
    ctl.set_lens_state(16, movie_mode=True)
    step = ctl.step(0.0, [person(0.5, 0.4)])
    assert not sent and "PDAF" in step.warnings[0] and step.status.startswith("suppressed")
    ctl.set_lens_state(16, movie_mode=False)
    assert ctl.step(1.0, [person(0.5, 0.4)]).status == "sent"


def test_controller_locks_and_releases():
    ctl, sent = make_controller(latency_s=0.0, lost_after_s=0.3)
    ctl.step(0.0, [person(0.3, 0.4, tid=7, size=0.3)])
    assert ctl.locked_id == 7
    # a bigger subject appears; lock stays on #7
    ctl.step(0.2, [person(0.3, 0.4, tid=7, size=0.3), person(0.8, 0.4, tid=9, size=0.6)])
    assert sent[-1][0] < 0.5
    ctl.step(0.3, [])
    step = ctl.step(0.7, [])
    assert "lost subject #7" in step.warnings
