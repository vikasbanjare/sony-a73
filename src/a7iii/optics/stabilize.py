"""Gyro-based stabilisation with rolling-shutter correction (roadmap §6.1).

A small, self-contained version of what Gyroflow does, used for preview
and for verifying GyroShoe logs: integrate gyro to orientation, smooth it,
and shift every *row* by the difference between raw and smoothed
orientation at that row's capture time (t + y/H * readout). For the small
rotations of handheld shake, rotation about the vertical/horizontal axes is
a pixel translation of f_px * angle.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.ndimage import gaussian_filter1d


@dataclass
class GyroTrack:
    t: np.ndarray  # camera-clock seconds
    yaw: np.ndarray  # integrated, radians
    pitch: np.ndarray

    @classmethod
    def from_gyro(cls, t: np.ndarray, gyro: np.ndarray, offset_s: float = 0.0, remove_bias: bool = True) -> "GyroTrack":
        """``offset_s`` is added to IMU timestamps to get camera time (see gyro.estimate_offset)."""
        t = np.asarray(t, dtype=np.float64) + offset_s
        g = np.asarray(gyro, dtype=np.float64)
        if remove_bias:
            # Bias = mean rate is wrong if the shot contains a deliberate pan; use the median of
            # the high-passed rate instead, which ignores slow intentional motion.
            g = g - (np.median(g - gaussian_filter1d(g, 200, axis=0), axis=0))
        dt = np.diff(t, prepend=t[0])
        yaw = np.cumsum(g[:, 0] * dt)
        pitch = np.cumsum(g[:, 1] * dt)
        return cls(t, yaw, pitch)

    def smoothed(self, smoothness_s: float = 0.5) -> "GyroTrack":
        rate = (len(self.t) - 1) / (self.t[-1] - self.t[0])
        sigma = smoothness_s * rate
        return GyroTrack(self.t, gaussian_filter1d(self.yaw, sigma, mode="nearest"),
                         gaussian_filter1d(self.pitch, sigma, mode="nearest"))

    def at(self, times: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        return np.interp(times, self.t, self.yaw), np.interp(times, self.t, self.pitch)


def row_corrections(raw: GyroTrack, smooth: GyroTrack, frame_t: float, height: int, readout_s: float,
                    f_px: float) -> tuple[np.ndarray, np.ndarray]:
    """Per-row (dx, dy) *sampling offsets* that move the frame onto the smoothed path.

    Convention: a camera rotated by angle a images world angle (x + a) at
    pixel x, so output pixel x must sample input pixel x + (smooth - raw) * f.
    """
    t_rows = frame_t + readout_s * np.arange(height) / height
    ry, rp = raw.at(t_rows)
    sy, sp = smooth.at(t_rows)
    return (sy - ry) * f_px, (sp - rp) * f_px


def apply_row_shifts(frame: np.ndarray, dx: np.ndarray, dy: np.ndarray) -> np.ndarray:
    """Resample a frame with per-row translations (bilinear). Edges clamp."""
    H, W = frame.shape[:2]
    out = np.empty_like(frame)
    xs = np.arange(W, dtype=np.float64)
    for y in range(H):
        sx = np.clip(xs + dx[y], 0, W - 1)
        sy = float(np.clip(y + dy[y], 0, H - 1))
        y0 = int(np.floor(sy))
        y1 = min(y0 + 1, H - 1)
        fy = sy - y0
        x0 = np.floor(sx).astype(int)
        x1 = np.minimum(x0 + 1, W - 1)
        fx = (sx - x0)[:, None] if frame.ndim == 3 else sx - x0
        top = frame[y0, x0] * (1 - fx) + frame[y0, x1] * fx
        bot = frame[y1, x0] * (1 - fx) + frame[y1, x1] * fx
        out[y] = top * (1 - fy) + bot * fy
    return out
