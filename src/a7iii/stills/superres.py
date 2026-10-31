"""Handheld multi-frame super-resolution (roadmap §8.2).

Classic shift-and-add: register each frame to sub-pixel precision, splat
its samples onto a finer grid with a small Gaussian kernel, normalise by
accumulated weight, then lightly deconvolve. Natural hand tremor gives the
random sub-pixel offsets that make the extra resolution recoverable.

Physical honesty: the gain is bounded by the lens/OLPF MTF and the number
of distinct sub-pixel phases; expect ~1.5-2x linear resolution, not a
perfect 4x pixel count.
"""

from __future__ import annotations

import numpy as np
from scipy.ndimage import gaussian_filter

from .align import phase_correlation


def shift_and_add(
    frames: list[np.ndarray],
    factor: int = 2,
    shifts: list[tuple[float, float]] | None = None,
    kernel_sigma: float = 0.6,
    sharpen: float = 0.6,
) -> np.ndarray:
    if len(frames) < 2:
        raise ValueError("super-resolution needs at least two frames")
    imgs = [np.asarray(f, dtype=np.float64) for f in frames]
    H, W = imgs[0].shape[:2]
    if shifts is None:
        shifts = [phase_correlation(imgs[0], f) for f in imgs]
    Hh, Wh = H * factor, W * factor
    extra = imgs[0].shape[2:]
    acc = np.zeros((Hh, Wh) + extra)
    wsum = np.zeros((Hh, Wh))
    yy, xx = np.mgrid[0:H, 0:W].astype(np.float64)
    for img, (dy, dx) in zip(imgs, shifts):
        # sample (y, x) of this frame sees scene point (y - dy, x - dx) of the reference
        hy = (yy - dy + 0.5) * factor - 0.5
        hx = (xx - dx + 0.5) * factor - 0.5
        iy = np.round(hy).astype(int)
        ix = np.round(hx).astype(int)
        ok = (iy >= 0) & (iy < Hh) & (ix >= 0) & (ix < Wh)
        np.add.at(acc, (iy[ok], ix[ok]), img[ok])
        np.add.at(wsum, (iy[ok], ix[ok]), 1.0)
    sig = (kernel_sigma * factor, kernel_sigma * factor) + (0,) * len(extra)
    acc = gaussian_filter(acc, sig)
    wsum = gaussian_filter(wsum, kernel_sigma * factor)
    out = acc / (wsum.reshape(wsum.shape + (1,) * len(extra)) + 1e-12)
    if sharpen > 0:  # unsharp mask to undo the splat kernel
        out = out + sharpen * (out - gaussian_filter(out, sig))
    return out


def _forward(hr: np.ndarray, dy: float, dx: float, factor: int) -> np.ndarray:
    """Imaging model: shift by the frame's offset (hi-res px), then box-average to sensor pixels."""
    from scipy.ndimage import shift

    s = (dy * factor, dx * factor) + (0,) * (hr.ndim - 2)
    moved = shift(hr, s, order=1, mode="nearest")
    H, W = hr.shape[0] // factor, hr.shape[1] // factor
    return moved[: H * factor, : W * factor].reshape((H, factor, W, factor) + hr.shape[2:]).mean(axis=(1, 3))


def iterative_backprojection(
    frames: list[np.ndarray],
    factor: int = 2,
    shifts: list[tuple[float, float]] | None = None,
    iterations: int = 6,  # more iterations start amplifying noise (semi-convergence)
    step: float = 1.0,
) -> np.ndarray:
    """Irani-Peleg iterative back-projection.

    Starting from shift-and-add, repeatedly simulate every captured frame
    from the current hi-res estimate and push the residual back. This
    removes the sensor's pixel-box blur that plain shift-and-add leaves in.
    """
    from scipy.ndimage import shift as nd_shift

    imgs = [np.asarray(f, dtype=np.float64) for f in frames]
    if shifts is None:
        shifts = [phase_correlation(imgs[0], f) for f in imgs]
    est = shift_and_add(imgs, factor, shifts, sharpen=0.0)
    for _ in range(iterations):
        update = np.zeros_like(est)
        for img, (dy, dx) in zip(imgs, shifts):
            resid = img - _forward(est, dy, dx, factor)
            up = np.repeat(np.repeat(resid, factor, axis=0), factor, axis=1)
            s = (-dy * factor, -dx * factor) + (0,) * (est.ndim - 2)
            update += nd_shift(up, s, order=1, mode="nearest")
        est = est + step * update / len(imgs)
    return est


def bilinear_upsample(img: np.ndarray, factor: int = 2) -> np.ndarray:
    from scipy.ndimage import zoom

    img = np.asarray(img, dtype=np.float64)
    z = (factor, factor) + (1,) * (img.ndim - 2)
    return zoom(img, z, order=1, mode="nearest", grid_mode=True)
