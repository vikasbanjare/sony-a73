"""Closed-loop AF steering (roadmap §5.2-5.3).

frame -> detector -> subject choice -> focus point -> Kalman lookahead ->
geometry mapping -> rate-limited, dead-banded sink (camera).

The sink is any callable ``(u, v) -> None`` taking image-normalised
coordinates. The PTP sink is deliberately not wired up yet: the Touch-AF
property and its value encoding for ILCE-7M3 still have to be confirmed on
hardware (see docs/ROADMAP_REVIEW.md).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Callable

import numpy as np

from ..optics.af_guard import check_aperture
from .geometry import FrameGeometry
from .kalman import PointKalman
from .priority import choose_subject, focus_point
from .types import Detection, Detector, FocusPoint

Sink = Callable[[float, float], None]


@dataclass
class AFConfig:
    latency_s: float = 0.025  # capture + inference + USB; roadmap §5.3 lookahead
    max_rate_hz: float = 15.0  # don't flood PTP
    deadband: float = 0.01  # min move (fraction of frame) worth resending
    lost_after_s: float = 0.5  # drop the lock after this long without the subject
    labels: tuple[str, ...] | None = ("person",)


@dataclass
class AFStep:
    sent: tuple[float, float] | None
    point: FocusPoint | None
    status: str
    warnings: list[str] = field(default_factory=list)


class AFController:
    def __init__(self, sink: Sink, geometry: FrameGeometry, config: AFConfig | None = None, detector: Detector | None = None):
        self.sink = sink
        self.geometry = geometry
        self.cfg = config or AFConfig()
        self.detector = detector
        self.kf = PointKalman()
        self.locked_id: int | None = None
        self.last_seen: float | None = None
        self.last_sent: tuple[float, float] | None = None
        self.last_sent_t = -math.inf
        self.f_number: float | None = None
        self.movie_mode = True

    def lock(self, track_id: int | None) -> None:
        """Operator picks a subject (e.g. taps it in the UI). None = auto."""
        self.locked_id = track_id
        self.kf.reset()

    def set_lens_state(self, f_number: float, movie_mode: bool = True) -> None:
        self.f_number = f_number
        self.movie_mode = movie_mode

    def process_frame(self, t: float, frame: np.ndarray) -> AFStep:
        if self.detector is None:
            raise RuntimeError("no detector configured; call step() with detections instead")
        return self.step(t, self.detector.detect(frame))

    def step(self, t: float, detections: list[Detection]) -> AFStep:
        warnings: list[str] = []
        pdaf_ok = True
        if self.f_number is not None:
            guard = check_aperture(self.f_number, self.movie_mode)
            pdaf_ok = guard.ok
            if not guard.ok:
                warnings.append(guard.message)

        subject = choose_subject(detections, self.locked_id, self.cfg.labels)
        if subject is None:
            if self.last_seen is not None and t - self.last_seen > self.cfg.lost_after_s:
                self.kf.reset()
                self.last_seen = None
                if self.locked_id is not None:
                    warnings.append(f"lost subject #{self.locked_id}")
            return AFStep(None, None, "no subject", warnings)

        if subject.track_id is not None and self.locked_id is None:
            self.locked_id = subject.track_id
        point = focus_point(subject)
        self.kf.update(t, point.x, point.y)
        self.last_seen = t
        px, py = self.kf.predict(t + self.cfg.latency_s)

        mapped = self.geometry.to_image(px, py)
        if mapped is None:
            return AFStep(None, point, "outside image area", warnings)
        if not pdaf_ok:
            # Steering is pointless while the camera is on contrast AF; don't make it hunt more.
            return AFStep(None, point, "suppressed (PDAF unavailable)", warnings)
        if t - self.last_sent_t < 1.0 / self.cfg.max_rate_hz:
            return AFStep(None, point, "rate limited", warnings)
        if self.last_sent is not None and math.dist(mapped, self.last_sent) < self.cfg.deadband:
            return AFStep(None, point, "within deadband", warnings)

        self.sink(*mapped)
        self.last_sent, self.last_sent_t = mapped, t
        return AFStep(mapped, point, "sent", warnings)


class UltralyticsPoseDetector:
    """Adapter for ``ultralytics`` YOLO pose/detect models (optional dependency).

    Example: ``UltralyticsPoseDetector("yolo11n-pose.pt")``. Uses the
    built-in ByteTrack tracker so detections carry persistent track IDs.
    """

    def __init__(self, weights: str = "yolo11n-pose.pt", conf: float = 0.4):
        from ultralytics import YOLO  # pragma: no cover - optional heavy dependency

        self.model = YOLO(weights)
        self.conf = conf

    def detect(self, frame: np.ndarray) -> list[Detection]:  # pragma: no cover
        r = self.model.track(frame, persist=True, conf=self.conf, tracker="bytetrack.yaml", verbose=False)[0]
        h, w = r.orig_shape
        out: list[Detection] = []
        boxes = r.boxes
        kps = getattr(r, "keypoints", None)
        for i in range(len(boxes)):
            x0, y0, x1, y1 = boxes.xyxy[i].tolist()
            kp = None
            if kps is not None and kps.data is not None and len(kps.data) > i:
                kp = kps.data[i].cpu().numpy().astype(np.float64)
                kp[:, 0] /= w
                kp[:, 1] /= h
            tid = int(boxes.id[i]) if boxes.id is not None else None
            out.append(Detection((x0 / w, y0 / h, x1 / w, y1 / h), float(boxes.conf[i]),
                                 r.names[int(boxes.cls[i])], tid, kp))
        return out
