"""Anamorphic de-squeeze and multi-aspect framing guides (roadmap §7)."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

SQUEEZE_FACTORS = (1.33, 1.5, 1.6, 1.8, 2.0)


def desqueeze(frame: np.ndarray, factor: float, keep_height: bool = True) -> np.ndarray:
    """Stretch horizontally by ``factor`` (linear interpolation).

    keep_height=True widens the image (W * factor); False keeps the width and
    squashes vertically instead, which is cheaper for monitoring.
    """
    if factor <= 0:
        raise ValueError("squeeze factor must be positive")
    f = np.asarray(frame, dtype=np.float64)
    H, W = f.shape[:2]
    if keep_height:
        new_w = int(round(W * factor))
        xs = np.linspace(0, W - 1, new_w)
        x0 = np.floor(xs).astype(int)
        x1 = np.minimum(x0 + 1, W - 1)
        t = (xs - x0)[None, :, None] if f.ndim == 3 else (xs - x0)[None, :]
        return f[:, x0] * (1 - t) + f[:, x1] * t
    new_h = int(round(H / factor))
    ys = np.linspace(0, H - 1, new_h)
    y0 = np.floor(ys).astype(int)
    y1 = np.minimum(y0 + 1, H - 1)
    t = (ys - y0)[:, None, None] if f.ndim == 3 else (ys - y0)[:, None]
    return f[y0] * (1 - t) + f[y1] * t


@dataclass(frozen=True)
class Guide:
    name: str
    x0: int
    y0: int
    x1: int
    y1: int


def aspect_guide(width: int, height: int, aspect: float, name: str | None = None, safe: float = 1.0) -> Guide:
    """Largest centred rectangle of ``aspect`` (w/h) inside the frame, optionally scaled by ``safe``."""
    if width / height > aspect:
        h = height
        w = height * aspect
    else:
        w = width
        h = width / aspect
    w, h = w * safe, h * safe
    x0 = int(round((width - w) / 2))
    y0 = int(round((height - h) / 2))
    return Guide(name or f"{aspect:.2f}:1", x0, y0, x0 + int(round(w)), y0 + int(round(h)))


def standard_guides(width: int, height: int) -> list[Guide]:
    return [
        aspect_guide(width, height, 2.39, "2.39:1 scope"),
        aspect_guide(width, height, 1.85, "1.85:1 flat"),
        aspect_guide(width, height, 9 / 16, "9:16 vertical"),
        aspect_guide(width, height, 4 / 5, "4:5 feed"),
        aspect_guide(width, height, width / height, "action safe 93%", safe=0.93),
        aspect_guide(width, height, width / height, "title safe 90%", safe=0.90),
    ]


def draw_guides(frame: np.ndarray, guides: list[Guide], dim_outside: Guide | None = None,
                color=(1.0, 1.0, 1.0), dim: float = 0.35) -> np.ndarray:
    out = np.array(frame, dtype=np.float64, copy=True)
    if dim_outside is not None:
        mask = np.ones(out.shape[:2], bool)
        mask[dim_outside.y0:dim_outside.y1, dim_outside.x0:dim_outside.x1] = False
        out[mask] *= dim
    H, W = out.shape[:2]
    for g in guides:
        x0, x1 = max(0, g.x0), min(W - 1, g.x1 - 1)
        y0, y1 = max(0, g.y0), min(H - 1, g.y1 - 1)
        out[y0, x0:x1 + 1] = color
        out[y1, x0:x1 + 1] = color
        out[y0:y1 + 1, x0] = color
        out[y0:y1 + 1, x1] = color
    return out
