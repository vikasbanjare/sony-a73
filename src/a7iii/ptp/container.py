"""PTP-over-USB container encoding (ISO 15740 / PIMA 15740 USB still image class)."""

from __future__ import annotations

import struct
from dataclasses import dataclass

from .codes import ContainerType, DataType

HEADER = struct.Struct("<IHHI")  # length, type, code, transaction id
MAX_PARAMS = 5

_PACK = {
    DataType.INT8: "<b", DataType.UINT8: "<B",
    DataType.INT16: "<h", DataType.UINT16: "<H",
    DataType.INT32: "<i", DataType.UINT32: "<I",
}


@dataclass
class Container:
    type: ContainerType
    code: int
    transaction_id: int
    payload: bytes = b""

    @property
    def params(self) -> tuple[int, ...]:
        if self.type == ContainerType.DATA:
            raise ValueError("data containers carry a payload, not params")
        n = len(self.payload) // 4
        return struct.unpack(f"<{n}I", self.payload[: n * 4])

    def pack(self) -> bytes:
        return HEADER.pack(HEADER.size + len(self.payload), int(self.type), self.code, self.transaction_id) + self.payload

    @classmethod
    def unpack(cls, raw: bytes) -> "Container":
        if len(raw) < HEADER.size:
            raise ValueError(f"short PTP container ({len(raw)} bytes)")
        length, ctype, code, tid = HEADER.unpack_from(raw)
        if length < HEADER.size or length > len(raw):
            raise ValueError(f"bad PTP container length {length} (have {len(raw)} bytes)")
        return cls(ContainerType(ctype), code, tid, bytes(raw[HEADER.size:length]))


def command(code: int, transaction_id: int, *params: int) -> Container:
    if len(params) > MAX_PARAMS:
        raise ValueError(f"PTP commands take at most {MAX_PARAMS} parameters")
    return Container(ContainerType.COMMAND, code, transaction_id, struct.pack(f"<{len(params)}I", *params))


def pack_value(datatype: DataType, value: int) -> bytes:
    return struct.pack(_PACK[datatype], value)


def unpack_value(datatype: DataType, raw: bytes, offset: int = 0) -> int:
    return struct.unpack_from(_PACK[datatype], raw, offset)[0]
