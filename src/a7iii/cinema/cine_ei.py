"""Cine EI (exposure index) mode (roadmap section 7).

The physical ISO stays locked at a native (LCG/HCG) value. Changing EI only
shifts the *monitoring* exposure, which nudges the operator to change light,
ND or aperture instead of adding sensor gain.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from ..color.profiles import native_isos

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
