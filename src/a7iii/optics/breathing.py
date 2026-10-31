"""Focus-breathing compensation (roadmap section 6.2).

Model: magnification relative to infinity focus
    s(d) = 1 + k1 * u + k2 * u^2,  u = f / (d - f)
Coefficients are per lens and come from calibration (shoot a chart at
several focus distances and fit). To lock framing through a rack, every
frame is scaled up to match the tightest field of view in the used range.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class BreathingProfile:
    focal_mm: float
    k1: float
    k2: float = 0.0
    min_focus_mm: float = 0.0

    def magnification(self, distance_mm: float | np.ndarray) -> np.ndarray:
        d = np.asarray(distance_mm, dtype=np.float64)
        if np.any(d <= self.focal_mm):
            raise ValueError("focus distance must exceed focal length")
        u = self.focal_mm / (d - self.focal_mm)
        return 1.0 + self.k1 * u + self.k2 * u**2

    def compensation_scale(self, distance_mm, near_mm: float | None = None, far_mm: float = np.inf) -> np.ndarray:
        """Per-frame crop factor (>= 1) that equalises FOV across [near, far]."""
        near = near_mm if near_mm is not None else max(self.min_focus_mm, self.focal_mm * 1.01)
        far = min(far_mm, 1e9)
        # s(d) is monotonic in d, so the tightest FOV is at one end of the range.
        s_max = float(np.max(self.magnification(np.array([near, far]))))
        return s_max / self.magnification(distance_mm)


def fit_breathing(focal_mm: float, distances_mm: np.ndarray, magnifications: np.ndarray) -> BreathingProfile:
    """Least-squares fit of k1, k2 from measured relative magnifications."""
    d = np.asarray(distances_mm, dtype=np.float64)
    m = np.asarray(magnifications, dtype=np.float64)
    u = focal_mm / (d - focal_mm)
    A = np.stack([u, u**2], axis=-1)
    (k1, k2), *_ = np.linalg.lstsq(A, m - 1.0, rcond=None)
    return BreathingProfile(focal_mm=focal_mm, k1=float(k1), k2=float(k2), min_focus_mm=float(d.min()))
