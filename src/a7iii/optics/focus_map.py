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
