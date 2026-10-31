"""Stand-in for YOLO-pose: turns the renderer's ground truth into detections.

Adds pixel jitter, confidence noise and random misses so the AF tracker is
exercised the way a real network would exercise it.
"""

from __future__ import annotations

import numpy as np

from ..af.types import L_EYE, L_HIP, L_SHOULDER, NOSE, R_EYE, R_HIP, R_SHOULDER, Detection
from .camera import Frame


class GroundTruthDetector:
    def __init__(self, jitter: float = 0.004, miss_rate: float = 0.05, seed: int = 0, track_id: int = 1):
        self.rng = np.random.default_rng(seed)
        self.jitter = jitter
        self.miss_rate = miss_rate
        self.track_id = track_id

    def detect_frame(self, frame: Frame) -> list[Detection]:
        kp = frame.keypoints
        if kp is None or self.rng.random() < self.miss_rate:
            return []
        j = lambda p: (p[0] + self.rng.normal(0, self.jitter), p[1] + self.rng.normal(0, self.jitter))  # noqa: E731
        k = np.zeros((17, 3))
        k[L_EYE] = (*j(kp["l_eye"]), 0.9)
        k[R_EYE] = (*j(kp["r_eye"]), 0.7)
        k[NOSE] = (*j(kp["nose"]), 0.9)
        hx, hy = kp["head"]
        tx, ty = kp["torso"]
        for idx, dx in ((L_SHOULDER, -0.05), (R_SHOULDER, 0.05)):
            k[idx] = (hx + dx, (hy + ty) / 2, 0.8)
        for idx, dx in ((L_HIP, -0.03), (R_HIP, 0.03)):
            k[idx] = (tx + dx, min(ty + 0.1, 1.0), 0.6)
        if not (0 <= hx <= 1 and 0 <= hy <= 1):
            return []
        bbox = (hx - 0.08, hy - 0.08, hx + 0.08, 1.0)
        return [Detection(bbox, 0.9, "person", self.track_id, k)]

    def detect(self, frame) -> list[Detection]:  # Detector protocol (frame is a sim Frame)
        return self.detect_frame(frame)
