"""SMPTE 12M linear timecode (LTC) encoder and decoder.

80-bit frames, least-significant bit first, biphase-mark coded: every bit
cell starts with a transition and a '1' has an extra transition mid-cell.
The decoder is self-clocking (tracks cell length from the signal) so it
works on audio recorded into the camera's mic input, then reports the
sample position where each frame starts, which is what sync needs.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .timecode import Timecode

SYNC_WORD = [0, 0, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 0, 1]  # bits 64..79


def _bcd(value: int, units_bits: int, tens_bits: int) -> tuple[list[int], list[int]]:
    u, t = value % 10, value // 10
    return [(u >> i) & 1 for i in range(units_bits)], [(t >> i) & 1 for i in range(tens_bits)]


def encode_frame_bits(tc: Timecode, user_bits: int = 0) -> list[int]:
    bits = [0] * 80
    ub = [(user_bits >> (4 * i)) & 0xF for i in range(8)]

    def put(start: int, values: list[int]):
        bits[start:start + len(values)] = values

    fu, ft = _bcd(tc.frames, 4, 2)
    su, st = _bcd(tc.seconds, 4, 3)
    mu, mt = _bcd(tc.minutes, 4, 3)
    hu, ht = _bcd(tc.hours, 4, 2)
    put(0, fu); put(8, ft); put(16, su); put(24, st); put(32, mu); put(40, mt); put(48, hu); put(56, ht)
    bits[10] = 1 if tc.drop_frame else 0
    for i, start in enumerate((4, 12, 20, 28, 36, 44, 52, 60)):
        put(start, [(ub[i] >> k) & 1 for k in range(4)])
    put(64, SYNC_WORD)
    # Polarity correction bit (27 at 24/30 fps, 59 at 25 fps) makes the number of zeros even,
    # so every frame starts with the same signal polarity.
    pol = 59 if tc.fps == 25 else 27
    bits[pol] = 0
    if (80 - sum(bits)) % 2 == 1:
        bits[pol] = 1
    return bits


def decode_frame_bits(bits: list[int], fps: int) -> tuple[Timecode, int]:
    def val(start: int, n: int) -> int:
        return sum(bits[start + i] << i for i in range(n))

    tc = Timecode(
        hours=val(48, 4) + 10 * val(56, 2),
        minutes=val(32, 4) + 10 * val(40, 3),
        seconds=val(16, 4) + 10 * val(24, 3),
        frames=val(0, 4) + 10 * val(8, 2),
        fps=fps,
        drop_frame=bool(bits[10]),
    )
    user = 0
    for i, start in enumerate((4, 12, 20, 28, 36, 44, 52, 60)):
        user |= val(start, 4) << (4 * i)
    return tc, user


def generate(start: Timecode, n_frames: int, sample_rate: int = 48000, actual_fps: float | None = None,
             amplitude: float = 0.5, rise_samples: int = 2) -> np.ndarray:
    """LTC audio for ``n_frames`` consecutive frames starting at ``start``."""
    fps = actual_fps or start.fps
    spf = sample_rate / fps
    total = int(round(spf * n_frames))
    out = np.empty(total)
    level = 1.0
    t = start
    for k in range(n_frames):
        bits = encode_frame_bits(t)
        frame_start = k * spf
        for i, b in enumerate(bits):
            c0 = frame_start + i * spf / 80
            c1 = c0 + spf / 80
            a, m, e = int(round(c0)), int(round((c0 + c1) / 2)), int(round(c1))
            level = -level  # transition at cell start
            if b:
                out[a:m] = level
                level = -level
                out[m:e] = level
            else:
                out[a:e] = level
        t = t + 1
    if rise_samples > 1:  # SMPTE specifies a finite rise time; soften the edges a little
        out = np.convolve(out, np.ones(rise_samples) / rise_samples, mode="same")
    return amplitude * out


@dataclass
class DecodedFrame:
    timecode: Timecode
    sample: int  # sample index where the frame's first bit cell starts
    user_bits: int


def decode(signal: np.ndarray, fps: int, sample_rate: int = 48000) -> list[DecodedFrame]:
    s = np.asarray(signal, dtype=np.float64)
    s = s - np.median(s)
    sign = s > 0
    edges = np.nonzero(sign[1:] != sign[:-1])[0] + 1
    if len(edges) < 10:
        return []
    intervals = np.diff(edges)
    cell = sample_rate / fps / 80  # nominal; refined adaptively
    bits: list[int] = []
    starts: list[int] = []
    i = 0
    while i < len(intervals):
        iv = intervals[i]
        if iv > 0.75 * cell:  # long interval: a '0'
            bits.append(0)
            starts.append(int(edges[i]))
            cell = 0.9 * cell + 0.1 * iv
            i += 1
        elif i + 1 < len(intervals) and intervals[i + 1] <= 0.75 * cell:  # two short: a '1'
            bits.append(1)
            starts.append(int(edges[i]))
            cell = 0.9 * cell + 0.1 * (iv + intervals[i + 1])
            i += 2
        else:
            i += 1  # glitch: resync on the next long cell
    out: list[DecodedFrame] = []
    b = np.array(bits)
    sw = np.array(SYNC_WORD)
    for end in range(80, len(b) + 1):
        if np.array_equal(b[end - 16:end], sw):
            frame = b[end - 80:end].tolist()
            try:
                tc, user = decode_frame_bits(frame, fps)
            except ValueError:
                continue
            out.append(DecodedFrame(tc, starts[end - 80], user))
    return out
