"""External subject-recognition AF bridge (roadmap §5, packages/03)."""

from .controller import AFConfig, AFController, AFStep, UltralyticsPoseDetector
from .geometry import FrameGeometry
from .kalman import PointKalman
from .priority import choose_subject, focus_point
from .types import Detection, Detector, FocusPoint

__all__ = [
    "AFConfig",
    "AFController",
    "AFStep",
    "Detection",
    "Detector",
    "FocusPoint",
    "FrameGeometry",
    "PointKalman",
    "UltralyticsPoseDetector",
    "choose_subject",
    "focus_point",
]
