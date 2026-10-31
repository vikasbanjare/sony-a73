"""Map points from the capture frame to the camera's sensor-image space.

The HDMI/live-view frame may contain the camera image letterboxed or
pillarboxed (e.g. a 3:2 stills live view inside a 16:9 HDMI signal), so a
point found by the detector must be re-normalised to the active image area
before it is sent to the camera as an AF position.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class FrameGeometry:
    capture_w: int
    capture_h: int
    active_x: int = 0
    active_y: int = 0
    active_w: int | None = None
    active_h: int | None = None

    @classmethod
    def fit(cls, capture_w: int, capture_h: int, image_aspect: float) -> "FrameGeometry":
        """Image of ``image_aspect`` centred in the capture frame with bars."""
        cap_aspect = capture_w / capture_h
        if image_aspect >= cap_aspect:
            w, h = capture_w, round(capture_w / image_aspect)
        else:
            w, h = round(capture_h * image_aspect), capture_h
        return cls(capture_w, capture_h, (capture_w - w) // 2, (capture_h - h) // 2, w, h)

    @property
    def _aw(self) -> int:
        return self.active_w or self.capture_w

    @property
    def _ah(self) -> int:
        return self.active_h or self.capture_h

    def to_image(self, x: float, y: float) -> tuple[float, float] | None:
        """Capture-normalised -> image-normalised. None if the point is on a bar."""
        px, py = x * self.capture_w, y * self.capture_h
        u = (px - self.active_x) / self._aw
        v = (py - self.active_y) / self._ah
        if not (0.0 <= u <= 1.0 and 0.0 <= v <= 1.0):
            return None
        return u, v
