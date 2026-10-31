"""Time-bounded pre-capture ring buffer (roadmap section 7, "Pre-Capture").

Holds the last N seconds of frames from the HDMI capture; on trigger the
buffered frames are flushed to the recorder ahead of the live feed. Frame
payloads are opaque, so the same class works for raw frames or encoded
packets. Memory guide: 4K 4:2:2 8-bit is ~16.6 MB/frame, so 10 s at 24p is
~4 GB uncompressed - buffer encoded packets for longer windows.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from typing import Generic, Iterator, TypeVar

T = TypeVar("T")


@dataclass
class Frame(Generic[T]):
    timestamp: float
    payload: T
    size_bytes: int = 0


class PreRollBuffer(Generic[T]):
    def __init__(self, seconds: float, max_bytes: int | None = None):
        if seconds <= 0:
            raise ValueError("seconds must be positive")
        self.seconds = seconds
        self.max_bytes = max_bytes
        self._frames: deque[Frame[T]] = deque()
        self._bytes = 0

    def push(self, timestamp: float, payload: T, size_bytes: int = 0) -> None:
        if self._frames and timestamp < self._frames[-1].timestamp:
            raise ValueError("timestamps must be non-decreasing")
        self._frames.append(Frame(timestamp, payload, size_bytes))
        self._bytes += size_bytes
        self._evict(timestamp)

    def _evict(self, now: float) -> None:
        while self._frames and now - self._frames[0].timestamp > self.seconds:
            self._bytes -= self._frames.popleft().size_bytes
        while self.max_bytes is not None and self._bytes > self.max_bytes and len(self._frames) > 1:
            self._bytes -= self._frames.popleft().size_bytes

    def flush(self) -> list[Frame[T]]:
        """Return buffered frames oldest-first and empty the buffer."""
        frames = list(self._frames)
        self._frames.clear()
        self._bytes = 0
        return frames

    @property
    def duration(self) -> float:
        if len(self._frames) < 2:
            return 0.0
        return self._frames[-1].timestamp - self._frames[0].timestamp

    @property
    def nbytes(self) -> int:
        return self._bytes

    def __len__(self) -> int:
        return len(self._frames)

    def __iter__(self) -> Iterator[Frame[T]]:
        return iter(self._frames)
