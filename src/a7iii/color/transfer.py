"""Camera transfer functions (OETFs) and their inverses.

All functions are vectorised over numpy arrays. "Scene" values are
scene-linear reflectance where 0.18 is 18% middle grey. "Signal" values are
normalised code values in [0, 1] of the *full* 0..1023 (or 0..255) range,
i.e. the same scale as an IRE reading on a 0-109% waveform when legal range
is respected.

Notes on accuracy:
- S-Log2 / S-Log3 follow Sony's published formulas.
- HLG follows ITU-R BT.2100. Sony's HLG1/2/3 picture-profile variants apply
  extra highlight shaping on top of BT.2100; below the knee they track the
  BT.2100 curve closely, which is what exposure tools need.
- Sony's Cine1-4 gammas are unpublished; ``rec709`` is the ITU-R BT.709 OETF
  and is used as the nearest documented proxy for Standard/ITU709/Cine4.
"""

from __future__ import annotations

import numpy as np

ArrayLike = np.ndarray | float

# --- S-Log3 ------------------------------------------------------------------

_SLOG3_CUT_LIN = 0.01125000
_SLOG3_CUT_CV = 171.2102946929


def slog3_encode(x: ArrayLike) -> np.ndarray:
    x = np.asarray(x, dtype=np.float64)
    hi = (420.0 + np.log10((np.maximum(x, _SLOG3_CUT_LIN) + 0.01) / (0.18 + 0.01)) * 261.5) / 1023.0
    lo = (x * (_SLOG3_CUT_CV - 95.0) / _SLOG3_CUT_LIN + 95.0) / 1023.0
    return np.where(x >= _SLOG3_CUT_LIN, hi, lo)


def slog3_decode(y: ArrayLike) -> np.ndarray:
    y = np.asarray(y, dtype=np.float64)
    hi = 10.0 ** ((y * 1023.0 - 420.0) / 261.5) * (0.18 + 0.01) - 0.01
    lo = (y * 1023.0 - 95.0) * _SLOG3_CUT_LIN / (_SLOG3_CUT_CV - 95.0)
    return np.where(y >= _SLOG3_CUT_CV / 1023.0, hi, lo)


# --- S-Log2 (S-Log applied to x * 155/219, legal-range output) ---------------

_SLOG_LIN_OFFSET = 0.030001222851889303


def _slog_encode_full(x: np.ndarray) -> np.ndarray:
    x = x / 0.9  # reflection -> IRE scaling used by Sony
    log_part = 0.432699 * np.log10(np.maximum(x, 0.0) + 0.037584) + 0.616596 + 0.03
    return np.where(x >= 0.0, log_part, x * 5.0 + _SLOG_LIN_OFFSET)


def _slog_decode_full(y: np.ndarray) -> np.ndarray:
    hi = 10.0 ** ((y - 0.616596 - 0.03) / 0.432699) - 0.037584
    lo = (y - _SLOG_LIN_OFFSET) / 5.0
    return np.where(y >= _SLOG_LIN_OFFSET, hi, lo) * 0.9


def slog2_encode(x: ArrayLike) -> np.ndarray:
    x = np.asarray(x, dtype=np.float64)
    y_full = _slog_encode_full(x * 155.0 / 219.0)
    return (y_full * (940.0 - 64.0) + 64.0) / 1023.0  # full -> legal (10-bit)


def slog2_decode(y: ArrayLike) -> np.ndarray:
    y = np.asarray(y, dtype=np.float64)
    y_full = (y * 1023.0 - 64.0) / (940.0 - 64.0)
    return _slog_decode_full(y_full) * 219.0 / 155.0


# --- HLG (ITU-R BT.2100) -----------------------------------------------------

HLG_A = 0.17883277
HLG_B = 1.0 - 4.0 * HLG_A
HLG_C = 0.5 - HLG_A * np.log(4.0 * HLG_A)

# Scene-linear E (0..1) that encodes to 75% signal: HLG reference diffuse white.
HLG_REFERENCE_WHITE_E = (np.exp((0.75 - HLG_C) / HLG_A) + HLG_B) / 12.0


def hlg_oetf(e: ArrayLike) -> np.ndarray:
    """BT.2100 HLG OETF: scene-linear E in [0, 1] -> signal E' in [0, 1]."""
    e = np.clip(np.asarray(e, dtype=np.float64), 0.0, None)
    lo = np.sqrt(3.0 * e)
    hi = HLG_A * np.log(np.maximum(12.0 * e - HLG_B, 1e-12)) + HLG_C
    return np.where(e <= 1.0 / 12.0, lo, hi)


def hlg_inverse_oetf(ep: ArrayLike) -> np.ndarray:
    ep = np.clip(np.asarray(ep, dtype=np.float64), 0.0, None)
    lo = ep**2 / 3.0
    hi = (np.exp((ep - HLG_C) / HLG_A) + HLG_B) / 12.0
    return np.where(ep <= 0.5, lo, hi)


def hlg_encode(x: ArrayLike) -> np.ndarray:
    """Reflectance (1.0 = diffuse white) -> HLG signal."""
    return hlg_oetf(np.asarray(x, dtype=np.float64) * HLG_REFERENCE_WHITE_E)


def hlg_decode(y: ArrayLike) -> np.ndarray:
    """HLG signal -> reflectance (1.0 = diffuse white, 0.18 = middle grey)."""
    return hlg_inverse_oetf(y) / HLG_REFERENCE_WHITE_E


# --- Rec.709 ----------------------------------------------------------------


def rec709_encode(x: ArrayLike) -> np.ndarray:
    x = np.clip(np.asarray(x, dtype=np.float64), 0.0, None)
    return np.where(x < 0.018, 4.5 * x, 1.099 * np.power(x, 0.45) - 0.099)


def rec709_decode(y: ArrayLike) -> np.ndarray:
    y = np.clip(np.asarray(y, dtype=np.float64), 0.0, None)
    return np.where(y < 0.081, y / 4.5, np.power((y + 0.099) / 1.099, 1.0 / 0.45))


ENCODERS = {
    "slog3": slog3_encode,
    "slog2": slog2_encode,
    "hlg": hlg_encode,
    "rec709": rec709_encode,
}
DECODERS = {
    "slog3": slog3_decode,
    "slog2": slog2_decode,
    "hlg": hlg_decode,
    "rec709": rec709_decode,
}


def decode(curve: str, signal: ArrayLike) -> np.ndarray:
    try:
        return DECODERS[curve](signal)
    except KeyError:
        raise ValueError(f"unknown curve {curve!r}; choose from {sorted(DECODERS)}") from None


def encode(curve: str, scene: ArrayLike) -> np.ndarray:
    try:
        return ENCODERS[curve](scene)
    except KeyError:
        raise ValueError(f"unknown curve {curve!r}; choose from {sorted(ENCODERS)}") from None


def middle_grey_signal(curve: str) -> float:
    """Signal level (0..1) of 18% grey for a curve - the exposure target."""
    return float(encode(curve, 0.18))
