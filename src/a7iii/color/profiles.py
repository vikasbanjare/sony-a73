"""In-camera Picture Profile recipes and native (dual conversion gain) ISOs.

Source: docs/ROADMAP.md sections 2.2 and 4.2. The HCG switch point near
ISO 640 (LCG base ISO 100) is consistent with published IMX410 read-noise
measurements; the per-gamma ISO pairs are the roadmap's mapping of that
switch onto each gamma's minimum ISO. Confirm on your own body with a
dark-frame noise sweep before relying on them.
"""

from __future__ import annotations

# gamma -> (LCG base ISO, HCG base ISO)
NATIVE_ISO_BY_GAMMA: dict[str, tuple[int, int]] = {
    "standard": (100, 640),
    "still": (100, 640),
    "cine1": (100, 640),
    "cine2": (100, 640),
    "cine3": (100, 640),
    "cine4": (100, 640),
    "itu709": (100, 640),
    "hlg": (100, 640),
    "hlg1": (100, 640),
    "hlg2": (125, 800),
    "hlg3": (125, 800),
    "slog2": (800, 5000),
    "slog3": (800, 5000),
}

# ISOs just below the HCG switch: more read noise than the HCG ISO above them.
AVOID_ISOS_BY_GAMMA: dict[str, tuple[int, ...]] = {
    **{g: (320, 400, 500) for g in ("standard", "still", "cine1", "cine2", "cine3", "cine4", "itu709", "hlg", "hlg1", "hlg2", "hlg3")},
    "slog2": (2500, 3200, 4000),
    "slog3": (2500, 3200, 4000),
}


def native_isos(gamma: str) -> tuple[int, int]:
    key = gamma.lower().replace("-", "").replace(" ", "")
    try:
        return NATIVE_ISO_BY_GAMMA[key]
    except KeyError:
        raise ValueError(f"unknown gamma {gamma!r}; choose from {sorted(NATIVE_ISO_BY_GAMMA)}") from None


def recommend_iso(gamma: str, required_iso: float) -> int:
    """Pick the cleanest native ISO that still provides ``required_iso``.

    If the needed sensitivity sits between the two native ISOs, jump to the
    HCG ISO rather than using a noisier intermediate value.
    """
    lcg, hcg = native_isos(gamma)
    if required_iso <= lcg:
        return lcg
    if required_iso <= hcg:
        return hcg
    return int(required_iso)


PICTURE_PROFILES: dict[str, dict] = {
    "A7III-Cinetone": {
        "note": "S-Cinetone-inspired starting point, not Sony's S-Cinetone; verify on a chart",
        "slot": "PP6",
        "gamma": "Cine4",
        "black_level": -2,
        "black_gamma": {"range": "Middle", "level": -3},
        "knee": {"mode": "Manual", "point_pct": 80, "slope": 2},
        "color_mode": "Pro",
        "saturation": 2,
        "color_phase": -2,
        "color_depth": {"R": 2, "G": -1, "B": 1, "C": 2, "M": -1, "Y": 1},
        "detail": -7,
        "native_iso": [100, 640],
        "exposure_target": "Middle grey 43-45% IRE; skin 55-62% IRE",
    },
    "A7III-HLG-Cine": {
        "slot": "PP10",
        "gamma": "HLG3",
        "black_level": 0,
        "black_gamma": {"range": "Wide", "level": 2},
        "knee": {"mode": "Auto"},
        "color_mode": "BT.2020",
        "saturation": -3,
        "color_phase": -1,
        "color_depth": {"R": 1, "G": 0, "B": 1, "C": 1, "M": 0, "Y": 0},
        "detail": -7,
        "native_iso": [125, 800],
        "exposure_target": "Middle grey ~40% IRE; zebras at 95%+",
    },
    "A7III-Log2-Pro": {
        "slot": "PP7",
        "gamma": "S-Log2",
        "black_level": 0,
        "black_gamma": {"range": "Middle", "level": 0},
        "knee": {"mode": "Manual", "point_pct": 85, "slope": 1},
        "color_mode": "S-Gamut3.Cine",
        "saturation": 0,
        "color_phase": -1,
        "color_depth": {"R": 0, "G": 0, "B": 0, "C": 0, "M": 0, "Y": 0},
        "detail": -7,
        "native_iso": [800, 5000],
        "exposure_target": "+1.3 to +1.7 EV over meter; skin 55-60% IRE",
    },
    "A7III-Neutral-709": {
        "slot": "PP4",
        "gamma": "ITU709",
        "black_level": 0,
        "black_gamma": {"range": "Middle", "level": 0},
        "knee": {"mode": "Manual", "point_pct": 90, "slope": 0},
        "color_mode": "ITU709 Matrix",
        "saturation": 0,
        "color_phase": -1,
        "color_depth": {"R": 1, "G": 0, "B": 0, "C": 1, "M": 0, "Y": 0},
        "detail": -5,
        "native_iso": [100, 640],
        "exposure_target": "Standard 0.0 EV meter",
    },
    "A7III-FX-Default": {
        "note": "everyday 'set once' profile: richer colour, deeper reds/magentas, gentle highlights. "
                "If skin still looks green-yellow, step Color Phase one notch at a time toward red and "
                "compare on a face. Starting point - verify on a chart. Pair proxies with the fxdefault look.",
        "slot": "PP1",
        "gamma": "Cine4",
        "black_level": 0,
        "black_gamma": {"range": "Middle", "level": -1},
        "knee": {"mode": "Auto"},
        "color_mode": "Pro",
        "saturation": 3,
        "color_phase": 0,
        "color_depth": {"R": 1, "G": -1, "B": 0, "C": 0, "M": 1, "Y": -1},
        "detail": -5,
        "native_iso": [100, 640],
        "exposure_target": "Standard metering; skin 60-70% IRE",
    },
    "A7III-Portrait-Soft": {
        "note": "soft-contrast skin look (roadmap COL-02); starting point, verify on a chart",
        "slot": "PP5",
        "gamma": "Cine1",
        "black_level": 1,
        "black_gamma": {"range": "Wide", "level": 1},
        "knee": {"mode": "Manual", "point_pct": 85, "slope": 1},
        "color_mode": "Cinema",
        "saturation": -1,
        "color_phase": -1,
        "color_depth": {"R": 1, "G": 0, "B": -1, "C": 0, "M": 0, "Y": 1},
        "detail": -7,
        "native_iso": [100, 640],
        "exposure_target": "Skin 60-65% IRE; middle grey ~42% IRE",
    },
    "A7III-SLog3-Cine": {
        "note": "Sony stock PP8 for grading; pair with a7iii_slog3_to_709_*.cube",
        "slot": "PP8",
        "gamma": "S-Log3",
        "black_level": 0,
        "black_gamma": {"range": "Middle", "level": 0},
        "knee": {"mode": "Auto"},
        "color_mode": "S-Gamut3.Cine",
        "saturation": 0,
        "color_phase": 0,
        "color_depth": {"R": 0, "G": 0, "B": 0, "C": 0, "M": 0, "Y": 0},
        "detail": -7,
        "native_iso": [800, 5000],
        "exposure_target": "Middle grey 41% IRE (+1 to +1.7 EV over meter keeps 8-bit shadows clean)",
    },
}
