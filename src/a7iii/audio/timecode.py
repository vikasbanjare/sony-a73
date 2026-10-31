"""SMPTE timecode arithmetic, including 29.97 drop-frame."""

from __future__ import annotations

import re
from dataclasses import dataclass

_TC = re.compile(r"^(\d{2}):(\d{2}):(\d{2})([:;])(\d{2})$")


@dataclass(frozen=True)
class Timecode:
    hours: int
    minutes: int
    seconds: int
    frames: int
    fps: int  # nominal integer rate: 24, 25, 30
    drop_frame: bool = False

    def __post_init__(self):
        if self.drop_frame and self.fps != 30:
            raise ValueError("drop-frame only exists for 30 (29.97) fps")
        if not (0 <= self.frames < self.fps and 0 <= self.seconds < 60 and 0 <= self.minutes < 60 and 0 <= self.hours < 24):
            raise ValueError(f"invalid timecode {self}")
        if self.drop_frame and self.seconds == 0 and self.frames < 2 and self.minutes % 10 != 0:
            raise ValueError(f"{self} does not exist in drop-frame")

    def __str__(self) -> str:
        sep = ";" if self.drop_frame else ":"
        return f"{self.hours:02d}:{self.minutes:02d}:{self.seconds:02d}{sep}{self.frames:02d}"

    @classmethod
    def parse(cls, text: str, fps: int) -> "Timecode":
        m = _TC.match(text.strip())
        if not m:
            raise ValueError(f"bad timecode {text!r}")
        h, mi, s, sep, f = m.groups()
        return cls(int(h), int(mi), int(s), int(f), fps, drop_frame=sep == ";")

    def to_frames(self) -> int:
        total_minutes = 60 * self.hours + self.minutes
        n = ((total_minutes * 60) + self.seconds) * self.fps + self.frames
        if self.drop_frame:
            n -= 2 * (total_minutes - total_minutes // 10)
        return n

    @classmethod
    def from_frames(cls, n: int, fps: int, drop_frame: bool = False) -> "Timecode":
        day = (24 * 3600 * fps) - (2 * (24 * 60 - 24 * 6) if drop_frame else 0)
        n %= day
        if drop_frame:
            per_10min = 10 * 60 * 30 - 18
            per_min = 60 * 30 - 2
            d, m = divmod(n, per_10min)
            if m > 2:
                n += 18 * d + 2 * ((m - 2) // per_min)
            else:
                n += 18 * d
        f = n % fps
        s = (n // fps) % 60
        mi = (n // (fps * 60)) % 60
        h = n // (fps * 3600)
        return cls(h, mi, s, f, fps, drop_frame)

    def __add__(self, frames: int) -> "Timecode":
        return Timecode.from_frames(self.to_frames() + frames, self.fps, self.drop_frame)

    def seconds_since_midnight(self, actual_fps: float | None = None) -> float:
        """Real time of this timecode; pass 29.97/23.976 for NTSC-rate material."""
        return self.to_frames() / (actual_fps or self.fps)
