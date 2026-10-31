import numpy as np
import pytest

from a7iii.color.chart_solver import solve_ccm
from a7iii.color.chroma import quantize_tpdf, upsample_chroma, yuv420_to_rgb444
from a7iii.color.colorimetry import delta_e_2000, linear_rgb_to_lab
from a7iii.color.dctl import lut_dctl, matrix_dctl
from a7iii.color.lut import apply_lut_trilinear, build_lut
from a7iii.color.oklab import linear_rgb_to_oklab, oklab_to_linear_rgb
from a7iii.color.residual import fit_residual, match_transform
from a7iii.color.transfer import encode


def test_oklab_white_and_round_trip():
    np.testing.assert_allclose(linear_rgb_to_oklab(np.ones(3)), [1.0, 0.0, 0.0], atol=1e-4)
    rgb = np.random.default_rng(0).uniform(0, 1, (100, 3))
    np.testing.assert_allclose(oklab_to_linear_rgb(linear_rgb_to_oklab(rgb)), rgb, atol=1e-9)


def _nonlinear_camera(target):
    """A 'camera' whose error a 3x3 can't fully model (hue twist in reds)."""
    src = target @ np.array([[0.9, 0.08, 0.02], [0.05, 0.9, 0.05], [0.0, 0.1, 0.9]]).T
    src[:, 0] = src[:, 0] ** 1.15
    return src


def test_residual_stage_reduces_error_beyond_ccm():
    rng = np.random.default_rng(3)
    target = rng.uniform(0.05, 0.7, (24, 3))
    source = _nonlinear_camera(target)
    ccm = solve_ccm(source, target, refine=False)
    after_ccm = ccm.apply(source)
    res = fit_residual(after_ccm, target)
    after_res = res(after_ccm)
    de_ccm = delta_e_2000(linear_rgb_to_lab(after_ccm), linear_rgb_to_lab(target)).mean()
    de_res = delta_e_2000(linear_rgb_to_lab(after_res), linear_rgb_to_lab(target)).mean()
    assert de_res < 0.2 * de_ccm


def test_residual_fades_far_from_chart():
    rng = np.random.default_rng(4)
    target = rng.uniform(0.3, 0.5, (24, 3))  # chart occupies a small region
    after = target * 1.03
    res = fit_residual(after, target)
    far = np.array([[0.02, 0.9, 0.02]])  # saturated green, nowhere near the chart
    np.testing.assert_allclose(res(far), far, rtol=1e-4)


def test_identity_match_transform_lut():
    rng = np.random.default_rng(5)
    rgb = rng.uniform(0.05, 0.6, (24, 3))
    ccm = solve_ccm(rgb, rgb, refine=False)
    lut = build_lut(match_transform("slog3", "slog3", ccm), size=17)
    pts = encode("slog3", rng.uniform(0.02, 0.8, (30, 3)))
    np.testing.assert_allclose(apply_lut_trilinear(lut, pts), pts, atol=2e-3)


def test_dctl_text():
    text = matrix_dctl(np.eye(3))
    assert "__DEVICE__ float3 transform" in text and "1.00000000f * p_R" in text
    with pytest.raises(ValueError):
        matrix_dctl(np.ones((3, 6)))
    assert 'DEFINE_LUT(MatchLUT, "match.cube")' in lut_dctl("/tmp/x/match.cube")


def test_flat_chroma_reconstructs_exactly():
    y = np.random.default_rng(6).uniform(0, 1, (8, 10))
    c = np.full((4, 5), 0.37)
    np.testing.assert_allclose(upsample_chroma(y, c), 0.37, atol=1e-6)


def test_joint_bilateral_keeps_colour_edge_on_luma_edge():
    # Vertical edge at column 5 (odd -> falls between chroma samples).
    h, w = 8, 12
    y = np.zeros((h, w)); y[:, 5:] = 1.0
    full_c = np.zeros((h, w)); full_c[:, 5:] = 1.0
    c = full_c[::2, ::2]  # left-sited horizontal subsampling
    up = upsample_chroma(y, c)
    assert np.all(up[:, :4] < 0.05) and np.all(up[:, 6:] > 0.95)
    assert up[:, 5].mean() > 0.9  # column 5 follows luma, not the chroma sample to its left


def test_yuv_grey_and_range():
    y = np.full((4, 4), 126, np.uint8)  # mid grey in narrow range
    cb = cr = np.full((2, 2), 128, np.uint8)
    rgb = yuv420_to_rgb444(y, cb, cr)
    assert rgb.dtype == np.float32
    np.testing.assert_allclose(rgb, (126 - 16) / 219, atol=1e-6)
    white = yuv420_to_rgb444(np.full((2, 2), 235, np.uint8), np.full((1, 1), 128, np.uint8), np.full((1, 1), 128, np.uint8))
    np.testing.assert_allclose(white, 1.0, atol=1e-6)


def test_tpdf_quantisation_unbiased():
    x = np.full(200_000, 100.3 / 255)
    q = quantize_tpdf(x, 8, np.random.default_rng(7))
    assert q.mean() == pytest.approx(100.3, abs=0.02)
    assert set(np.unique(q)) <= {99, 100, 101, 102}
