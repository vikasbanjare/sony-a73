"""Detector-agnostic detection types. Coordinates are normalised to [0, 1]."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

import numpy as np

# COCO-17 keypoint indices (YOLO-pose, RTMPose, etc.)
NOSE, L_EYE, R_EYE, L_EAR, R_EAR, L_SHOULDER, R_SHOULDER = 0, 1, 2, 3, 4, 5, 6
L_HIP, R_HIP = 11, 12


@dataclass
class Detection:
    bbox: tuple[float, float, float, float]  # x0, y0, x1, y1 (normalised)
    score: float
    label: str = "person"
    track_id: int | None = None
    keypoints: np.ndarray | None = None  # (17, 3): x, y, confidence

    @property
    def center(self) -> tuple[float, float]:
        x0, y0, x1, y1 = self.bbox
        return ((x0 + x1) / 2, (y0 + y1) / 2)

    @property
    def area(self) -> float:
        x0, y0, x1, y1 = self.bbox
        return max(0.0, x1 - x0) * max(0.0, y1 - y0)


@dataclass
class FocusPoint:
    x: float
    y: float
    part: str  # "eye", "head", "torso", "box"
    track_id: int | None = None
    meta: dict = field(default_factory=dict)


class Detector(Protocol):
    def detect(self, frame: np.ndarray) -> list[Detection]: ...
