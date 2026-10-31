"""ColorChecker Classic reference + patch sampling - calibrate without a reference camera.

The reference is X-Rite's published sRGB (D65) rendering of the 24 patches,
row by row from dark skin to black. Matching the a7 III to it gives *accurate*
colour; matching to an FX3 (``a7iii match`` with two charts) gives *FX3* colour.
"""

from __future__ import annotations

import numpy as np

REFERENCE_SRGB8 = np.array([
    [115, 82, 68], [194, 150, 130], [98, 122, 157], [87, 108, 67], [133, 128, 177], [103, 189, 170],
    [214, 126, 44], [80, 91, 166], [193, 90, 99], [94, 60, 108], [157, 188, 64], [224, 163, 46],
    [56, 61, 150], [70, 148, 73], [175, 54, 60], [231, 199, 31], [187, 86, 149], [8, 133, 161],
    [243, 243, 242], [200, 200, 200], [160, 160, 160], [122, 122, 121], [85, 85, 85], [52, 52, 52],
], dtype=np.float64)


def reference_linear() -> np.ndarray:
    """The 24 patches as scene-linear Rec.709 (sRGB primaries), shape (24, 3)."""
    c = REFERENCE_SRGB8 / 255.0
    return np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)


def sample_chart(image: np.ndarray, corners: list[tuple[float, float]], box: int = 9) -> np.ndarray:
    """Average the 24 patches of a 6x4 chart in ``image`` (H, W, 3, values 0..1).

    ``corners`` are the pixel centres of dark skin (top-left), bluish green
    (top-right), white (bottom-left) and black (bottom-right). Patch centres are
    bilinear between them, so mild perspective is fine. Returns (24, 3).
    """
    tl, tr, bl, br = (np.asarray(c, dtype=np.float64) for c in corners)
    h = box // 2
    out = []
    for row in range(4):
        v = row / 3
        left, right = tl + (bl - tl) * v, tr + (br - tr) * v
        for col in range(6):
            x, y = left + (right - left) * (col / 5)
            x, y = int(round(x)), int(round(y))
            out.append(image[max(y - h, 0):y + h + 1, max(x - h, 0):x + h + 1].reshape(-1, 3).mean(axis=0))
    return np.array(out)
