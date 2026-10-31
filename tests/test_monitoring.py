import numpy as np
import pytest

from a7iii.cinema.cine_ei import CineEI, display_tonemap, monitor_lut, monitor_transform
from a7iii.cinema.framing import aspect_guide, desqueeze, draw_guides, standard_guides
from a7iii.cinema.scopes import clipping_report, histogram, rgb_parade, to_image, vectorscope, waveform
from a7iii.color.lut import apply_lut_trilinear
from a7iii.color.transfer import encode
from a7iii.optics.breathing import BreathingProfile, scale_about_center
from a7iii.optics.focus_map import BEHIND, FRONT, IN_FOCUS, classify, overlay


def test_waveform_places_levels():
    f = np.zeros((10, 4, 3))
    f[:, :2] = 1.0
    wf = waveform(f[..., 0], levels=11)
    assert wf[0, :2].sum() == 20 and wf[10, 2:].sum() == 20
    assert rgb_parade(f, levels=11).shape == (11, 12, 3)


def test_vectorscope_grey_at_centre_red_up_left():
    grey = np.full((4, 4, 3), 0.5)
    vs = vectorscope(grey, size=101)
    assert vs[50, 50] == 16
    red = np.zeros((4, 4, 3)); red[..., 0] = 0.8
    ys, xs = np.nonzero(vectorscope(red, size=101))
    assert ys[0] < 50 and xs[0] < 60  # Cr positive (up), Cb slightly negative


def test_histogram_and_clipping():
    f = np.concatenate([np.zeros((5, 4, 3)), np.ones((5, 4, 3))])
    h = histogram(f, bins=4)
    assert h[0, 0] == 20 and h[0, 3] == 20
    rep = clipping_report(f)
    assert rep["crushed"] == 0.5 and rep["clipped"] == 0.5
    assert to_image(h).dtype == np.uint8


def test_desqueeze_2x():
    f = np.random.default_rng(0).random((10, 20, 3))
    out = desqueeze(f, 2.0)
    assert out.shape == (10, 40, 3)
    np.testing.assert_allclose(out[:, 0], f[:, 0])
    np.testing.assert_allclose(out[:, -1], f[:, -1])
    assert desqueeze(f, 2.0, keep_height=False).shape == (5, 20, 3)


def test_aspect_guides():
    g = aspect_guide(1920, 1080, 2.39)
    assert (g.x1 - g.x0, g.y1 - g.y0) == (1920, 803)
    v = aspect_guide(1920, 1080, 9 / 16)
    assert v.y1 - v.y0 == 1080 and v.x1 - v.x0 == 608
    out = draw_guides(np.zeros((108, 192, 3)), standard_guides(192, 108), dim_outside=g)
    assert out.max() == 1.0


def test_monitor_lut_ei_offset():
    ei = CineEI("slog3", "low")
    grey = encode("slog3", np.full((1, 3), 0.18))
    base = monitor_transform("slog3", 0.0)(grey)[0, 0]
    plus1 = monitor_transform("slog3", ei.monitor_offset_ev(1600))(grey)[0, 0]
    assert base == pytest.approx(float(encode("rec709", 0.18)), abs=1e-6)  # grey preserved below knee
    assert plus1 == pytest.approx(float(encode("rec709", 0.36)), abs=1e-6)
    lut = monitor_lut(ei, 1600, "slog3", size=17)
    assert apply_lut_trilinear(lut, grey)[0, 0] == pytest.approx(plus1, abs=0.01)
    tm = display_tonemap(np.array([0.5, 1.0, 4.0, 100.0]))
    assert np.all(np.diff(tm) >= 0) and tm.max() <= 1.0


def test_focus_map_classes():
    depth = np.array([[1.0, 2.0, 5.0]])
    cls = classify(depth, 50, 2.0, 2000)
    assert cls.tolist() == [[FRONT, IN_FOCUS, BEHIND]]
    assert overlay(np.zeros((1, 3, 3)), cls).shape == (1, 3, 3)


def test_breathing_frame_compensation_restores_size():
    prof = BreathingProfile(50, k1=-0.1)
    yy, xx = np.mgrid[0:101, 0:101]
    disc = (((xx - 50) ** 2 + (yy - 50) ** 2) <= 20**2).astype(float)
    shrunk = scale_about_center(disc, prof.magnification(500))  # close focus widens FOV -> subject smaller
    scale = float(prof.compensation_scale(500, near_mm=500))
    fixed = scale_about_center(shrunk, scale)
    far_scale = float(prof.compensation_scale(1e9, near_mm=500))
    reference = scale_about_center(disc, far_scale * prof.magnification(1e9))
    assert abs(fixed.sum() - reference.sum()) / reference.sum() < 0.03
