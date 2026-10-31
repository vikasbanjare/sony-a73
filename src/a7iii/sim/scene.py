"""Procedural 3D scenes for the virtual a7 III.

Everything is analytic so it can be sampled at any pixel and any time:
that is what lets the renderer do rolling shutter (each row at its own
time) and camera rotation without resampling images.

World units are metres. The camera looks down +Z; image coordinates are
angles (radians) from the optical axis, x right and y down.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Callable

import numpy as np

# ColorChecker Classic, sRGB 8-bit (D65), row-major from Dark Skin.
COLORCHECKER_SRGB8 = np.array([
    [115, 82, 68], [194, 150, 130], [98, 122, 157], [87, 108, 67], [133, 128, 177], [103, 189, 170],
    [214, 126, 44], [80, 91, 166], [193, 90, 99], [94, 60, 108], [157, 188, 64], [224, 163, 46],
    [56, 61, 150], [70, 148, 73], [175, 54, 60], [231, 199, 31], [187, 86, 149], [8, 133, 161],
    [243, 243, 242], [200, 200, 200], [160, 160, 160], [122, 122, 121], [85, 85, 85], [52, 52, 52],
], dtype=np.float64)


def srgb_to_linear(v: np.ndarray) -> np.ndarray:
    v = np.asarray(v, dtype=np.float64)
    return np.where(v <= 0.04045, v / 12.92, ((v + 0.055) / 1.055) ** 2.4)


COLORCHECKER_LINEAR = srgb_to_linear(COLORCHECKER_SRGB8 / 255.0)


def _hash01(ix: np.ndarray, iy: np.ndarray) -> np.ndarray:
    """Deterministic pseudo-random value in [0, 1) per integer lattice point."""
    n = (ix.astype(np.int64) * 374761393 + iy.astype(np.int64) * 668265263) & 0xFFFFFFFF
    n = ((n ^ (n >> 13)) * 1274126177) & 0xFFFFFFFF
    return ((n ^ (n >> 16)) & 0xFFFFFF) / float(0x1000000)


def _value_noise(X: np.ndarray, Y: np.ndarray, cell: float) -> np.ndarray:
    """Smooth aperiodic noise in [0, 1) with features about ``cell`` metres across."""
    gx, gy = X / cell, Y / cell
    x0, y0 = np.floor(gx), np.floor(gy)
    fx, fy = gx - x0, gy - y0
    fx, fy = fx * fx * (3 - 2 * fx), fy * fy * (3 - 2 * fy)
    a, b = _hash01(x0, y0), _hash01(x0 + 1, y0)
    c, d = _hash01(x0, y0 + 1), _hash01(x0 + 1, y0 + 1)
    return (a * (1 - fx) + b * fx) * (1 - fy) + (c * (1 - fx) + d * fx) * fy


def _texture(X: np.ndarray, Y: np.ndarray, scale: float | None) -> np.ndarray:
    """Band-limited detail texture in [0.25, 0.75] with features near ``scale`` metres.

    ``scale=None`` gives a flat 0.5 (for exposure tests).
    """
    if scale is None:
        return np.full(np.shape(X), 0.5)
    k = 2 * math.pi / scale
    # Periodic structure (like fabric or brick) plus aperiodic detail, so image
    # registration has a unique answer, as it does on real scenes.
    t = (
        0.5
        + 0.06 * np.sin(k * X) * np.sin(k * Y)
        + 0.04 * np.sin(2.3 * k * X + 1.7) * np.cos(1.9 * k * Y)
        + 0.04 * np.sign(np.sin(0.25 * k * X) * np.sin(0.25 * k * Y))
        + 0.20 * (_value_noise(X, Y, scale * 0.6) - 0.5)
        + 0.10 * (_value_noise(X + 17.3, Y - 4.1, scale * 2.5) - 0.5)
    )
    return t


@dataclass
class Subject:
    """A person-like figure: body ellipse, head disc, two dark eyes."""

    path: Callable[[np.ndarray], np.ndarray] = field(default=lambda t: np.stack([-0.6 + 0.4 * t, np.full_like(t, 2.5)], -1))
    height: float = 1.75
    width: float = 0.5
    eye_offset: float = 0.0325
    head_r: float = 0.11
    eye_r: float = 0.014
    skin: tuple[float, float, float] = (0.44, 0.29, 0.22)
    shirt: tuple[float, float, float] = (0.08, 0.14, 0.32)

    def position(self, t: np.ndarray | float) -> tuple[np.ndarray, np.ndarray]:
        """(X, Z) of the subject's centre line at time t."""
        p = np.asarray(self.path(np.atleast_1d(np.asarray(t, dtype=np.float64))))
        return p[..., 0], p[..., 1]

    def head_center_y(self) -> float:
        # Camera at 1.6 m eye height; Y down, so a head at 1.62 m sits slightly above axis.
        return -(self.height - self.head_r - 1.6)


