"""Gyroflow ``.gcsv`` logs and IMU/video sync (roadmap §6.1, A7III-GyroShoe).

The GyroShoe logger samples a BMI270 and records raw integer counts. The
``.gcsv`` header carries the scale factors, so the file stays compact and
lossless. Gyroflow converts with: gyro_rad_s = raw * gscale,
accel_g = raw * ascale, time_s = t * tscale.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from .rolling_shutter import readout_ms

# Bosch BMI270 datasheet sensitivities.
BMI270_GYRO_LSB_PER_DPS = {2000: 16.4, 1000: 32.8, 500: 65.6, 250: 131.2, 125: 262.4}
BMI270_ACCEL_LSB_PER_G = {2: 16384, 4: 8192, 8: 4096, 16: 2048}


def bmi270_scales(gyro_range_dps: int = 2000, accel_range_g: int = 8) -> tuple[float, float]:
    """(gscale rad/s per LSB, ascale g per LSB)."""
    gscale = math.radians(1.0 / BMI270_GYRO_LSB_PER_DPS[gyro_range_dps])
    ascale = 1.0 / BMI270_ACCEL_LSB_PER_G[accel_range_g]
    return gscale, ascale


@dataclass
class GcsvLog:
    t: np.ndarray  # seconds
    gyro: np.ndarray  # (N, 3) rad/s, IMU axes
    accel: np.ndarray | None = None  # (N, 3) g
    orientation: str = "XYZ"  # IMU->camera axis mapping as Gyroflow expects (e.g. "YxZ")
    header: dict[str, str] = field(default_factory=dict)

    @property
    def sample_rate(self) -> float:
        return (len(self.t) - 1) / (self.t[-1] - self.t[0])


def write_gcsv(
    path: str | Path,
    log: GcsvLog,
    readout_mode: str | None = None,
    gscale: float | None = None,
    ascale: float | None = None,
    tscale: float = 1e-6,
    vendor: str = "a7iii-gyroshoe",
) -> Path:
    gscale_d, ascale_d = bmi270_scales()
    gscale = gscale or gscale_d
    ascale = ascale or ascale_d
    hdr = {
        "version": "1.3",
        "id": "a7iii_gyroshoe",
        "orientation": log.orientation,
        "vendor": vendor,
        "lensprofile": "",
        "tscale": repr(tscale),
        "gscale": repr(gscale),
        "ascale": repr(ascale),
    }
    if readout_mode:
        hdr["frame_readout_time"] = f"{readout_ms(readout_mode):.2f}"
        hdr["frame_readout_direction"] = "0"  # top to bottom
    hdr.update(log.header)

    t_raw = np.round((log.t - log.t[0]) / tscale).astype(np.int64)
    g_raw = np.round(np.asarray(log.gyro) / gscale).astype(np.int64)
    cols = ["t", "gx", "gy", "gz"]
    data = [t_raw[:, None], g_raw]
    if log.accel is not None:
        cols += ["ax", "ay", "az"]
        data.append(np.round(np.asarray(log.accel) / ascale).astype(np.int64))
    table = np.hstack(data)

    lines = ["GYROFLOW IMU LOG"] + [f"{k},{v}" for k, v in hdr.items()] + [",".join(cols)]
    lines += [",".join(map(str, row)) for row in table]
    path = Path(path)
    path.write_text("\n".join(lines) + "\n")
    return path


def read_gcsv(path: str | Path) -> GcsvLog:
    lines = Path(path).read_text().splitlines()
    if not lines or lines[0].strip() != "GYROFLOW IMU LOG":
        raise ValueError("not a Gyroflow .gcsv file")
    header: dict[str, str] = {}
    i = 1
    while i < len(lines) and not lines[i].startswith("t,"):
        k, _, v = lines[i].partition(",")
        header[k] = v
        i += 1
    cols = lines[i].split(",")
    raw = np.array([[float(x) for x in ln.split(",")] for ln in lines[i + 1 :] if ln.strip() and not ln.startswith("#")])
    col = {c: raw[:, j] for j, c in enumerate(cols)}
    tscale = float(header.get("tscale", 1e-3))
    gscale = float(header["gscale"])
    ascale = float(header.get("ascale", 1.0))
    accel = np.stack([col["ax"], col["ay"], col["az"]], 1) * ascale if "ax" in col else None
    return GcsvLog(
        t=col["t"] * tscale,
        gyro=np.stack([col["gx"], col["gy"], col["gz"]], 1) * gscale,
        accel=accel,
        orientation=header.get("orientation", "XYZ"),
        header=header,
    )


def estimate_offset(
    imu_t: np.ndarray,
    imu_signal: np.ndarray,
    video_t: np.ndarray,
    video_signal: np.ndarray,
    max_offset_s: float = 2.0,
    rate_hz: float = 200.0,
) -> float:
    """Time offset (s) to ADD to IMU timestamps to align them with video.

    Signals may be 1-D (e.g. |gyro| vs optical-flow magnitude) or (N, k)
    multi-axis *signed* signals (e.g. yaw/pitch rate vs camera rotation rate
    derived from flow). Signed per-axis correlation is far more distinctive
    than magnitudes for quasi-periodic hand shake, so prefer it. Each axis
    is normalised, then the cross-correlations are summed.

    Timestamp video measurements at mid-readout for rolling-shutter frames
    (frame start + readout/2), or the estimate is biased by that amount.
    """
    a_sig = np.asarray(imu_signal, dtype=np.float64)
    b_sig = np.asarray(video_signal, dtype=np.float64)
    if a_sig.ndim == 1:
        a_sig, b_sig = a_sig[:, None], b_sig[:, None]
    if a_sig.shape[1] != b_sig.shape[1]:
        raise ValueError("IMU and video signals need the same number of axes")
    t0 = min(imu_t[0], video_t[0]) - max_offset_s
    t1 = max(imu_t[-1], video_t[-1]) + max_offset_s
    grid = np.arange(t0, t1, 1.0 / rate_hz)
    max_lag = int(round(max_offset_s * rate_hz))
    lags = np.arange(-max_lag, max_lag + 1)
    total = np.zeros(len(lags))
    for k in range(a_sig.shape[1]):
        a = np.interp(grid, imu_t, a_sig[:, k], left=np.nan, right=np.nan)
        b = np.interp(grid, video_t, b_sig[:, k], left=np.nan, right=np.nan)
        a = np.nan_to_num((a - np.nanmean(a)) / (np.nanstd(a) or 1.0))
        b = np.nan_to_num((b - np.nanmean(b)) / (np.nanstd(b) or 1.0))
        # score(lag) = sum a(t) * b(t + lag): video lags the IMU clock by ``lag`` samples
        full = np.correlate(b, a, mode="full")
        center = len(a) - 1
        total += full[center + lags[0]: center + lags[-1] + 1]
    i = int(np.argmax(total))
    frac = 0.0
    if 0 < i < len(total) - 1:  # parabolic sub-sample refinement of the peak
        denom = total[i - 1] - 2 * total[i] + total[i + 1]
        frac = 0.0 if denom == 0 else 0.5 * (total[i - 1] - total[i + 1]) / denom
    return float((lags[i] + frac) / rate_hz)
