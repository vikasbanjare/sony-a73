"""Sony device-property descriptors (GetAllDevicePropData, op 0x9209).

Layout follows libgphoto2's ``ptp_unpack_Sony_DPD`` (UNVERIFIED on
ILCE-7M3, but it's the layout the open-source Sony driver uses):

  u64 entry count, then per entry:
    u16 property code, u16 datatype, u8 get/set, u8 enabled,
    <factory default>, <current value>, u8 form flag,
    form 0x01 (range): min, max, step
    form 0x02 (enum):  u16 count, values...
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field

from .codes import DataType

_FMT = {
    DataType.INT8: "b", DataType.UINT8: "B", DataType.INT16: "h",
    DataType.UINT16: "H", DataType.INT32: "i", DataType.UINT32: "I",
}
FORM_NONE, FORM_RANGE, FORM_ENUM = 0, 1, 2


@dataclass
class PropDesc:
    code: int
    datatype: DataType
    value: int
    writable: bool = True
    enabled: bool = True
    default: int = 0
    form: int = FORM_NONE
    range: tuple[int, int, int] | None = None
    values: list[int] = field(default_factory=list)


def pack_props(props: list[PropDesc]) -> bytes:
    out = struct.pack("<Q", len(props))
    for p in props:
        f = "<" + _FMT[p.datatype]
        out += struct.pack("<HHBB", p.code, int(p.datatype), 1 if p.writable else 0, 1 if p.enabled else 0)
        out += struct.pack(f, p.default) + struct.pack(f, p.value) + struct.pack("<B", p.form)
        if p.form == FORM_RANGE:
            out += b"".join(struct.pack(f, v) for v in p.range)
        elif p.form == FORM_ENUM:
            out += struct.pack("<H", len(p.values)) + b"".join(struct.pack(f, v) for v in p.values)
    return out


def parse_props(data: bytes) -> dict[int, PropDesc]:
    (n,) = struct.unpack_from("<Q", data, 0)
    off = 8
    out: dict[int, PropDesc] = {}
    for _ in range(n):
        code, dt, getset, enabled = struct.unpack_from("<HHBB", data, off)
        off += 6
        dtype = DataType(dt)
        f = "<" + _FMT[dtype]
        size = struct.calcsize(f)
        (default,) = struct.unpack_from(f, data, off)
        (value,) = struct.unpack_from(f, data, off + size)
        off += 2 * size
        (form,) = struct.unpack_from("<B", data, off)
        off += 1
        desc = PropDesc(code, dtype, value, bool(getset), bool(enabled), default, form)
        if form == FORM_RANGE:
            desc.range = struct.unpack_from("<" + _FMT[dtype] * 3, data, off)
            off += 3 * size
        elif form == FORM_ENUM:
            (cnt,) = struct.unpack_from("<H", data, off)
            off += 2
            desc.values = list(struct.unpack_from("<" + _FMT[dtype] * cnt, data, off))
            off += cnt * size
        out[code] = desc
    return out
