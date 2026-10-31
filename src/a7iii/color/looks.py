"""FX-style LUT pack for the a7 III: log/HDR -> Rec.709 looks.

Inputs are the a7 III's own capture formats as set by this repo's Picture
Profile recipes (S-Log3 and S-Log2 with S-Gamut3.Cine, HLG with BT.2020).

Looks, all built without FX3 footage from published behaviour:

- ``technical``: correct gamut matrix + Sony-style highlight roll-off to
  Rec.709. The monitoring LUT (like the FX3's s709 MLUT) and the grading start.
- ``cinetone``: softer contrast, earlier roll-off, calmer colour with skin
  hues protected - *inspired by* S-Cinetone, not Sony's processing.
- ``portrait``: soft contrast and slightly warm, for skin.
- ``cl_*``: the FX3's Creative Looks (ST, PT, NT, VV, VV2, FL, IN, SH, BW, SE),
  rebuilt from Sony's descriptions of each look. Approximations.

Gamut primaries are Sony's / ITU's published xy values (D65 white).
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

from ..cinema.cine_ei import display_tonemap
from .dctl import lut_dctl
from .lut import build_lut, write_cube
from .oklab import linear_rgb_to_oklab, oklab_to_linear_rgb
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
    # default (no Picture Profile) Standard / Cine4 / ITU709 footage; Rec.709 OETF stands in for Sony's unpublished gamma
    "std709": ("rec709", "rec709"),
}

DEFAULT = dict(contrast=1.0, sat=1.0, skin_sat=None, skin_shift=0.0, knee=0.60, warm=(1.0, 1.0, 1.0), ev=0.0,
               lift=0.0, shadow_tint=(0.0, 0.0, 0.0), highlight_tint=(0.0, 0.0, 0.0), mono=False, tone=(1.0, 1.0, 1.0))
LOOKS = {
    "technical": {},
    # FX-style default rendering: richer colour, skin pulled from the a7 III's green-yellow lean toward warm/pink
    "fxdefault": dict(sat=1.12, skin_sat=1.02, skin_shift=-4.0, warm=(1.005, 1.0, 0.995)),
    "cinetone": dict(contrast=0.90, sat=0.90, skin_sat=1.0, knee=0.50, warm=(1.01, 1.0, 0.99)),
    "portrait": dict(contrast=0.85, sat=0.90, skin_sat=0.97, knee=0.45, warm=(1.02, 1.0, 0.97)),
    # FX3 Creative Look-inspired
    "cl_st": dict(contrast=1.05),  # Standard: balanced
    "cl_pt": dict(contrast=0.90, sat=0.88, skin_sat=1.0, knee=0.50, warm=(1.015, 1.0, 0.985)),  # Portrait: soft skin
    "cl_nt": dict(contrast=0.95, sat=0.78),  # Natural: muted, calm
    "cl_vv": dict(contrast=1.12, sat=1.30, skin_sat=1.10),  # Vivid: punchy colour
    "cl_vv2": dict(contrast=1.0, sat=1.22, ev=0.25),  # Vivid 2: bright and clear
    "cl_fl": dict(contrast=1.10, sat=0.78, lift=0.035,  # Film: muted, matte, teal shadows / warm highlights
                  shadow_tint=(-0.012, 0.004, 0.016), highlight_tint=(0.016, 0.006, -0.010)),
    "cl_in": dict(contrast=0.85, sat=0.85, lift=0.06, highlight_tint=(0.02, 0.01, -0.015)),  # Instant: faded print
    "cl_sh": dict(contrast=0.85, sat=0.85, ev=0.5, warm=(0.99, 1.0, 1.02)),  # Soft high-key: bright, airy
    "cl_bw": dict(contrast=1.10, mono=True),  # Black & white
    "cl_se": dict(contrast=1.05, mono=True, tone=(1.07, 1.0, 0.84)),  # Sepia
}
SKIN_HUE_DEG, SKIN_HUE_WIDTH = 45.0, 22.0  # OKLab hue of ColorChecker dark/light skin (44-46 deg), and spread
LUMA = np.array([0.2126, 0.7152, 0.0722])


def rgb_to_xyz(gamut: str) -> np.ndarray:
    xy = np.array(PRIMARIES[gamut] + (D65,))
    xyz = np.column_stack([xy[:, 0] / xy[:, 1], np.ones(4), (1 - xy[:, 0] - xy[:, 1]) / xy[:, 1]])
    prim, white = xyz[:3].T, xyz[3]
    return prim * np.linalg.solve(prim, white)  # scale columns so RGB(1,1,1) -> white


def gamut_matrix(src: str, dst: str) -> np.ndarray:
    return np.linalg.solve(rgb_to_xyz(dst), rgb_to_xyz(src))


def saturate(lin: np.ndarray, sat: float, skin_sat: float | None, skin_shift: float = 0.0) -> np.ndarray:
    """Scale chroma in OKLab; skin hues get ``skin_sat`` instead (S-Cinetone-style skin
    protection) and are rotated by ``skin_shift`` degrees (negative = toward red)."""
    if sat == 1.0 and skin_sat in (None, 1.0) and not skin_shift:
        return lin
    lab = linear_rgb_to_oklab(lin)
    hue = np.arctan2(lab[:, 2], lab[:, 1])
    chroma = np.hypot(lab[:, 1], lab[:, 2])
    w = np.exp(-(((np.degrees(hue) - SKIN_HUE_DEG + 180) % 360 - 180) / SKIN_HUE_WIDTH) ** 2)
    scale = sat + ((skin_sat if skin_sat is not None else sat) - sat) * w
    hue = hue + np.radians(skin_shift) * w
    lab[:, 1], lab[:, 2] = chroma * scale * np.cos(hue), chroma * scale * np.sin(hue)
    return oklab_to_linear_rgb(lab)


def look_transform(source: str, look: str):
    curve, gamut = INPUTS[source]
    p = {**DEFAULT, **LOOKS[look]}
    m = gamut_matrix(gamut, "rec709")
    if curve == "rec709":  # already display-referred: no second highlight roll-off
        tone = lambda x: np.clip(x, 0.0, 1.0)  # noqa: E731
    else:
        tone = lambda x: display_tonemap(x, knee=p["knee"])  # noqa: E731

    def f(signal: np.ndarray) -> np.ndarray:
        lin = np.clip(decode(curve, signal) @ m.T, 0.0, None)  # ponytail: clip out-of-gamut, no gamut compression
        lin = 0.18 * np.power(lin * 2.0 ** p["ev"] / 0.18, p["contrast"])  # contrast pivots on middle grey
        if p["mono"]:
            lin = np.repeat((lin @ LUMA)[:, None], 3, axis=1)
        lin = np.clip(saturate(lin, p["sat"], p["skin_sat"], p["skin_shift"]), 0.0, None) * np.array(p["warm"])
        d = rec709_encode(tone(lin))
        d = p["lift"] + (1.0 - p["lift"]) * d  # matte blacks
        d = d + np.array(p["shadow_tint"]) * (1.0 - d) ** 2 + np.array(p["highlight_tint"]) * d**2  # split tone
        return d * np.array(p["tone"])

    return f


def write_lut_pack(out: str | Path, sizes: tuple[int, ...] = (33, 65)) -> list[Path]:
    """Write every input x look as .cube plus a DCTL. Creative Looks get the
    smallest size only (a 65-pt cube is ~7 MB; 33-pt is plenty for a look)."""
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    written = []
    for src in INPUTS:
        for look in LOOKS:
            name = f"a7iii_{src}_to_709_{look}"
            look_sizes = (min(sizes),) if look.startswith("cl_") else sizes
            for n in look_sizes:
                p = out / f"{name}_{n}.cube"
                write_cube(p, build_lut(look_transform(src, look), n), title=name)
                written.append(p)
            d = out / f"{name}.dctl"
            d.write_text(lut_dctl(out / f"{name}_{max(look_sizes)}.cube", name))
            written.append(d)
    return written
