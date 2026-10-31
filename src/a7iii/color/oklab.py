"""OKLab perceptual colour space (Ottosson 2020), from linear Rec.709 RGB."""

from __future__ import annotations

import numpy as np

_M1 = np.array(
    [
        [0.4122214708, 0.5363325363, 0.0514459929],
        [0.2119034982, 0.6806995451, 0.1073969566],
        [0.0883024619, 0.2817188376, 0.6299787005],
    ]
)
_M2 = np.array(
    [
        [0.2104542553, 0.7936177850, -0.0040720468],
        [1.9779984951, -2.4285922050, 0.4505937099],
        [0.0259040371, 0.7827717662, -0.8086757660],
    ]
)
_M1_INV = np.linalg.inv(_M1)
_M2_INV = np.linalg.inv(_M2)


def linear_rgb_to_oklab(rgb: np.ndarray) -> np.ndarray:
    lms = np.asarray(rgb, dtype=np.float64) @ _M1.T
    return np.cbrt(lms) @ _M2.T


def oklab_to_linear_rgb(lab: np.ndarray) -> np.ndarray:
    lms_ = np.asarray(lab, dtype=np.float64) @ _M2_INV.T
    return (lms_**3) @ _M1_INV.T
