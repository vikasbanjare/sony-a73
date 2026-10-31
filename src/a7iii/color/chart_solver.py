"""Chart-based camera matching (roadmap section 4.3, stage 1).

Solves a 3x3 (or root-polynomial 3xK) matrix mapping scene-linear chart
patches from the a7 III onto a reference camera (e.g. FX3), minimising the
weighted CIEDE2000 error. Patch extraction from images is out of scope here;
feed in mean linear RGB per patch.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .colorimetry import delta_e_2000, linear_rgb_to_lab

# ColorChecker Classic patch order: index 0 = Dark Skin, 1 = Light Skin, 11 = Orange Yellow.
SKIN_PATCHES = (0, 1, 11)


def root_polynomial_features(rgb: np.ndarray, degree: int = 1) -> np.ndarray:
    """Root-polynomial expansion (Finlayson et al. 2015). Exposure invariant.

    degree=1 -> [r, g, b]
    degree=2 -> adds sqrt(rg), sqrt(gb), sqrt(rb)
    """
    rgb = np.clip(np.asarray(rgb, dtype=np.float64), 0.0, None)
    r, g, b = rgb[..., 0], rgb[..., 1], rgb[..., 2]
    feats = [r, g, b]
    if degree >= 2:
        feats += [np.sqrt(r * g), np.sqrt(g * b), np.sqrt(r * b)]
    if degree >= 3:
        feats += [
            np.cbrt(r * g * g), np.cbrt(r * b * b), np.cbrt(g * r * r),
            np.cbrt(g * b * b), np.cbrt(b * r * r), np.cbrt(b * g * g),
            np.cbrt(r * g * b),
        ]
    return np.stack(feats, axis=-1)


@dataclass
class MatchResult:
    matrix: np.ndarray  # shape (3, K)
    degree: int
    delta_e: np.ndarray  # per patch

    @property
    def mean_delta_e(self) -> float:
        return float(np.mean(self.delta_e))

    def apply(self, rgb: np.ndarray) -> np.ndarray:
        return root_polynomial_features(rgb, self.degree) @ self.matrix.T


def default_weights(n_patches: int, skin_weight: float = 2.5) -> np.ndarray:
    w = np.ones(n_patches)
    for i in SKIN_PATCHES:
        if i < n_patches:
            w[i] = skin_weight
    return w


def solve_ccm(
    source_rgb: np.ndarray,
    target_rgb: np.ndarray,
    weights: np.ndarray | None = None,
    degree: int = 1,
    refine: bool = True,
) -> MatchResult:
    """Fit target ~= M @ features(source).

    A weighted least-squares fit in linear RGB seeds the solution; if scipy is
    available and ``refine`` is set it is then refined to minimise weighted
    CIEDE2000 directly.
    """
    source_rgb = np.asarray(source_rgb, dtype=np.float64)
    target_rgb = np.asarray(target_rgb, dtype=np.float64)
    if source_rgb.shape != target_rgb.shape or source_rgb.shape[-1] != 3:
        raise ValueError("source and target must both be (N, 3)")
    n = source_rgb.shape[0]
    w = default_weights(n) if weights is None else np.asarray(weights, dtype=np.float64)

    X = root_polynomial_features(source_rgb, degree)
    sw = np.sqrt(w)[:, None]
    M, *_ = np.linalg.lstsq(X * sw, target_rgb * sw, rcond=None)
    M = M.T  # (3, K)

    target_lab = linear_rgb_to_lab(target_rgb)

    def errors(m_flat: np.ndarray) -> np.ndarray:
        pred = X @ m_flat.reshape(M.shape).T
        return delta_e_2000(linear_rgb_to_lab(np.clip(pred, 0.0, None)), target_lab)

    if refine:
        try:
            from scipy.optimize import minimize
        except ImportError:
            pass
        else:
            res = minimize(lambda m: float(np.sum(w * errors(m))), M.ravel(), method="Powell",
                           options={"maxiter": 20000, "xtol": 1e-8, "ftol": 1e-10})
            if res.fun <= float(np.sum(w * errors(M.ravel()))):
                M = res.x.reshape(M.shape)

    return MatchResult(matrix=M, degree=degree, delta_e=errors(M.ravel()))
