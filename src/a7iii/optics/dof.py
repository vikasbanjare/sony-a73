"""Depth of field, hyperfocal distance and focus-bracketing plans.

All distances are in millimetres, measured from the sensor plane (as lens
distance scales are). The thin-lens approximations used here are the
standard ones and are accurate except at macro magnifications.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

# Full-frame circle of confusion. 0.030 mm is the print convention; 0.019 mm
# is closer to 1-pixel-ish scrutiny at 4K on a 24 MP sensor (roadmap §7).
COC_FULL_FRAME_MM = 0.030
COC_CRITICAL_MM = 0.019


def hyperfocal(focal_mm: float, f_number: float, coc_mm: float = COC_FULL_FRAME_MM) -> float:
    return focal_mm**2 / (f_number * coc_mm) + focal_mm


@dataclass(frozen=True)
class DepthOfField:
    near: float
    far: float  # math.inf beyond hyperfocal

    @property
    def total(self) -> float:
        return self.far - self.near


def depth_of_field(focal_mm: float, f_number: float, distance_mm: float, coc_mm: float = COC_FULL_FRAME_MM) -> DepthOfField:
    if distance_mm <= focal_mm:
        raise ValueError("focus distance must exceed focal length")
    H = hyperfocal(focal_mm, f_number, coc_mm)
    near = distance_mm * (H - focal_mm) / (H + distance_mm - 2 * focal_mm)
    far = math.inf if distance_mm >= H else distance_mm * (H - focal_mm) / (H - distance_mm)
    return DepthOfField(near, far)


def _distance_with_near_limit(near_mm: float, focal_mm: float, H: float) -> float:
    """Invert the near-limit formula: focus distance whose DoF starts at near_mm."""
    denom = H - focal_mm - near_mm
    if denom <= 0:
        return math.inf
    return near_mm * (H - 2 * focal_mm) / denom


def focus_bracket_plan(
    focal_mm: float,
    f_number: float,
    near_mm: float,
    far_mm: float,
    coc_mm: float = COC_CRITICAL_MM,
    overlap: float = 0.1,
    max_shots: int = 500,
) -> list[float]:
    """Focus distances for a stack covering [near_mm, far_mm].

    Each shot's near DoF limit sits at the previous shot's far limit, pulled
    back by ``overlap`` (fraction of that shot's depth) so slices overlap.
    Steps therefore grow roughly with distance squared, which is the
    behaviour the roadmap's  Δd ∝ N·c·d²/f²  heuristic approximates.
    """
    if not 0 <= overlap < 1:
        raise ValueError("overlap must be in [0, 1)")
    if near_mm >= far_mm:
        raise ValueError("near must be closer than far")
    H = hyperfocal(focal_mm, f_number, coc_mm)
    plan: list[float] = []
    next_near = near_mm
    while len(plan) < max_shots:
        d = _distance_with_near_limit(next_near, focal_mm, H)
        if math.isinf(d) or d >= H:
            plan.append(H)  # hyperfocal covers everything to infinity
            break
        plan.append(d)
        dof = depth_of_field(focal_mm, f_number, d, coc_mm)
        if dof.far >= far_mm:
            break
        next_near = dof.far - overlap * dof.total
    else:
        raise ValueError(f"stack would need more than {max_shots} shots; stop down or reduce range")
    return plan
