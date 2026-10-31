"""Cine EI (exposure index) mode (roadmap section 7).

The physical ISO stays locked at a native (LCG/HCG) value. Changing EI only
shifts the *monitoring* exposure, which nudges the operator to change light,
ND or aperture instead of adding sensor gain.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from ..color.profiles import native_isos
from ..color.transfer import decode, rec709_encode

MAX_OFFSET_EV = 2.0


@dataclass(frozen=True)
class CineEI:
    gamma: str
    base: str = "low"  # "low" (LCG) or "high" (HCG)

    @property
    def recording_iso(self) -> int:
        lcg, hcg = native_isos(self.gamma)
        if self.base not in ("low", "high"):
            raise ValueError("base must be 'low' or 'high'")
        return lcg if self.base == "low" else hcg

    def monitor_offset_ev(self, ei: float) -> float:
        """Exposure offset to apply in the monitoring LUT for a given EI.

        Rating higher than the recording ISO brightens the monitor, so the
        operator stops down and protects highlights (more shadow noise).
        """
        if ei <= 0:
            raise ValueError("EI must be positive")
        offset = math.log2(ei / self.recording_iso)
        if abs(offset) > MAX_OFFSET_EV + 1e-9:
            raise ValueError(f"EI {ei:g} is {offset:+.2f} EV from ISO {self.recording_iso}; limit is +/-{MAX_OFFSET_EV} EV")
        return offset

    def monitor_gain(self, ei: float) -> float:
        """Linear-light multiplier for the monitoring path."""
        return 2.0 ** self.monitor_offset_ev(ei)


def display_tonemap(x: np.ndarray, knee: float = 0.6) -> np.ndarray:
    """Scene-linear -> display-linear with a soft shoulder; linear (grey-preserving) below ``knee``."""
    x = np.clip(np.asarray(x, dtype=np.float64), 0.0, None)
    shoulder = knee + (1 - knee) * (1 - np.exp(-(x - knee) / (1 - knee)))
    return np.where(x <= knee, x, shoulder)


def monitor_transform(curve: str, offset_ev: float = 0.0):
    """Camera signal -> Rec.709 monitor signal with an EI exposure offset (for ``build_lut``)."""
    gain = 2.0**offset_ev

    def transform(signal: np.ndarray) -> np.ndarray:
        return rec709_encode(display_tonemap(decode(curve, signal) * gain))

    return transform


def monitor_lut(cine_ei: CineEI, ei: float, curve: str, size: int = 33) -> np.ndarray:
    """3D LUT (size**3, 3) for the monitoring path at the given EI."""
    from ..color.lut import build_lut

    return build_lut(monitor_transform(curve, cine_ei.monitor_offset_ev(ei)), size)
