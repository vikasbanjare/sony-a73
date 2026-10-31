"""Sub-pixel image registration by phase correlation.

Integer peak from the normalised cross-power spectrum, then refined with
a locally upsampled DFT around the peak (Guizar-Sicairos et al., 2008),
giving ~1/upsample-pixel precision without upsampling the whole image.
"""

from __future__ import annotations

import numpy as np


def _gray(img: np.ndarray) -> np.ndarray:
    img = np.asarray(img, dtype=np.float64)
    return img.mean(axis=-1) if img.ndim == 3 else img


def _upsampled_dft(data: np.ndarray, region: int, factor: int, offsets: np.ndarray) -> np.ndarray:
    """DFT of ``data`` evaluated on a ``region``-sized patch of a ``factor``-times finer grid."""
    out = data
    for n_items, offset in zip(data.shape[::-1], offsets[::-1]):
        kernel = (np.arange(region) - offset)[:, None] * np.fft.fftfreq(n_items, factor)
        out = np.tensordot(np.exp(-2j * np.pi * kernel), out, axes=(1, -1))
    return out


def phase_correlation(ref: np.ndarray, img: np.ndarray, upsample: int = 20, window: bool = True) -> tuple[float, float]:
    """Shift (dy, dx) such that ``img(y, x) ~= ref(y - dy, x - dx)``."""
    a, b = _gray(ref), _gray(img)
    if a.shape != b.shape:
        raise ValueError("images must have the same shape")
    if window:
        win = np.outer(np.hanning(a.shape[0]), np.hanning(a.shape[1]))
        a, b = (a - a.mean()) * win, (b - b.mean()) * win
    A, B = np.fft.fft2(a), np.fft.fft2(b)
    product = A * np.conj(B)
    product /= np.abs(product) + 1e-12
    corr = np.fft.ifft2(product)
    peak = np.array(np.unravel_index(np.argmax(np.abs(corr)), corr.shape), dtype=np.float64)
    shape = np.array(corr.shape)
    peak[peak > shape // 2] -= shape[peak > shape // 2]

    if upsample > 1:
        peak = np.round(peak * upsample) / upsample
        region = int(np.ceil(upsample * 1.5))
        center = np.trunc(region / 2.0)
        offsets = center - peak * upsample
        up = _upsampled_dft(product.conj(), region, upsample, offsets).conj()
        m = np.array(np.unravel_index(np.argmax(np.abs(up)), up.shape), dtype=np.float64)
        peak = peak + (m - center) / upsample
    # ``peak`` registers img onto ref; img = ref shifted by -peak.
    return float(-peak[0]), float(-peak[1])


def shift_image(img: np.ndarray, dy: float, dx: float) -> np.ndarray:
    """Translate by (dy, dx) with bilinear sampling (edges clamp)."""
    from scipy.ndimage import shift

    img = np.asarray(img, dtype=np.float64)
    s = (dy, dx, 0) if img.ndim == 3 else (dy, dx)
    return shift(img, s, order=1, mode="nearest")


def align_to(ref: np.ndarray, frames: list[np.ndarray]) -> tuple[list[np.ndarray], list[tuple[float, float]]]:
    shifts = [phase_correlation(ref, f) for f in frames]
    return [shift_image(f, -dy, -dx) for f, (dy, dx) in zip(frames, shifts)], shifts
