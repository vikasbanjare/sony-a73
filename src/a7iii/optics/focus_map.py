"""Focus map / depth-of-field visualiser (roadmap §7).

Needs a per-pixel depth estimate. On hardware that comes from a monocular
depth network on the HDMI feed (any model returning metric depth works);
in the simulator it's the renderer's depth buffer. Colours: cyan = in
front of the DoF, green = inside, orange = behind.
"""

from __future__ import annotations

import math

import numpy as np

from .dof import COC_CRITICAL_MM, depth_of_field

FRONT, IN_FOCUS, BEHIND = 0, 1, 2
COLORS = np.array([[0.0, 0.85, 1.0], [0.1, 1.0, 0.2], [1.0, 0.5, 0.0]])


def classify(depth_m: np.ndarray, focal_mm: float, f_number: float, focus_mm: float,
             coc_mm: float = COC_CRITICAL_MM) -> np.ndarray:
    d = np.asarray(depth_m, dtype=np.float64) * 1000.0
    if math.isinf(focus_mm):
        from .dof import hyperfocal

        near, far = hyperfocal(focal_mm, f_number, coc_mm) / 2, math.inf
    else:
        dof = depth_of_field(focal_mm, f_number, focus_mm, coc_mm)
        near, far = dof.near, dof.far
    out = np.full(d.shape, IN_FOCUS, dtype=np.uint8)
    out[d < near] = FRONT
    out[d > far] = BEHIND
    return out


def overlay(frame: np.ndarray, classes: np.ndarray, alpha: float = 0.45) -> np.ndarray:
    f = np.asarray(frame, dtype=np.float64)
    return (1 - alpha) * f + alpha * COLORS[classes]


def sharpness_map(frame: np.ndarray, block: int = 16, rel: float = 0.35, floor: float = 0.03) -> np.ndarray:
    """No-depth focus map for real hardware: True where a block has strong fine detail.

    Laplacian energy per ``block`` x ``block`` tile; a tile counts as sharp at
    ``rel`` of the frame's strongest tiles and at least ``floor`` in absolute
    terms, so a fully defocused frame shows nothing. ``floor`` comes from a real
    a7 III: in-focus detail ~0.06, defocused live view <=0.018 (1024 px wide).
    Can't tell front from behind - only sharp vs soft. ponytail: very high ISO
    noise can cross the floor; expose a slider if that bites.
    """
    y = np.asarray(frame, dtype=np.float64) @ np.array([0.2126, 0.7152, 0.0722])
    lap = np.zeros_like(y)
    lap[1:-1, 1:-1] = np.abs(4 * y[1:-1, 1:-1] - y[:-2, 1:-1] - y[2:, 1:-1] - y[1:-1, :-2] - y[1:-1, 2:])
    H, W = (y.shape[0] // block) * block, (y.shape[1] // block) * block
    energy = lap[:H, :W].reshape(H // block, block, W // block, block).mean(axis=(1, 3))
    top = np.percentile(energy, 99)
    sharp = energy >= max(rel * top, floor)
    full = np.zeros(y.shape, dtype=bool)
    full[:H, :W] = np.repeat(np.repeat(sharp, block, axis=0), block, axis=1)
    return full


def sharpness_overlay(frame: np.ndarray, sharp: np.ndarray, alpha: float = 0.5) -> np.ndarray:
    """Green over sharp tiles, the rest dimmed - same green as the depth map's 'in focus'."""
    f = np.asarray(frame, dtype=np.float64)
    out = f * 0.45
    out[sharp] = (1 - alpha) * f[sharp] + alpha * COLORS[IN_FOCUS]
    return out
