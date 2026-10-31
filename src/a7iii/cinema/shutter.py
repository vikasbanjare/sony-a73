"""Shutter-angle lock and anti-flicker engine (roadmap section 10.3, module A).

The a7 III has no variable/clear-scan shutter: only the discrete 1/3-stop
speeds below are available. That matters for flicker - e.g. under 60 Hz
mains the ideal 1/120 s does not exist, so we must fall back to 1/60 s.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from fractions import Fraction

# ILCE-7M3 shutter speeds (seconds), fastest to slowest.
_FAST = [8000, 6400, 5000, 4000, 3200, 2500, 2000, 1600, 1250, 1000, 800, 640, 500, 400, 320,
         250, 200, 160, 125, 100, 80, 60, 50, 40, 30, 25, 20, 15, 13, 10, 8, 6, 5, 4, 3]
_SLOW = ["0.4", "0.5", "0.6", "0.8", "1", "1.3", "1.6", "2", "2.5", "3.2", "4", "5", "6", "8",
         "10", "13", "15", "20", "25", "30"]
SHUTTER_SPEEDS: list[Fraction] = [Fraction(1, d) for d in _FAST] + [Fraction(s) for s in _SLOW]

FLICKER_TOLERANCE = 0.02  # fraction of a flicker period still considered "clean"


def format_speed(t: Fraction) -> str:
    if t < 1 and t.numerator == 1:
        return f"1/{t.denominator}"
    return f'{float(t):g}"'


def sony_ptp_shutter_value(t: Fraction) -> int:
    """Encode for Sony property 0xD20D: (numerator << 16) | denominator.

    Slow speeds such as 1.3" are encoded with a denominator of 10 (13/10).
    """
    if t < 1 and t.numerator == 1:
        num, den = 1, t.denominator
    else:
        num, den = round(float(t) * 10), 10
        if num % 10 == 0:
            num, den = num // 10, 1
    return (num << 16) | den


def shutter_angle(t: float, fps: float) -> float:
    return 360.0 * t * fps


def ideal_exposure(fps: float, angle: float) -> float:
    if not 0.0 < angle <= 360.0:
        raise ValueError("shutter angle must be in (0, 360]")
    if fps <= 0:
        raise ValueError("fps must be positive")
    return angle / (360.0 * fps)


def is_flicker_free(t: float, mains_hz: float) -> bool:
    """Light from AC mains flickers at 2x mains; exposure must span whole periods."""
    periods = t * 2.0 * mains_hz
    return periods >= 1.0 - FLICKER_TOLERANCE and abs(periods - round(periods)) <= FLICKER_TOLERANCE


@dataclass
class ShutterSolution:
    fps: float
    target_angle: float
    ideal_seconds: float
    speed: Fraction
    effective_angle: float
    flicker_free: bool | None
    warnings: list[str] = field(default_factory=list)

    @property
    def label(self) -> str:
        return format_speed(self.speed)

    @property
    def ptp_value(self) -> int:
        return sony_ptp_shutter_value(self.speed)


def solve_shutter(fps: float, angle: float = 180.0, mains_hz: float | None = None, movie: bool = True) -> ShutterSolution:
    """Choose the a7 III shutter speed closest (in stops) to the requested angle.

    With ``mains_hz`` set, only flicker-free speeds are considered. In movie
    mode, speeds slower than one frame interval are excluded.
    """
    t_ideal = ideal_exposure(fps, angle)
    candidates = list(SHUTTER_SPEEDS)
    warnings: list[str] = []
    if movie:
        candidates = [t for t in candidates if float(t) <= 1.0 / fps * (1 + 1e-9)]
    if mains_hz:
        clean = [t for t in candidates if is_flicker_free(float(t), mains_hz)]
        if clean:
            candidates = clean
        else:
            warnings.append(f"no flicker-free speed available at {fps} fps under {mains_hz} Hz lighting")

    best = min(candidates, key=lambda t: abs(math.log2(float(t) / t_ideal)))
    eff = shutter_angle(float(best), fps)
    stops_off = math.log2(float(best) / t_ideal)
    if abs(stops_off) > 1 / 6:
        warnings.append(f"closest speed is {stops_off:+.2f} stops from the requested {angle:g} deg")
    return ShutterSolution(
        fps=fps,
        target_angle=angle,
        ideal_seconds=t_ideal,
        speed=best,
        effective_angle=eff,
        flicker_free=is_flicker_free(float(best), mains_hz) if mains_hz else None,
        warnings=warnings,
    )
