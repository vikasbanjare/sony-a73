import numpy as np
import pytest

from a7iii.color import transfer as tf


@pytest.mark.parametrize("curve", ["slog3", "slog2", "hlg", "rec709"])
def test_round_trip(curve):
    x = np.geomspace(1e-3, 4.0, 200)
    if curve == "hlg":
        x = x[x <= 1.0 / tf.HLG_REFERENCE_WHITE_E]  # HLG tops out at E = 1
    np.testing.assert_allclose(tf.decode(curve, tf.encode(curve, x)), x, rtol=1e-9, atol=1e-12)


def test_published_middle_grey_levels():
    # Sony: S-Log3 18% grey = 420/1023 (41%); S-Log2 18% grey ~ 32 IRE.
    assert tf.slog3_encode(0.18) == pytest.approx(420 / 1023)
    slog2_ire = (tf.slog2_encode(0.18) * 1023 - 64) / 876
    assert slog2_ire == pytest.approx(0.32, abs=0.01)
    # S-Log3 90% white = 61% (Sony white paper)
    assert tf.slog3_encode(0.9) * 1023 == pytest.approx(598, abs=1)


def test_hlg_reference_white_is_75_percent():
    assert tf.hlg_encode(1.0) == pytest.approx(0.75)
    assert tf.hlg_oetf(1.0) == pytest.approx(1.0)
    assert tf.hlg_oetf(1 / 12) == pytest.approx(0.5)


def test_unknown_curve():
    with pytest.raises(ValueError):
        tf.decode("vlog", 0.5)
