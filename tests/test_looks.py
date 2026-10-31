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
