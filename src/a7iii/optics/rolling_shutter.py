"""Sensor readout times for Gyroflow rolling-shutter correction (roadmap §6.1).

Values are the roadmap's figures, which line up with commonly published
a7 III measurements. Measure your own body (e.g. with a strobing LED or a
fast pan against verticals) before treating them as calibration data.
"""

from __future__ import annotations

READOUT_MS: dict[str, float] = {
    "ff_4k_24p": 24.4,
    "ff_4k_25p": 24.4,
    "ff_4k_30p": 20.1,  # 1.2x crop
    "s35_4k_24p": 13.8,
    "s35_4k_30p": 13.8,
    "ff_1080_60p": 8.2,
    "ff_1080_120p": 8.2,
}


def readout_ms(mode: str) -> float:
    try:
        return READOUT_MS[mode]
    except KeyError:
        raise ValueError(f"unknown mode {mode!r}; choose from {sorted(READOUT_MS)}") from None


def row_time_offset_s(mode: str, row: int, height: int) -> float:
    """Capture-time offset of a given image row relative to the first row."""
    if not 0 <= row < height:
        raise ValueError("row out of range")
    return readout_ms(mode) / 1000.0 * row / height


def skew_pixels(mode: str, pan_deg_per_s: float, hfov_deg: float, width_px: int) -> float:
    """Horizontal skew (px) between top and bottom rows for a steady pan."""
    return pan_deg_per_s * readout_ms(mode) / 1000.0 / hfov_deg * width_px
