"""Multi-device audio sync, 4-channel muxing and a clip-repair safety track (roadmap §7).

The a7 III records 2 channels (internal/MI-shoe mic). A USB interface on the
companion host records 2 more, typically a 32-bit float lav + a -12 dB
safety. ``align`` finds the sample offset between devices by
cross-correlation, ``repair_clipping`` swaps in the gain-matched safety
wherever the primary clipped, and ``write_bwf`` writes a polyphonic
Broadcast WAV with the start timecode in its ``bext`` chunk.
"""

from __future__ import annotations

import struct
from pathlib import Path

import numpy as np

from .timecode import Timecode


def find_offset(reference: np.ndarray, other: np.ndarray, max_lag: int | None = None) -> int:
    """Samples to delay ``other`` by so it lines up with ``reference`` (negative = advance)."""
    a = np.asarray(reference, dtype=np.float64)
    b = np.asarray(other, dtype=np.float64)
    n = len(a) + len(b) - 1
    nfft = 1 << (n - 1).bit_length()
    corr = np.fft.irfft(np.fft.rfft(a, nfft) * np.conj(np.fft.rfft(b, nfft)), nfft)
    lags = np.concatenate([np.arange(0, len(a)), np.arange(-(len(b) - 1), 0)])
    vals = np.concatenate([corr[: len(a)], corr[nfft - (len(b) - 1):]])
    if max_lag is not None:
        keep = np.abs(lags) <= max_lag
        lags, vals = lags[keep], vals[keep]
    return int(lags[np.argmax(vals)])


def shift_signal(x: np.ndarray, offset: int, length: int) -> np.ndarray:
    """Place ``x`` delayed by ``offset`` samples into a zero buffer of ``length``."""
    out = np.zeros(length)
    src0 = max(0, -offset)
    dst0 = max(0, offset)
    n = min(len(x) - src0, length - dst0)
    if n > 0:
        out[dst0:dst0 + n] = x[src0:src0 + n]
    return out


def repair_clipping(primary: np.ndarray, safety: np.ndarray, safety_gain_db: float = -12.0,
                    clip_level: float = 0.999, crossfade: int = 32) -> tuple[np.ndarray, int]:
    """Replace clipped stretches of ``primary`` with the gain-matched ``safety``.

    Returns (repaired, number of clipped samples found).
    """
    p = np.asarray(primary, dtype=np.float64)
    s = np.asarray(safety, dtype=np.float64) * 10 ** (-safety_gain_db / 20)
    clipped = np.abs(p) >= clip_level
    if not clipped.any():
        return p.copy(), 0
    # widen the mask and build a smooth crossfade weight
    w = np.convolve(clipped.astype(float), np.ones(2 * crossfade + 1), mode="same") > 0
    w = np.convolve(w.astype(float), np.hanning(2 * crossfade + 1) / np.hanning(2 * crossfade + 1).sum(), mode="same")
    return (1 - w) * p + w * s, int(clipped.sum())


def write_bwf(path: str | Path, channels: list[np.ndarray], sample_rate: int = 48000, bits: int = 24,
              start: Timecode | None = None, actual_fps: float | None = None, description: str = "",
              originator: str = "a7iii-control-desk") -> Path:
    """Write a polyphonic WAV (PCM 16/24-bit or 32-bit float) with an optional BWF ``bext`` chunk."""
    data = np.stack([np.asarray(c, dtype=np.float64) for c in channels], axis=1)
    n_ch = data.shape[1]
    if bits == 32:
        fmt_tag, payload = 3, data.astype("<f4").tobytes()
    elif bits in (16, 24):
        fmt_tag = 1
        scale = 2 ** (bits - 1) - 1
        ints = np.clip(np.round(data * scale), -scale - 1, scale).astype("<i4")
        if bits == 16:
            payload = ints.astype("<i2").tobytes()
        else:
            raw = ints.reshape(-1).view(np.uint8).reshape(-1, 4)[:, :3]
            payload = raw.tobytes()
    else:
        raise ValueError("bits must be 16, 24 or 32 (float)")
    block = n_ch * bits // 8
    fmt = struct.pack("<HHIIHH", fmt_tag, n_ch, sample_rate, sample_rate * block, block, bits)
    chunks = [b"fmt " + struct.pack("<I", len(fmt)) + fmt]
    if start is not None:
        ref = int(round(start.seconds_since_midnight(actual_fps) * sample_rate))
        bext = (
            description.encode()[:256].ljust(256, b"\0")
            + originator.encode()[:32].ljust(32, b"\0")
            + b"".ljust(32, b"\0")
            + b"2026-10-31"
            + b"00:00:00"
            + struct.pack("<II", ref & 0xFFFFFFFF, ref >> 32)
            + struct.pack("<H", 2)
            + b"\0" * 64  # UMID
            + b"\0" * 10  # loudness fields
            + b"\0" * 180  # reserved
            + f"A=PCM,F={sample_rate},W={bits},M={'stereo' if n_ch == 2 else 'poly'},T=a7iii;TC={start}\r\n".encode()
        )
        if len(bext) % 2:
            bext += b"\0"
        chunks.append(b"bext" + struct.pack("<I", len(bext)) + bext)
    chunks.append(b"data" + struct.pack("<I", len(payload)) + payload + (b"\0" if len(payload) % 2 else b""))
    body = b"WAVE" + b"".join(chunks)
    path = Path(path)
    path.write_bytes(b"RIFF" + struct.pack("<I", len(body)) + body)
    return path


def read_wav(path: str | Path) -> tuple[np.ndarray, int, dict]:
    """Minimal reader for files written by ``write_bwf``: (samples (N, ch), rate, info)."""
    raw = Path(path).read_bytes()
    if raw[:4] != b"RIFF" or raw[8:12] != b"WAVE":
        raise ValueError("not a WAV file")
    off = 12
    info: dict = {}
    fmt = None
    data = b""
    while off + 8 <= len(raw):
        cid, size = raw[off:off + 4], struct.unpack_from("<I", raw, off + 4)[0]
        body = raw[off + 8: off + 8 + size]
        if cid == b"fmt ":
            fmt = struct.unpack_from("<HHIIHH", body)
        elif cid == b"bext":
            lo, hi = struct.unpack_from("<II", body, 338)
            info["time_reference"] = lo | (hi << 32)
            info["coding_history"] = body[602:].rstrip(b"\0").decode(errors="replace")
        elif cid == b"data":
            data = body
        off += 8 + size + (size % 2)
    if fmt is None:
        raise ValueError("missing fmt chunk")
    tag, ch, rate, _, _, bits = fmt
    if tag == 3:
        samples = np.frombuffer(data, "<f4").astype(np.float64)
    elif bits == 16:
        samples = np.frombuffer(data, "<i2") / 32767.0
    else:
        b = np.frombuffer(data, np.uint8).reshape(-1, 3)
        ints = (b[:, 0].astype(np.int32) | (b[:, 1].astype(np.int32) << 8) | (b[:, 2].astype(np.int32) << 16))
        ints = np.where(ints >= 1 << 23, ints - (1 << 24), ints)
        samples = ints / float(2**23 - 1)
    return samples.reshape(-1, ch), rate, info
