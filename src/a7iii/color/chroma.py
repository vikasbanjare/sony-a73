"""8-bit 4:2:0 -> float 4:4:4 reconstruction (roadmap §4.3 step 3).

Internal a7 III files are 8-bit 4:2:0 BT.709 narrow range. Before grading,
the chroma planes are upsampled with a *joint bilateral* filter guided by
full-resolution luma, so colour edges snap to luma edges instead of
bleeding, and everything is promoted to float32 so LUTs don't re-quantise.

Chroma siting is MPEG-2/H.264 default ("left"): co-sited horizontally with
even luma columns, centred vertically between luma rows.
"""

from __future__ import annotations

import numpy as np

# BT.709 Y'CbCr -> R'G'B' (normalised, full-swing after range expansion)
_KR, _KB = 0.2126, 0.0722
_KG = 1.0 - _KR - _KB
YCBCR709_TO_RGB = np.array(
    [
        [1.0, 0.0, 2 * (1 - _KR)],
        [1.0, -2 * _KB * (1 - _KB) / _KG, -2 * _KR * (1 - _KR) / _KG],
        [1.0, 2 * (1 - _KB), 0.0],
    ]
)


RANGE_WEIGHT_FLOOR = 1e-4


def _luma_at_chroma_sites(y: np.ndarray, ch: int, cw: int) -> np.ndarray:
    """Luma at left-sited chroma positions: mean of rows 2j, 2j+1 at column 2i."""
    h, w = y.shape
    r0 = np.minimum(2 * np.arange(ch), h - 1)
    r1 = np.minimum(2 * np.arange(ch) + 1, h - 1)
    cols = np.minimum(2 * np.arange(cw), w - 1)
    return 0.5 * (y[r0][:, cols] + y[r1][:, cols])


def upsample_chroma(
    y: np.ndarray,
    c: np.ndarray,
    sigma_spatial: float = 1.0,
    sigma_range: float = 0.04,
) -> np.ndarray:
    """Joint-bilateral upsample of one chroma plane to luma resolution.

    ``y`` is (H, W) and ``c`` is (H/2, W/2), both float in [0, 1].
    """
    y = np.asarray(y, dtype=np.float32)
    c = np.asarray(c, dtype=np.float32)
    h, w = y.shape
    ch, cw = c.shape
    if (ch, cw) != ((h + 1) // 2, (w + 1) // 2):
        raise ValueError(f"chroma {c.shape} does not match luma {y.shape} for 4:2:0")
    y_low = _luma_at_chroma_sites(y, ch, cw)

    rows = np.arange(h, dtype=np.float32)
    cols = np.arange(w, dtype=np.float32)
    # nearest low-res sample index for each full-res pixel
    j0 = np.clip(np.floor((rows - 0.5) / 2).astype(int), 0, ch - 1)
    i0 = np.clip(np.floor(cols / 2).astype(int), 0, cw - 1)

    num = np.zeros((h, w), dtype=np.float32)
    den = np.zeros((h, w), dtype=np.float32)
    for dj in (-1, 0, 1, 2):
        jj = np.clip(j0 + dj, 0, ch - 1)
        dy = rows - (2 * jj + 0.5)
        for di in (-1, 0, 1, 2):
            ii = np.clip(i0 + di, 0, cw - 1)
            dx = cols - 2 * ii
            spatial = np.exp(-(dy[:, None] ** 2 + dx[None, :] ** 2) / (2 * (2 * sigma_spatial) ** 2))
            # Floor keeps the filter well-defined where luma matches no neighbour
            # (noise/texture): it then degrades to plain spatial interpolation.
            rng = np.exp(-((y - y_low[jj][:, ii]) ** 2) / (2 * sigma_range**2)) + RANGE_WEIGHT_FLOOR
            wgt = spatial * rng
            num += wgt * c[jj][:, ii]
            den += wgt
    return num / np.maximum(den, 1e-12)


def yuv420_to_rgb444(y8: np.ndarray, cb8: np.ndarray, cr8: np.ndarray, **kwargs) -> np.ndarray:
    """8-bit narrow-range BT.709 4:2:0 planes -> float32 (H, W, 3) R'G'B'.

    Output is non-linear (still in the camera curve) and unclipped, so
    super-whites/sub-blacks survive for the grade.
    """
    y = (np.asarray(y8, dtype=np.float32) - 16.0) / 219.0
    cb = (np.asarray(cb8, dtype=np.float32) - 128.0) / 224.0
    cr = (np.asarray(cr8, dtype=np.float32) - 128.0) / 224.0
    cb_full = upsample_chroma(y, cb + 0.5, **kwargs) - 0.5
    cr_full = upsample_chroma(y, cr + 0.5, **kwargs) - 0.5
    ycc = np.stack([y, cb_full, cr_full], axis=-1)
    return (ycc @ YCBCR709_TO_RGB.T.astype(np.float32)).astype(np.float32)


def quantize_tpdf(x: np.ndarray, bits: int, rng: np.random.Generator | None = None) -> np.ndarray:
    """Quantise [0,1] floats to ``bits`` with triangular dither (+/-1 LSB).

    Use when writing graded float output back to an integer format; it
    trades banding for fine, uncorrelated noise.
    """
    rng = rng or np.random.default_rng()
    levels = (1 << bits) - 1
    noise = rng.random(np.shape(x)) - rng.random(np.shape(x))
    q = np.round(np.asarray(x, dtype=np.float64) * levels + noise)
    return np.clip(q, 0, levels).astype(np.uint16 if bits > 8 else np.uint8)
