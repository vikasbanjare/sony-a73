"""Simulated handheld motion and a hot-shoe BMI270 IMU (A7III-GyroShoe).

Motion: smooth intentional pan + physiological hand shake (several
sinusoids, 1-12 Hz). The IMU samples angular rate with bias, white noise
and its own clock, offset from the camera clock, which is what sync has to
recover.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np


@dataclass
class HandheldMotion:
    pan_rate: float = 0.02  # rad/s intentional yaw pan
    shake_amp: float = 0.004  # rad, per component
    seed: int = 0
    _components: list[tuple[float, float, float, int]] = field(default_factory=list)

    def __post_init__(self):
        rng = np.random.default_rng(self.seed)
        # (frequency Hz, amplitude rad, phase, axis 0=yaw 1=pitch)
        self._components = [
            (float(rng.uniform(1, 12)), float(self.shake_amp * rng.uniform(0.4, 1.0)), float(rng.uniform(0, 2 * np.pi)), axis)
            for axis in (0, 1) for _ in range(4)
        ]

    def angles(self, t: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        t = np.asarray(t, dtype=np.float64)
        yaw = self.pan_rate * t
        pitch = np.zeros_like(t)
        for f, a, ph, axis in self._components:
            w = a * np.sin(2 * np.pi * f * t + ph)
            if axis == 0:
                yaw = yaw + w
            else:
                pitch = pitch + w
        return yaw, pitch

    def rates(self, t: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        t = np.asarray(t, dtype=np.float64)
        yaw_r = np.full_like(t, self.pan_rate)
        pitch_r = np.zeros_like(t)
        for f, a, ph, axis in self._components:
            w = a * 2 * np.pi * f * np.cos(2 * np.pi * f * t + ph)
            if axis == 0:
                yaw_r = yaw_r + w
            else:
                pitch_r = pitch_r + w
        return yaw_r, pitch_r


@dataclass
class SimulatedIMU:
    rate_hz: float = 500.0
    clock_offset_s: float = 0.0  # IMU clock = camera clock - offset
    gyro_noise: float = 0.002  # rad/s white noise
    gyro_bias: tuple[float, float, float] = (0.0015, -0.001, 0.0005)
    seed: int = 1

    def sample(self, motion: HandheldMotion, t0: float, t1: float) -> tuple[np.ndarray, np.ndarray]:
        """Return (imu_timestamps, gyro (N,3) rad/s) in the IMU's own clock.

        Axis convention matches the renderer: gyro[:,0] = yaw rate (about Y),
        gyro[:,1] = pitch rate (about X), gyro[:,2] = roll (unused, noise only).
        """
        rng = np.random.default_rng(self.seed)
        t_cam = np.arange(t0, t1, 1.0 / self.rate_hz)
        yaw_r, pitch_r = motion.rates(t_cam)
        gyro = np.stack([yaw_r, pitch_r, np.zeros_like(yaw_r)], axis=1)
        gyro += np.array(self.gyro_bias) + rng.normal(0, self.gyro_noise, gyro.shape)
        return t_cam - self.clock_offset_s, gyro
