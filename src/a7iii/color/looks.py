"""FX-style LUT pack for the a7 III: log/HDR -> Rec.709 looks.

Inputs are the a7 III's own capture formats as set by this repo's Picture
Profile recipes (S-Log3 and S-Log2 with S-Gamut3.Cine, HLG with BT.2020).
Each gets three outputs:

- ``technical``: correct gamut matrix + Sony-style highlight roll-off to
  Rec.709. The monitoring LUT (like the FX3's s709 MLUT) and the grading start.
- ``cinetone``: softer contrast, earlier roll-off and gentler saturation,
  *inspired by* S-Cinetone. Not Sony's proprietary S-Cinetone processing.
- ``portrait``: soft contrast and slightly warm, for skin.

Gamut primaries are Sony's / ITU's published xy values (D65 white).
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

from ..cinema.cine_ei import display_tonemap
from .dctl import lut_dctl
from .lut import build_lut, write_cube
from .transfer import decode, rec709_encode

PRIMARIES = {  # (R, G, B) xy chromaticities
    "rec709": ((0.640, 0.330), (0.300, 0.600), (0.150, 0.060)),
    "sgamut3cine": ((0.766, 0.275), (0.225, 0.800), (0.089, -0.087)),
    "sgamut3": ((0.730, 0.280), (0.140, 0.855), (0.100, -0.050)),
    "bt2020": ((0.708, 0.292), (0.170, 0.797), (0.131, 0.046)),
}
PRIMARIES["sgamut"] = PRIMARIES["sgamut3"]  # S-Gamut and S-Gamut3 share primaries
D65 = (0.3127, 0.3290)

# a7 III capture format -> (transfer curve, gamut)
INPUTS = {
    "slog3": ("slog3", "sgamut3cine"),
    "slog2": ("slog2", "sgamut3cine"),  # matches the A7III-Log2-Pro recipe, not stock PP7 (S-Gamut)
    "hlg": ("hlg", "bt2020"),
}
# look -> (contrast around grey, saturation, roll-off knee, RGB warmth gains)
LOOKS = {
    "technical": (1.0, 1.0, 0.60, (1.0, 1.0, 1.0)),
    "cinetone": (0.90, 0.94, 0.50, (1.01, 1.0, 0.99)),
    "portrait": (0.85, 0.90, 0.45, (1.02, 1.0, 0.97)),
}


def rgb_to_xyz(gamut: str) -> np.ndarray:
    xy = np.array(PRIMARIES[gamut] + (D65,))
    xyz = np.column_stack([xy[:, 0] / xy[:, 1], np.ones(4), (1 - xy[:, 0] - xy[:, 1]) / xy[:, 1]])
    prim, white = xyz[:3].T, xyz[3]
    return prim * np.linalg.solve(prim, white)  # scale columns so RGB(1,1,1) -> white


def gamut_matrix(src: str, dst: str) -> np.ndarray:
    return np.linalg.solve(rgb_to_xyz(dst), rgb_to_xyz(src))


def look_transform(source: str, look: str):
    curve, gamut = INPUTS[source]
    contrast, sat, knee, warm = LOOKS[look]
    m = gamut_matrix(gamut, "rec709")
    luma = np.array([0.2126, 0.7152, 0.0722])

    def f(signal: np.ndarray) -> np.ndarray:
        lin = np.clip(decode(curve, signal) @ m.T, 0.0, None)  # ponytail: clip out-of-gamut, no gamut compression
        lin = 0.18 * np.power(lin / 0.18, contrast)  # contrast pivots on middle grey
        y = (lin @ luma)[:, None]
        lin = (y + sat * (lin - y)) * np.array(warm)
        return rec709_encode(display_tonemap(np.clip(lin, 0.0, None), knee=knee))

    return f


def write_lut_pack(out: str | Path, sizes: tuple[int, ...] = (33, 65)) -> list[Path]:
    """Write every input x look as .cube (each size) plus a DCTL for the largest."""
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    written = []
    for src in INPUTS:
        for look in LOOKS:
            name = f"a7iii_{src}_to_709_{look}"
            for n in sizes:
                p = out / f"{name}_{n}.cube"
                write_cube(p, build_lut(look_transform(src, look), n), title=name)
                written.append(p)
            d = out / f"{name}.dctl"
            d.write_text(lut_dctl(out / f"{name}_{max(sizes)}.cube", name))
            written.append(d)
    return written
