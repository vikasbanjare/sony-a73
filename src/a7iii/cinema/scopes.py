"""Video scopes: luma waveform, RGB parade, vectorscope, histogram.

Inputs are (H, W, 3) signal frames in [0, 1] (whatever curve the camera
recorded). Outputs are float densities plus helpers that render them as
uint8 images for the Control Desk.
"""

from __future__ import annotations

import numpy as np

REC709_LUMA = np.array([0.2126, 0.7152, 0.0722])


def luma(frame: np.ndarray) -> np.ndarray:
    return np.asarray(frame, dtype=np.float64) @ REC709_LUMA


def waveform(channel: np.ndarray, levels: int = 256, columns: int | None = None) -> np.ndarray:
    """(levels, columns) histogram of values per image column (row 0 = top = 100%)."""
    ch = np.clip(np.asarray(channel, dtype=np.float64), 0.0, 1.0)
    H, W = ch.shape
    columns = columns or W
    col = (np.arange(W) * columns // W)[None, :].repeat(H, 0)
    lvl = np.round(ch * (levels - 1)).astype(int)
    out = np.zeros((levels, columns))
    np.add.at(out, (levels - 1 - lvl, col), 1.0)
    return out


def rgb_parade(frame: np.ndarray, levels: int = 256, columns: int | None = None) -> np.ndarray:
    """Three waveforms side by side: (levels, 3*columns, 3)."""
    cols = columns or frame.shape[1]
    out = np.zeros((levels, 3 * cols, 3))
    for i in range(3):
        out[:, i * cols:(i + 1) * cols, i] = waveform(frame[..., i], levels, cols)
    return out


def ycbcr709(frame: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    f = np.asarray(frame, dtype=np.float64)
    y = f @ REC709_LUMA
    cb = (f[..., 2] - y) / 1.8556
    cr = (f[..., 0] - y) / 1.5748
    return y, cb, cr


def vectorscope(frame: np.ndarray, size: int = 256, gain: float = 1.0) -> np.ndarray:
    """(size, size) density of Cb (x) / Cr (y, up) around the centre."""
    _, cb, cr = ycbcr709(frame)
    x = np.clip(((cb * gain) + 0.5) * (size - 1), 0, size - 1).astype(int).ravel()
    y = np.clip((0.5 - cr * gain) * (size - 1), 0, size - 1).astype(int).ravel()
    out = np.zeros((size, size))
    np.add.at(out, (y, x), 1.0)
    return out


def histogram(frame: np.ndarray, bins: int = 256) -> np.ndarray:
    """(3, bins) per-channel histogram."""
    f = np.clip(np.asarray(frame, dtype=np.float64), 0, 1)
    return np.stack([np.histogram(f[..., i], bins=bins, range=(0, 1))[0] for i in range(3)])


def skin_tone_line_angle_deg() -> float:
    """Angle of the conventional skin-tone (I) line on a vectorscope (~123 deg from +Cb)."""
    return 123.0


def to_image(density: np.ndarray, gamma: float = 0.5) -> np.ndarray:
    """Normalise a density map to uint8 for display (gamma lifts faint traces)."""
    d = np.asarray(density, dtype=np.float64)
    peak = d.max() or 1.0
    return (np.power(d / peak, gamma) * 255).astype(np.uint8)


def clipping_report(frame: np.ndarray, low: float = 2 / 255, high: float = 253 / 255) -> dict[str, float]:
    y = luma(frame)
    return {"crushed": float(np.mean(y <= low)), "clipped": float(np.mean(np.max(frame, axis=-1) >= high))}
