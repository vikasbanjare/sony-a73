"""Eased rack-focus schedules (roadmap section 5.3, mode B).

The a7 III only exposes relative near/far focus steps over PTP (property
0xD2D1, step sizes 1/2/3) so a rack is executed as a timed series of step
commands. ``rack_schedule`` turns a total travel (in small-step units) and a
duration into per-tick step counts following a cubic Bezier ease.
"""

from __future__ import annotations

import numpy as np


def cubic_bezier_ease(x1: float, y1: float, x2: float, y2: float):
    """CSS-style cubic-bezier(x1, y1, x2, y2) easing function, P0=(0,0), P3=(1,1)."""
    if not (0 <= x1 <= 1 and 0 <= x2 <= 1):
        raise ValueError("x control points must be within [0, 1]")

    def coord(t, a, b):
        return 3 * (1 - t) ** 2 * t * a + 3 * (1 - t) * t**2 * b + t**3

    def ease(x: np.ndarray | float) -> np.ndarray:
        x = np.clip(np.asarray(x, dtype=np.float64), 0.0, 1.0)
        # Solve coord(t, x1, x2) = x for t by bisection (monotonic since x1, x2 in [0,1]).
        lo = np.zeros_like(x)
        hi = np.ones_like(x)
        for _ in range(50):
            mid = (lo + hi) / 2
            too_low = coord(mid, x1, x2) < x
            lo = np.where(too_low, mid, lo)
            hi = np.where(too_low, hi, mid)
        return coord((lo + hi) / 2, y1, y2)

    return ease


EASE_IN_OUT = cubic_bezier_ease(0.42, 0.0, 0.58, 1.0)


def rack_schedule(total_steps: int, duration_s: float, tick_hz: float = 30.0, ease=EASE_IN_OUT) -> list[int]:
    """Signed step count to send at each tick. Sum equals ``total_steps``."""
    if duration_s <= 0 or tick_hz <= 0:
        raise ValueError("duration and tick rate must be positive")
    n_ticks = max(1, round(duration_s * tick_hz))
    progress = ease(np.linspace(0.0, 1.0, n_ticks + 1))
    cumulative = np.round(progress * total_steps).astype(int)
    cumulative[-1] = total_steps
    return np.diff(cumulative).tolist()
