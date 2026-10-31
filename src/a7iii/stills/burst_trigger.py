"""Motion-triggered capture with pre-roll (roadmap §8.3).

Watches a region of interest on the live feed; when the mean absolute
frame difference inside it crosses a threshold (after a noise-adaptive
baseline), it fires. With a ``PreRollBuffer`` the frames from *before*
the trigger are kept too, which is how a pre-capture burst works.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

import numpy as np

from ..cinema.ring_buffer import Frame, PreRollBuffer


@dataclass
class MotionTrigger:
    roi: tuple[float, float, float, float]  # x0, y0, x1, y1 normalised
    sensitivity: float = 6.0  # threshold in multiples of the running noise level
    min_level: float = 0.01  # absolute floor on the diff level
    cooldown_s: float = 1.0
    on_fire: Callable[[float, float], None] | None = None
    background_rate: float = 0.05  # how fast the background model absorbs slow changes
    _bg: np.ndarray | None = None
    _noise: float | None = None
    _last_fire: float = -np.inf
    fires: list[float] = field(default_factory=list)

    def _crop(self, frame: np.ndarray) -> np.ndarray:
        H, W = frame.shape[:2]
        x0, y0, x1, y1 = self.roi
        c = np.asarray(frame[int(y0 * H): int(y1 * H), int(x0 * W): int(x1 * W)], dtype=np.float64)
        return c.mean(axis=-1) if c.ndim == 3 else c

    def update(self, t: float, frame: np.ndarray) -> bool:
        """Compare the ROI with a running background model, not just the last frame.

        Frame differencing only sees moving edges. A background model also sees
        something that arrives and then stays still (a bird landing, a runner
        entering the zone), which is what a pre-capture trigger is for.
        """
        roi = self._crop(frame)
        fired = False
        if self._bg is None:
            self._bg = roi.copy()
            return False
        level = float(np.mean(np.abs(roi - self._bg)))
        if self._noise is None:
            self._noise = max(level, 1e-6)
        threshold = max(self.min_level, self.sensitivity * self._noise)
        if level > threshold:
            if t - self._last_fire >= self.cooldown_s:
                fired = True
                self._last_fire = t
                self.fires.append(t)
                if self.on_fire:
                    self.on_fire(t, level)
        else:
            # Only learn while nothing is happening, so a subject isn't absorbed into the background.
            self._noise = 0.95 * self._noise + 0.05 * max(level, 1e-6)
            self._bg = (1 - self.background_rate) * self._bg + self.background_rate * roi
        return fired


class PreCaptureBurst:
    """Keeps ``pre_s`` seconds of frames; on trigger returns them plus ``post_s`` after."""

    def __init__(self, trigger: MotionTrigger, pre_s: float = 1.0, post_s: float = 0.5):
        self.trigger = trigger
        self.buffer: PreRollBuffer = PreRollBuffer(pre_s)
        self.post_s = post_s
        self._collecting: list[Frame] | None = None
        self._until = 0.0
        self.bursts: list[list[Frame]] = []

    def feed(self, t: float, frame: np.ndarray) -> None:
        if self._collecting is not None:
            self._collecting.append(Frame(t, frame))
            if t >= self._until:
                self.bursts.append(self._collecting)
                self._collecting = None
            return
        self.buffer.push(t, frame)
        if self.trigger.update(t, frame):
            self._collecting = self.buffer.flush()
            self._until = t + self.post_s
