"""Noise / astro stacking (roadmap §8.2): SNR grows ~ sqrt(N)."""

from __future__ import annotations

import numpy as np

from .align import align_to


def stack(frames: list[np.ndarray], method: str = "sigma_clip", align: bool = True, kappa: float = 2.5) -> np.ndarray:
    imgs = [np.asarray(f, dtype=np.float64) for f in frames]
    if align and len(imgs) > 1:
        imgs, _ = align_to(imgs[0], imgs)
    cube = np.stack(imgs)
    if method == "mean":
        return cube.mean(axis=0)
    if method == "median":
        return np.median(cube, axis=0)
    if method == "sigma_clip":
        # Reject outliers (satellites, hot pixels, planes) per pixel, then average.
        med = np.median(cube, axis=0)
        mad = np.median(np.abs(cube - med), axis=0) * 1.4826 + 1e-12
        keep = np.abs(cube - med) <= kappa * mad
        return np.where(keep, cube, 0).sum(axis=0) / np.maximum(keep.sum(axis=0), 1)
    raise ValueError(f"unknown method {method!r}")


def snr(region: np.ndarray) -> float:
    r = np.asarray(region, dtype=np.float64)
    return float(r.mean() / (r.std() + 1e-12))


def dynamic_range_gain_ev(n_frames: int) -> float:
    """Shadow DR gained by averaging N frames (read/shot noise drops by sqrt(N))."""
    return 0.5 * np.log2(n_frames)
