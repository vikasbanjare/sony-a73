"""3D LUT generation and .cube I/O (roadmap section 4.3, stage 2 output)."""

from __future__ import annotations

from pathlib import Path
from typing import Callable

import numpy as np


def lattice(size: int) -> np.ndarray:
    """RGB lattice in .cube order (red varies fastest). Shape (size**3, 3)."""
    axis = np.linspace(0.0, 1.0, size)
    b, g, r = np.meshgrid(axis, axis, axis, indexing="ij")
    return np.stack([r.ravel(), g.ravel(), b.ravel()], axis=-1)


def build_lut(transform: Callable[[np.ndarray], np.ndarray], size: int = 33) -> np.ndarray:
    """Sample ``transform`` (N,3)->(N,3) on a lattice. Returns (size**3, 3)."""
    if size < 2:
        raise ValueError("LUT size must be >= 2")
    out = np.asarray(transform(lattice(size)), dtype=np.float64)
    return np.clip(out, 0.0, 1.0)


def write_cube(path: str | Path, table: np.ndarray, title: str = "a7iii") -> None:
    table = np.asarray(table, dtype=np.float64)
    size = round(table.shape[0] ** (1.0 / 3.0))
    if size**3 != table.shape[0]:
        raise ValueError("table length is not a perfect cube")
    lines = [f'TITLE "{title}"', f"LUT_3D_SIZE {size}", "DOMAIN_MIN 0.0 0.0 0.0", "DOMAIN_MAX 1.0 1.0 1.0"]
    lines += [f"{r:.6f} {g:.6f} {b:.6f}" for r, g, b in table]
    Path(path).write_text("\n".join(lines) + "\n")


def read_cube(path: str | Path) -> np.ndarray:
    size = None
    rows = []
    for raw in Path(path).read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        key = line.split()[0]
        if key == "LUT_3D_SIZE":
            size = int(line.split()[1])
        elif key[0].isdigit() or key[0] in "-.":
            rows.append([float(v) for v in line.split()[:3]])
    table = np.array(rows)
    if size is None or table.shape != (size**3, 3):
        raise ValueError(f"malformed .cube file: {path}")
    return table


def apply_lut_trilinear(table: np.ndarray, rgb: np.ndarray) -> np.ndarray:
    """Apply a 3D LUT to (N,3) RGB in [0,1] with trilinear interpolation."""
    size = round(table.shape[0] ** (1.0 / 3.0))
    cube = table.reshape(size, size, size, 3)  # indexed [b, g, r]
    p = np.clip(np.asarray(rgb, dtype=np.float64), 0.0, 1.0) * (size - 1)
    i0 = np.minimum(np.floor(p).astype(int), size - 2)
    f = p - i0
    r0, g0, b0 = i0[:, 0], i0[:, 1], i0[:, 2]
    fr, fg, fb = f[:, 0:1], f[:, 1:2], f[:, 2:3]
    out = np.zeros_like(p)
    for db in (0, 1):
        for dg in (0, 1):
            for dr in (0, 1):
                wgt = (fr if dr else 1 - fr) * (fg if dg else 1 - fg) * (fb if db else 1 - fb)
                out += wgt * cube[b0 + db, g0 + dg, r0 + dr]
    return out
