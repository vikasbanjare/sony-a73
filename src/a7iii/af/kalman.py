"""Constant-velocity Kalman filter for a 2D focus point (roadmap RSK-03).

Used to predict where the subject will be after the vision + USB latency,
so the AF point lands on the subject rather than where it was.
"""

from __future__ import annotations

import numpy as np


class PointKalman:
    def __init__(self, process_noise: float = 2.0, measurement_noise: float = 1e-4):
        self.q = process_noise  # acceleration spectral density (normalised units / s^2)
        self.r = measurement_noise
        self.x: np.ndarray | None = None  # [x, y, vx, vy]
        self.P = np.eye(4)
        self.t: float | None = None

    @staticmethod
    def _F(dt: float) -> np.ndarray:
        F = np.eye(4)
        F[0, 2] = F[1, 3] = dt
        return F

    def _Q(self, dt: float) -> np.ndarray:
        q = self.q
        block = np.array([[dt**4 / 4, dt**3 / 2], [dt**3 / 2, dt**2]]) * q
        Q = np.zeros((4, 4))
        Q[np.ix_([0, 2], [0, 2])] = block
        Q[np.ix_([1, 3], [1, 3])] = block
        return Q

    def reset(self) -> None:
        self.x = None
        self.t = None
        self.P = np.eye(4)

    def update(self, t: float, x: float, y: float) -> None:
        z = np.array([x, y])
        if self.x is None:
            self.x = np.array([x, y, 0.0, 0.0])
            self.P = np.diag([self.r, self.r, 1.0, 1.0])
            self.t = t
            return
        dt = max(t - self.t, 1e-6)
        F = self._F(dt)
        self.x = F @ self.x
        self.P = F @ self.P @ F.T + self._Q(dt)
        H = np.zeros((2, 4))
        H[0, 0] = H[1, 1] = 1.0
        S = H @ self.P @ H.T + np.eye(2) * self.r
        K = self.P @ H.T @ np.linalg.inv(S)
        self.x = self.x + K @ (z - H @ self.x)
        self.P = (np.eye(4) - K @ H) @ self.P
        self.t = t

    def predict(self, t: float) -> tuple[float, float]:
        """Position at time ``t`` (does not change the filter state)."""
        if self.x is None:
            raise RuntimeError("filter has no measurements yet")
        x = self._F(t - self.t) @ self.x
        return float(np.clip(x[0], 0.0, 1.0)), float(np.clip(x[1], 0.0, 1.0))

    @property
    def velocity(self) -> tuple[float, float]:
        if self.x is None:
            return (0.0, 0.0)
        return float(self.x[2]), float(self.x[3])
