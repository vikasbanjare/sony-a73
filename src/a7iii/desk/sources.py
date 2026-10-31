"""Video sources for the Control Desk.

All sources return ``(timestamp_s, frame)`` with ``frame`` an (H, W, 3)
float signal in [0, 1] - exactly what the camera put on HDMI/live view.

- ``SimSource``: frames from the virtual a7 III (advances simulated time)
- ``UVCSource``: an HDMI capture card via OpenCV (``pip install opencv-python``)
- ``PTPLiveViewSource``: JPEG live view over USB when no capture card is attached
"""

from __future__ import annotations

import io
import time
from typing import Protocol

import numpy as np


class VideoSource(Protocol):
    def read(self) -> tuple[float, np.ndarray]: ...
    def close(self) -> None: ...


class SimSource:
    def __init__(self, camera, realtime: bool = False):
        self.camera = camera
        self.realtime = realtime
        self._wall0 = time.monotonic()
        self.last = None

    def read(self) -> tuple[float, np.ndarray]:
        cam = self.camera
        if self.realtime:
            target = time.monotonic() - self._wall0
            if target > cam.t:
                cam.advance(target - cam.t)
        else:
            cam.advance(1.0 / cam.state.fps)
        self.last = cam.render()
        return cam.t, self.last.signal

    def close(self) -> None:
        pass


class UVCSource:  # pragma: no cover - needs a capture card
    def __init__(self, device: int | str = 0, width: int = 1920, height: int = 1080):
        import cv2

        self._cv2 = cv2
        self.cap = cv2.VideoCapture(device)
        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
        if not self.cap.isOpened():
            raise ConnectionError(f"cannot open capture device {device!r}")

    def read(self) -> tuple[float, np.ndarray]:
        ok, bgr = self.cap.read()
        if not ok:
            raise ConnectionError("capture device stopped delivering frames")
        rgb = bgr[..., ::-1].astype(np.float32) / 255.0
        return time.monotonic(), rgb

    def close(self) -> None:
        self.cap.release()


class PTPLiveViewSource:
    def __init__(self, driver):
        self.driver = driver

    def read(self) -> tuple[float, np.ndarray]:
        from PIL import Image

        from ..ptp.session import extract_jpeg

        jpeg = extract_jpeg(self.driver.liveview_frame())
        if jpeg is None:
            raise ConnectionError("live view returned no JPEG")
        img = np.asarray(Image.open(io.BytesIO(jpeg)).convert("RGB"), dtype=np.float32) / 255.0
        return time.monotonic(), img

    def close(self) -> None:
        pass


def encode_jpeg(frame: np.ndarray, quality: int = 85) -> bytes:
    from PIL import Image

    img = Image.fromarray(np.clip(np.asarray(frame) * 255.0 + 0.5, 0, 255).astype(np.uint8))
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=quality)
    return buf.getvalue()


def encode_png(img_u8: np.ndarray) -> bytes:
    from PIL import Image

    buf = io.BytesIO()
    Image.fromarray(np.asarray(img_u8, dtype=np.uint8)).save(buf, format="PNG")
    return buf.getvalue()
