"""Pick *where* on a subject to focus: eye -> head -> torso -> box."""

from __future__ import annotations

import numpy as np

from .types import (
    L_EAR,
    L_EYE,
    L_HIP,
    L_SHOULDER,
    NOSE,
    R_EAR,
    R_EYE,
    R_HIP,
    R_SHOULDER,
    Detection,
    FocusPoint,
)

KEYPOINT_MIN_CONF = 0.5


def _visible(kp: np.ndarray, idx) -> np.ndarray:
    pts = kp[list(idx)]
    return pts[pts[:, 2] >= KEYPOINT_MIN_CONF]


def focus_point(det: Detection) -> FocusPoint:
    """Best focus target on one detection.

    For eyes, the more confident eye wins. It's usually the one facing the
    camera, which is also the one a portrait should be sharp on.
    """
    kp = det.keypoints
    if kp is not None and len(kp) >= 13:
        eyes = _visible(kp, (L_EYE, R_EYE))
        if len(eyes):
            best = eyes[np.argmax(eyes[:, 2])]
            return FocusPoint(float(best[0]), float(best[1]), "eye", det.track_id)
        head = _visible(kp, (NOSE, L_EAR, R_EAR))
        if len(head):
            return FocusPoint(float(head[:, 0].mean()), float(head[:, 1].mean()), "head", det.track_id)
        torso = _visible(kp, (L_SHOULDER, R_SHOULDER, L_HIP, R_HIP))
        if len(torso) >= 2:
            return FocusPoint(float(torso[:, 0].mean()), float(torso[:, 1].mean()), "torso", det.track_id)
    x0, y0, x1, y1 = det.bbox
    # Upper third of a person box is roughly head/shoulders; centre for objects.
    y = y0 + (y1 - y0) / 3 if det.label == "person" else (y0 + y1) / 2
    return FocusPoint((x0 + x1) / 2, y, "box", det.track_id)


def choose_subject(
    detections: list[Detection],
    locked_id: int | None = None,
    labels: tuple[str, ...] | None = None,
) -> Detection | None:
    """Keep the locked track if present, else take the biggest, most confident subject."""
    pool = [d for d in detections if labels is None or d.label in labels]
    if not pool:
        return None
    if locked_id is not None:
        for d in pool:
            if d.track_id == locked_id:
                return d
    return max(pool, key=lambda d: d.area * d.score)
