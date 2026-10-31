"""Live-view object (handle 0xFFFFC002) packing/parsing - roadmap §10.2.

Real ILCE-7M3 (verified over USB PC Remote): u32 offset to JPEG, u32 JPEG size,
then Sony info data, then the JPEG at that offset (e.g. 1012 / 45568, 1024x576).
The info block isn't decoded yet, so real frames give no focus_frames.

Simulator layout from the roadmap (only the simulator uses it):

  CommonHeader (8 bytes): 0xFF, payload type, sequence (u16), timestamp ms (u32)
  type 0x01 (JPEG):  jpeg size (u32), padding size (u32), jpeg bytes, padding
  type 0x02 (focus): frame count (u16), then per frame:
                     x, y, w, h (u16, 0..10000, centre-based), status (u8), reserved (u8)

``extract_jpeg`` in session.py stays marker-based so the JPEG is found even
if the real header differs.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

COMMON = struct.Struct("<BBHI")
FRAME = struct.Struct("<HHHHBB")

PAYLOAD_JPEG = 0x01
PAYLOAD_FOCUS = 0x02

FOCUS_STATUS = {1: "focused", 2: "unfocused", 3: "tracking", 4: "eye"}


@dataclass
class FocusFrame:
    x: float  # centre, normalised 0..1
    y: float
    w: float
    h: float
    status: str


@dataclass
class LiveView:
    sequence: int
    timestamp_ms: int
    jpeg: bytes | None
    focus_frames: list[FocusFrame]


def _q(v: float) -> int:
    return int(round(min(max(v, 0.0), 1.0) * 10000))


def pack_liveview(jpeg: bytes, frames: list[FocusFrame], sequence: int, timestamp_ms: int) -> bytes:
    out = COMMON.pack(0xFF, PAYLOAD_JPEG, sequence & 0xFFFF, timestamp_ms & 0xFFFFFFFF)
    out += struct.pack("<II", len(jpeg), 0) + jpeg
    out += COMMON.pack(0xFF, PAYLOAD_FOCUS, sequence & 0xFFFF, timestamp_ms & 0xFFFFFFFF)
    out += struct.pack("<H", len(frames))
    status_code = {v: k for k, v in FOCUS_STATUS.items()}
    for f in frames:
        out += FRAME.pack(_q(f.x), _q(f.y), _q(f.w), _q(f.h), status_code[f.status], 0)
    return out


def parse_liveview(blob: bytes) -> LiveView:
    if len(blob) >= 8:
        start, size = struct.unpack_from("<II", blob)
        if size and 8 <= start and start + size <= len(blob) and blob[start:start + 2] == b"\xff\xd8":
            return LiveView(0, 0, blob[start:start + size], [])
    off = 0
    seq = ts = 0
    jpeg = None
    frames: list[FocusFrame] = []
    while off + COMMON.size <= len(blob):
        start, ptype, seq, ts = COMMON.unpack_from(blob, off)
        if start != 0xFF:
            raise ValueError(f"bad live-view header at offset {off}")
        off += COMMON.size
        if ptype == PAYLOAD_JPEG:
            size, pad = struct.unpack_from("<II", blob, off)
            off += 8
            jpeg = blob[off: off + size]
            off += size + pad
        elif ptype == PAYLOAD_FOCUS:
            (n,) = struct.unpack_from("<H", blob, off)
            off += 2
            for _ in range(n):
                x, y, w, h, st, _r = FRAME.unpack_from(blob, off)
                off += FRAME.size
                frames.append(FocusFrame(x / 1e4, y / 1e4, w / 1e4, h / 1e4, FOCUS_STATUS.get(st, "unknown")))
        else:
            raise ValueError(f"unknown live-view payload type 0x{ptype:02x}")
    return LiveView(seq, ts, jpeg, frames)