@dataclass
class Scene:
    background_depth: float = 6.0
    background_tint: tuple[float, float, float] = (0.55, 0.5, 0.45)
    texture_scale: float | None = 0.05
    subject: Subject | None = None
    tilted_plane: tuple[float, float] | None = None  # (near depth at bottom, far depth at top) fills frame
    chart_depth: float | None = None
    chart_size: float = 0.6  # metres wide
    ev100: float = 9.0  # scene brightness; 9 ~ bright interior, 14-15 ~ daylight
    flicker_hz: float | None = None  # mains frequency (light flickers at 2x)
    flicker_depth: float = 0.6
    shadow_patch: tuple[float, ...] | None = None  # reflectances of a strip of near-black patches

    # --- geometry helpers ---------------------------------------------------

    def chart_layout(self) -> tuple[float, float, float, float] | None:
        """Chart bounding box in image angles (x0, y0, x1, y1)."""
        if self.chart_depth is None:
            return None
        w = self.chart_size / self.chart_depth
        h = w * 4 / 6
        return (-w / 2, -h / 2, w / 2, h / 2)

    def keypoints(self, t: float) -> dict[str, tuple[float, float]] | None:
        """Ground-truth image angles of subject features at time t (no camera rotation)."""
        if self.subject is None:
            return None
        s = self.subject
        X, Z = s.position(t)
        X, Z = float(X[0]), float(Z[0])
        hy = s.head_center_y()
        ey = hy - 0.01
        return {
            "l_eye": ((X - s.eye_offset) / Z, ey / Z),
            "r_eye": ((X + s.eye_offset) / Z, ey / Z),
            "nose": (X / Z, (hy + 0.03) / Z),
            "head": (X / Z, hy / Z),
            "torso": (X / Z, (hy + 0.45) / Z),
            "depth": (Z, Z),
        }

    # --- sampling -------------------------------------------------------------

    def sample(self, u: np.ndarray, v: np.ndarray, t_row: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """Radiance (reflectance x tint, linear RGB) and depth at image angles (u, v).

        ``u``, ``v`` are (H, W) arrays, ``t_row`` is (H,) sample time per row.
        """
        H, W = u.shape
        if self.tilted_plane is not None:
            near, far = self.tilted_plane
            frac = np.clip(0.5 - v / (2 * np.max(np.abs(v))), 0.0, 1.0)  # 0 at bottom, 1 at top
            depth = near + (far - near) * frac
            tex = _texture(u * depth, v * depth, self.texture_scale)
            rgb = tex[..., None] * np.array(self.background_tint)
        else:
            depth = np.full((H, W), self.background_depth)
            tex = _texture(u * depth, v * depth, None if self.texture_scale is None else self.texture_scale * self.background_depth / 2)
            rgb = tex[..., None] * np.array(self.background_tint)

        if self.shadow_patch is not None:
            n = len(self.shadow_patch)
            band = (v > 0.12) & (v < 0.18)
            for i, refl in enumerate(self.shadow_patch):
                cell = band & (u > -0.3 + 0.6 * i / n) & (u < -0.3 + 0.6 * (i + 0.8) / n)
                rgb[cell] = refl

        box = self.chart_layout()
        if box is not None:
            x0, y0, x1, y1 = box
            inside = (u >= x0) & (u < x1) & (v >= y0) & (v < y1)
            if inside.any():
                col = np.clip(((u - x0) / (x1 - x0) * 6).astype(int), 0, 5)
                row = np.clip(((v - y0) / (y1 - y0) * 4).astype(int), 0, 3)
                fx = (u - x0) / (x1 - x0) * 6 - col
                fy = (v - y0) / (y1 - y0) * 4 - row
                patch = inside & (fx > 0.1) & (fx < 0.9) & (fy > 0.1) & (fy < 0.9)
                frame = inside & ~patch
                rgb[patch] = COLORCHECKER_LINEAR[row[patch] * 6 + col[patch]]
                rgb[frame] = 0.02
                depth[inside] = self.chart_depth

        if self.subject is not None:
            s = self.subject
            X, Z = s.position(t_row)  # (H,)
            Xc, Zc = X[:, None], Z[:, None]
            wx, wy = u * Zc, v * Zc  # world coords on the subject plane
            dx = wx - Xc
            hy = s.head_center_y()
            body = ((dx / (s.width / 2)) ** 2 + ((wy - (hy + 0.75)) / 0.65) ** 2) <= 1.0
            head = (dx**2 + (wy - hy) ** 2) <= s.head_r**2
            eyes = ((dx - s.eye_offset) ** 2 + (wy - hy + 0.01) ** 2 <= s.eye_r**2) | (
                (dx + s.eye_offset) ** 2 + (wy - hy + 0.01) ** 2 <= s.eye_r**2
            )
            in_front = Zc < depth
            stripes = 0.75 + 0.25 * np.sign(np.sin(2 * math.pi * wy / 0.02))
            body_m = body & ~head & in_front
            head_m = head & in_front
            rgb[body_m] = (np.array(s.shirt) * stripes[..., None])[body_m]
            rgb[head_m] = np.array(s.skin)
            rgb[eyes & in_front] = 0.02
            depth = np.where(body_m | head_m, np.broadcast_to(Zc, depth.shape), depth)
        return rgb, depth

    def flicker_factor(self, t_start: np.ndarray, exposure: float) -> np.ndarray:
        """Mean illumination over [t, t+exposure] per row for AC-lit scenes."""
        if not self.flicker_hz:
            return np.ones_like(t_start)
        w = 4 * math.pi * self.flicker_hz  # light intensity ~ sin^2 -> cos at 2f
        integral = (np.sin(w * (t_start + exposure)) - np.sin(w * t_start)) / (w * exposure)
        return 1.0 + self.flicker_depth * integral


# --- ready-made scenes ---------------------------------------------------------


def walking_subject_scene(speed_mps: float = 0.6, depth: float = 2.5, start_x: float = -0.6, **kw) -> Scene:
    subj = Subject(path=lambda t: np.stack([start_x + speed_mps * t, np.full_like(t, depth)], -1))
    return Scene(subject=subj, **kw)


def approaching_subject_scene(start_depth: float = 4.0, speed_mps: float = 0.8, **kw) -> Scene:
    subj = Subject(path=lambda t: np.stack([np.zeros_like(t), np.maximum(start_depth - speed_mps * t, 1.0)], -1))
    return Scene(subject=subj, **kw)


def macro_scene(near: float = 0.30, far: float = 0.42) -> Scene:
    return Scene(tilted_plane=(near, far), texture_scale=0.0025, background_tint=(0.6, 0.55, 0.45), ev100=12.0)


def chart_scene(depth: float = 2.0, ev100: float = 10.0) -> Scene:
    return Scene(chart_depth=depth, ev100=ev100)
