"""PDAF aperture guard (roadmap section 5.3, mode C; risk RSK-04).

In movie mode the a7 III falls back from phase detection to contrast
detection when stopped down past roughly f/11, which shows up as hunting.
"""

from __future__ import annotations

from dataclasses import dataclass

PDAF_MOVIE_MAX_F_NUMBER = 11.0


@dataclass(frozen=True)
class AFGuardStatus:
    ok: bool
    message: str


def check_aperture(f_number: float, movie_mode: bool, af_enabled: bool = True) -> AFGuardStatus:
    if f_number <= 0:
        raise ValueError("f-number must be positive")
    if movie_mode and af_enabled and f_number > PDAF_MOVIE_MAX_F_NUMBER + 1e-6:
        return AFGuardStatus(False, f"PDAF DISABLED (f/{f_number:g} > f/11) - add ND or switch to MF")
    return AFGuardStatus(True, "PDAF available")


def f_number_from_ptp(raw: int) -> float:
    """Decode PTP property 0x5007 (FNumber), which is stored as f-number x 100."""
    return raw / 100.0
