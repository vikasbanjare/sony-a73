"""Focus stacking (roadmap §8.1).

Pipeline: undo focus breathing (per-frame scale), register translations,
measure local sharpness (smoothed Laplacian energy), then blend with
weights sharpened by an exponent so each pixel comes almost entirely from
its sharpest slice without hard seams.
"""

from __future__ import annotations

import numpy as np
from scipy.ndimage import gaussian_filter, laplace

from ..optics.breathing import scale_about_center
from .align import align_to


def sharpness(img: np.ndarray, sigma: float = 2.0) -> np.ndarray:
    g = np.asarray(img, dtype=np.float64)
    g = g.mean(axis=-1) if g.ndim == 3 else g
    return gaussian_filter(laplace(g) ** 2, sigma)


def prepare(frames: list[np.ndarray], scales: list[float] | None = None, align: bool = True) -> list[np.ndarray]:
    """Undo breathing (rescale to the largest magnification) and register translations."""
    imgs = [np.asarray(f, dtype=np.float64) for f in frames]
    if scales is not None:
        target = max(scales)
        imgs = [scale_about_center(f, target / s) if abs(target / s - 1) > 1e-6 else f for f, s in zip(imgs, scales)]
    if align and len(imgs) > 1:
        imgs, _ = align_to(imgs[len(imgs) // 2], imgs)
    return imgs


def focus_stack(
    frames: list[np.ndarray],
    scales: list[float] | None = None,
    align: bool = True,
    power: float = 4.0,
    sigma: float = 2.0,
) -> tuple[np.ndarray, np.ndarray]:
    """Merge a focus bracket. Returns (merged image, index map of the winning slice).

    ``scales``: relative magnification of each frame (e.g. from the lens
    breathing model); frames are rescaled to the largest magnification.
    """
    if not frames:
        raise ValueError("no frames")
    imgs = prepare(frames, scales, align)
    sharp = np.stack([sharpness(f, sigma) for f in imgs])
    norm = sharp / (sharp.max(axis=0, keepdims=True) + 1e-12)
    w = norm**power
    w /= w.sum(axis=0, keepdims=True) + 1e-12
    stack = np.stack(imgs)
    merged = np.einsum("nhw,nhw...->hw...", w, stack)
    return merged, np.argmax(sharp, axis=0)
