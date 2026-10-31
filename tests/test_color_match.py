import numpy as np
import pytest

from a7iii.color.chart_solver import solve_ccm
from a7iii.color.colorimetry import delta_e_2000
from a7iii.color.lut import apply_lut_trilinear, build_lut, read_cube, write_cube

# Sharma, Wu & Dalal (2005) CIEDE2000 test data, first pairs.
SHARMA = [
    ((50.0, 2.6772, -79.7751), (50.0, 0.0, -82.7485), 2.0425),
    ((50.0, 3.1571, -77.2803), (50.0, 0.0, -82.7485), 2.8615),
    ((50.0, 2.8361, -74.0200), (50.0, 0.0, -82.7485), 3.4412),
    ((50.0, -1.3802, -84.2814), (50.0, 0.0, -82.7485), 1.0000),
    ((50.0, 0.0, 0.0), (50.0, -1.0, 2.0), 2.3669),
    ((50.0, 2.5, 0.0), (73.0, 25.0, -18.0), 27.1492),
    ((2.0776, 0.0795, -1.1350), (0.9033, -0.0636, -0.5514), 0.9082),
]


@pytest.mark.parametrize("lab1,lab2,expected", SHARMA)
def test_ciede2000_reference_values(lab1, lab2, expected):
    assert delta_e_2000(np.array(lab1), np.array(lab2)) == pytest.approx(expected, abs=1e-4)
    assert delta_e_2000(np.array(lab2), np.array(lab1)) == pytest.approx(expected, abs=1e-4)


def _synthetic_chart(seed=0):
    rng = np.random.default_rng(seed)
    target = rng.uniform(0.03, 0.8, size=(24, 3))
    m_true = np.array([[1.15, -0.10, -0.05], [-0.08, 1.12, -0.04], [0.02, -0.15, 1.13]])
    source = target @ np.linalg.inv(m_true).T
    return source, target, rng


def test_solver_recovers_linear_matrix():
    source, target, _ = _synthetic_chart()
    res = solve_ccm(source, target, refine=False)
    assert res.mean_delta_e < 1e-6


def test_solver_meets_roadmap_gate_with_noise():
    # Roadmap phase 2 gate: mean dE2000 < 1.5, skin patches < 1.0.
    source, target, rng = _synthetic_chart(1)
    noisy = source * rng.normal(1.0, 0.01, size=source.shape)
    res = solve_ccm(noisy, target, degree=2)
    assert res.mean_delta_e < 1.5
    assert np.all(res.delta_e[[0, 1, 11]] < 1.0)


def test_cube_round_trip_and_identity(tmp_path):
    table = build_lut(lambda rgb: rgb, size=9)
    path = tmp_path / "id.cube"
    write_cube(path, table)
    loaded = read_cube(path)
    np.testing.assert_allclose(loaded, table, atol=1e-6)
    pts = np.random.default_rng(2).uniform(0, 1, size=(50, 3))
    np.testing.assert_allclose(apply_lut_trilinear(loaded, pts), pts, atol=1e-6)


def test_lut_red_varies_fastest():
    table = build_lut(lambda rgb: rgb, size=3)
    assert table[1].tolist() == [0.5, 0.0, 0.0]
    assert table[3].tolist() == [0.0, 0.5, 0.0]
