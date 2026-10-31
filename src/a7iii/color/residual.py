"""Stage 2 of chart matching (roadmap §4.3): non-linear residual correction.

After the CCM, the leftover per-patch error is measured in OKLab and
interpolated with a thin-plate-spline RBF. Away from the chart samples the
correction fades out (Gaussian falloff on distance to the nearest sample),
so colours the chart never saw are left on the CCM result instead of being
extrapolated by the spline.

The linear working space is whatever the decoded camera RGB is; the CCM
absorbs the gamut difference. OKLab is computed as if that space had
Rec.709 primaries, which is fine for measuring *small residuals*.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

import numpy as np

from .chart_solver import MatchResult
from .oklab import linear_rgb_to_oklab, oklab_to_linear_rgb
from .transfer import decode, encode


@dataclass
class ResidualCorrector:
    rbf: Callable[[np.ndarray], np.ndarray] | None
    anchors: np.ndarray  # OKLab sample points
    falloff: float  # OKLab distance at which correction has dropped to ~37%

    def __call__(self, rgb_linear: np.ndarray) -> np.ndarray:
        if self.rbf is None:
            return rgb_linear
        rgb_linear = np.asarray(rgb_linear, dtype=np.float64)
        lab = linear_rgb_to_oklab(np.clip(rgb_linear, 0.0, None))
        d = np.min(np.linalg.norm(lab[:, None, :] - self.anchors[None, :, :], axis=-1), axis=1)
        weight = np.exp(-((d / self.falloff) ** 2))[:, None]
        return oklab_to_linear_rgb(lab + weight * self.rbf(lab))


def fit_residual(
    corrected_rgb: np.ndarray,
    target_rgb: np.ndarray,
    smoothing: float = 1e-4,
    falloff: float = 0.08,
) -> ResidualCorrector:
    """Fit OKLab residuals target - corrected at the chart patches."""
    try:
        from scipy.interpolate import RBFInterpolator
    except ImportError as e:  # pragma: no cover - scipy is a declared extra
        raise ImportError("residual fitting needs scipy: pip install 'a7iii-enhanced-suite[color]'") from e

    src = linear_rgb_to_oklab(np.clip(np.asarray(corrected_rgb, dtype=np.float64), 0.0, None))
    dst = linear_rgb_to_oklab(np.clip(np.asarray(target_rgb, dtype=np.float64), 0.0, None))
    rbf = RBFInterpolator(src, dst - src, kernel="thin_plate_spline", smoothing=smoothing)
    return ResidualCorrector(rbf=rbf, anchors=src, falloff=falloff)


def match_transform(
    in_curve: str,
    out_curve: str,
    ccm: MatchResult,
    residual: ResidualCorrector | None = None,
    exposure_ev: float = 0.0,
) -> Callable[[np.ndarray], np.ndarray]:
    """Signal -> signal transform suitable for ``lut.build_lut``."""
    gain = 2.0**exposure_ev

    def transform(signal: np.ndarray) -> np.ndarray:
        linear = decode(in_curve, signal) * gain
        linear = ccm.apply(linear)
        if residual is not None:
            linear = residual(linear)
        return encode(out_curve, np.clip(linear, 0.0, None))

    return transform
