import numpy as np

from a7iii.color.looks import INPUTS, LOOKS, gamut_matrix, look_transform, write_lut_pack
from a7iii.color.lut import read_cube
from a7iii.color.transfer import encode


def test_sgamut3cine_matrix_matches_sony_published():
    m = gamut_matrix("sgamut3cine", "rec709")
    sony = np.array([[1.6269, -0.5401, -0.0868], [-0.1785, 1.4179, -0.2394], [-0.0444, -0.1959, 1.2404]])
    assert np.allclose(m, sony, atol=2e-3)
    assert np.allclose(m.sum(axis=1), 1.0)  # white stays white


def test_grey_lands_on_rec709_grey_and_technical_is_neutral():
    for src, (curve, _) in INPUTS.items():
        grey = encode(curve, np.full((1, 3), 0.18))
        out = look_transform(src, "technical")(grey)[0]
        assert np.allclose(out, 0.409, atol=0.003), src
        assert look_transform(src, "portrait")(grey)[0][0] > out[0]  # portrait is warmer


def test_lut_pack_writes_every_input_and_look(tmp_path):
    files = write_lut_pack(tmp_path, sizes=(17,))
    assert len(files) == len(INPUTS) * len(LOOKS) * 2
    t = read_cube(tmp_path / "a7iii_slog3_to_709_technical_17.cube")
    assert t.shape == (17**3, 3) and t.min() >= 0 and t.max() <= 1


def test_skin_protection_keeps_skin_and_mutes_the_rest():
    from a7iii.color.colorchecker import reference_linear
    from a7iii.color.looks import saturate
    from a7iii.color.oklab import linear_rgb_to_oklab

    ref = reference_linear()
    skin, blue = ref[1:2], ref[12:13]  # light skin, blue
    chroma = lambda x: np.hypot(*linear_rgb_to_oklab(x)[0, 1:])
    assert chroma(saturate(skin, 0.7, 1.0)) > 0.95 * chroma(skin)
    assert chroma(saturate(blue, 0.7, 1.0)) < 0.75 * chroma(blue)


def test_every_creative_look_renders_in_range():
    grey = encode("slog3", np.full((1, 3), 0.18))
    for look in LOOKS:
        out = look_transform("slog3", look)(grey)[0]
        assert 0.0 <= out.min() and out.max() <= 1.0, look
    bw = look_transform("slog3", "cl_bw")(encode("slog3", np.array([[0.3, 0.1, 0.05]])))[0]
    assert np.ptp(bw) < 1e-9  # black & white really is mono


def test_chart_sample_and_colorchecker_calibration():
    from a7iii.color.chart_solver import solve_ccm
    from a7iii.color.colorchecker import reference_linear, sample_chart
    from a7iii.color.transfer import decode

    ref = reference_linear()
    skew = np.array([[0.9, 0.12, -0.02], [0.05, 0.85, 0.1], [0.0, 0.08, 0.92]])  # a camera that is "off"
    seen = encode("slog3", ref @ skew.T)
    img = np.zeros((400, 600, 3))
    for i, c in enumerate(seen):  # paint a 6x4 chart, patch centres 100 px apart
        y, x = 50 + 100 * (i // 6), 50 + 100 * (i % 6)
        img[y - 30:y + 30, x - 30:x + 30] = c
    got = sample_chart(img, [(50, 50), (550, 50), (50, 350), (550, 350)])
    assert np.allclose(got, seen, atol=1e-9)
    ccm = solve_ccm(decode("slog3", got), ref)
    assert ccm.mean_delta_e < 1.0  # calibrated to the published chart, no FX3 needed


def test_fxdefault_warms_skin_and_keeps_greys_on_default_footage():
    from a7iii.color.colorchecker import reference_linear
    from a7iii.color.oklab import linear_rgb_to_oklab
    from a7iii.color.transfer import rec709_decode

    f = look_transform("std709", "fxdefault")
    grey = encode("rec709", np.full((1, 3), 0.18))
    assert np.allclose(f(grey), grey, atol=0.004)  # neutral stays neutral, exposure unchanged
    hue = lambda sig: np.degrees(np.arctan2(*linear_rgb_to_oklab(rec709_decode(sig))[0, [2, 1]]))
    skin = encode("rec709", reference_linear()[1:2])
    assert hue(f(skin)) < hue(skin) - 2  # skin rotated away from green-yellow toward red
