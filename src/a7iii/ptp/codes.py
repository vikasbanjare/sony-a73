"""PTP and Sony vendor-extension codes.

Opcode names and semantics follow libgphoto2's ``ptp.h`` / Sony driver,
which is the most widely exercised open implementation. Note this differs
from the roadmap's §10.2 table, which has 0x9205 and 0x9207 swapped:
0x9205 sets property *values*; 0x9207 drives *button-style* controls.

Entries marked ``verified=False`` are taken from the roadmap only and need
confirming against a real ILCE-7M3 (check GetExtDeviceInfo's list).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum


class ContainerType(IntEnum):
    COMMAND = 1
    DATA = 2
    RESPONSE = 3
    EVENT = 4


class Op(IntEnum):
    GET_DEVICE_INFO = 0x1001
    OPEN_SESSION = 0x1002
    CLOSE_SESSION = 0x1003
    GET_OBJECT_INFO = 0x1008
    GET_OBJECT = 0x1009
    # Sony "SDIO" vendor extension
    SONY_SDIO_CONNECT = 0x9201
    SONY_GET_EXT_DEVICE_INFO = 0x9202
    SONY_GET_DEVICE_PROP_DESC = 0x9203
    SONY_GET_DEVICE_PROP_VALUE = 0x9204
    SONY_SET_CONTROL_DEVICE_A = 0x9205  # property values
    SONY_GET_CONTROL_DEVICE_DESC = 0x9206
    SONY_SET_CONTROL_DEVICE_B = 0x9207  # buttons / actions
    SONY_GET_ALL_DEVICE_PROP_DATA = 0x9209


class Response(IntEnum):
    OK = 0x2001
    GENERAL_ERROR = 0x2002
    SESSION_NOT_OPEN = 0x2003
    OPERATION_NOT_SUPPORTED = 0x2005
    DEVICE_BUSY = 0x2019
    SESSION_ALREADY_OPEN = 0x201E


class DataType(IntEnum):
    INT8 = 0x0001
    UINT8 = 0x0002
    INT16 = 0x0003
    UINT16 = 0x0004
    INT32 = 0x0005
    UINT32 = 0x0006


@dataclass(frozen=True)
class Prop:
    code: int
    name: str
    datatype: DataType
    control: str  # "value" -> 0x9205, "button" -> 0x9207
    verified: bool = True


PROPS: dict[str, Prop] = {p.name: p for p in [
    Prop(0x5005, "white_balance", DataType.UINT16, "value"),
    Prop(0x5007, "f_number", DataType.UINT16, "value"),  # f-number x 100
    Prop(0x500A, "focus_mode", DataType.UINT16, "value"),
    Prop(0x500E, "exposure_program", DataType.UINT16, "value"),
    Prop(0x5010, "exposure_bias", DataType.INT16, "value"),  # EV x 1000
    Prop(0xD20D, "shutter_speed", DataType.UINT32, "value"),  # (num << 16) | den
    Prop(0xD21E, "iso", DataType.UINT32, "value"),
    Prop(0xD2C1, "half_press", DataType.UINT16, "button"),  # 2 = down, 1 = up
    Prop(0xD2C2, "shutter_release", DataType.UINT16, "button"),  # 2 = down, 1 = up
    Prop(0xD2C8, "movie_record", DataType.UINT16, "button"),  # 2 = down, 1 = up
    Prop(0xD2D1, "near_far", DataType.INT16, "button"),  # signed focus step
    # Not reported by a real ILCE-7M3 on FW 4.04 (docs/CAMERA_BASELINE.md); kept for the simulator and other bodies.
    Prop(0xD2E4, "touch_af_position", DataType.UINT32, "button", verified=False),
]}

BUTTON_DOWN = 2
BUTTON_UP = 1

LIVEVIEW_HANDLE = 0xFFFFC002
SDIO_PROTOCOL_VERSION = 0x00C8  # 2.00

SONY_VID = 0x054C

# Touch-AF / AF-point position. Encoding per the roadmap's 0..10000 convention:
# (x << 16) | y. UNVERIFIED on ILCE-7M3 - confirm before trusting on hardware.
TOUCH_AF_SCALE = 10000


def encode_touch_af(u: float, v: float) -> int:
    x = int(round(min(max(u, 0.0), 1.0) * TOUCH_AF_SCALE))
    y = int(round(min(max(v, 0.0), 1.0) * TOUCH_AF_SCALE))
    return (x << 16) | y


def decode_touch_af(value: int) -> tuple[float, float]:
    return ((value >> 16) & 0xFFFF) / TOUCH_AF_SCALE, (value & 0xFFFF) / TOUCH_AF_SCALE
