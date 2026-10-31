"""Stop-based false colour (roadmap section 10.3, module B).

Linearises the incoming signal with the active curve's inverse OETF and maps
each pixel's exposure relative to 18% grey onto a palette of half-stop-ish
bands, so the same colours mean the same stops regardless of picture profile.
"""

from __future__ import annotations

import numpy as np

from ..color.transfer import decode

REC709_LUMA = np.array([0.2126, 0.7152, 0.0722])

# (lower EV bound, RGB 0-255, label). Each band runs to the next bound.
ZONES: list[tuple[float, tuple[int, int, int], str]] = [
    (-np.inf, (40, 0, 80), "below -6: crushed"),
    (-6.0, (80, 0, 160), "-6 to -4: shadow floor"),
    (-4.0, (0, 60, 220), "-4 to -2: deep shadow"),
    (-2.0, (0, 150, 220), "-2 to -0.5: shadow"),
    (-0.5, (128, 128, 128), "-0.5 to +0.5: middle grey"),
    (0.5, (0, 190, 80), "+0.5 to +1.5: skin / key"),
    (1.5, (250, 200, 160), "+1.5 to +3: highlight"),
    (3.0, (250, 220, 0), "+3 to +5: bright highlight"),
    (5.0, (255, 120, 0), "+5 to +6: near clip"),
    (6.0, (255, 0, 0), "above +6: clipped"),
]
_BOUNDS = np.array([z[0] for z in ZONES[1:]])
_COLORS = np.array([z[1] for z in ZONES], dtype=np.uint8)


def exposure_stops(frame: np.ndarray, curve: str) -> np.ndarray:
    """(H, W, 3) signal in [0,1] -> (H, W) stops relative to 18% grey."""
    linear = decode(curve, np.asarray(frame, dtype=np.float64))
    y = np.clip(linear @ REC709_LUMA, 1e-6, None)
    return np.log2(y / 0.18)


def zone_index(stops: np.ndarray) -> np.ndarray:
    return np.searchsorted(_BOUNDS, stops, side="right")


def false_color(frame: np.ndarray, curve: str) -> np.ndarray:
    """Render a false-colour (H, W, 3) uint8 image."""
    return _COLORS[zone_index(exposure_stops(frame, curve))]


def zone_histogram(frame: np.ndarray, curve: str) -> dict[str, float]:
    """Fraction of pixels in each zone - handy for an exposure readout."""
    idx = zone_index(exposure_stops(frame, curve)).ravel()
    counts = np.bincount(idx, minlength=len(ZONES)) / max(idx.size, 1)
    return {ZONES[i][2]: float(c) for i, c in enumerate(counts)}
