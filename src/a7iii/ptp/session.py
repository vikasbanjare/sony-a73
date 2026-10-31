"""Sony PTP remote session: handshake, property access and actions."""

from __future__ import annotations

import struct
import time
from dataclasses import dataclass

from .codes import (
    BUTTON_DOWN,
    BUTTON_UP,
    LIVEVIEW_HANDLE,
    PROPS,
    SDIO_PROTOCOL_VERSION,
    ContainerType,
    Op,
    Response,
)
from .container import Container, command, pack_value
from .transport import Transport


class PTPError(RuntimeError):
    def __init__(self, op: int, code: int):
        try:
            name = Response(code).name
        except ValueError:
            name = f"0x{code:04X}"
        super().__init__(f"PTP op 0x{op:04X} failed: {name}")
        self.op = op
        self.code = code


@dataclass
class Result:
    params: tuple[int, ...]
    data: bytes


class SonyCamera:
    def __init__(self, transport: Transport, session_id: int = 1):
        self.t = transport
        self.session_id = session_id
        self._tid = 0

    # --- transaction plumbing -------------------------------------------------

    def _next_tid(self) -> int:
        self._tid = (self._tid + 1) & 0xFFFFFFFF
        return self._tid

    def transact(self, op: int, *params: int, data_out: bytes | None = None) -> Result:
        tid = 0 if op == Op.OPEN_SESSION else self._next_tid()
        self.t.write(command(op, tid, *params).pack())
        if data_out is not None:
            self.t.write(Container(ContainerType.DATA, op, tid, data_out).pack())
        data = b""
        while True:
            c = Container.unpack(self.t.read())
            if c.type == ContainerType.DATA:
                data += c.payload
            elif c.type == ContainerType.RESPONSE:
                if c.transaction_id != tid:
                    raise RuntimeError(f"transaction id mismatch: sent {tid}, got {c.transaction_id}")
                if c.code != Response.OK:
                    raise PTPError(op, c.code)
                return Result(c.params, data)
            # events on the bulk pipe are ignored here

    # --- session & Sony handshake --------------------------------------------

    def open(self) -> None:
        try:
            self.transact(Op.OPEN_SESSION, self.session_id)
        except PTPError as e:
            if e.code != Response.SESSION_ALREADY_OPEN:
                raise

    def sdio_handshake(self) -> list[int]:
        """Three-phase SDIO connect. Returns the supported property codes."""
        self.transact(Op.SONY_SDIO_CONNECT, 1, 0, 0)
        self.transact(Op.SONY_SDIO_CONNECT, 2, 0, 0)
        info = self.transact(Op.SONY_GET_EXT_DEVICE_INFO, SDIO_PROTOCOL_VERSION).data
        self.transact(Op.SONY_SDIO_CONNECT, 3, 0, 0)
        return parse_ext_device_info(info)

    def connect(self) -> list[int]:
        self.open()
        return self.sdio_handshake()

    def close(self) -> None:
        try:
            self.transact(Op.CLOSE_SESSION)
        finally:
            self.t.close()

    # --- properties & controls -----------------------------------------------

    def set_prop(self, name: str, value: int) -> None:
        prop = PROPS[name]
        if prop.control != "value":
            raise ValueError(f"{name} is a button control; use press()")
        self.transact(Op.SONY_SET_CONTROL_DEVICE_A, prop.code, data_out=pack_value(prop.datatype, value))

    def control(self, name: str, value: int) -> None:
        prop = PROPS[name]
        if prop.control != "button":
            raise ValueError(f"{name} is a value property; use set_prop()")
        self.transact(Op.SONY_SET_CONTROL_DEVICE_B, prop.code, data_out=pack_value(prop.datatype, value))

    def press(self, name: str, hold_s: float = 0.05) -> None:
        self.control(name, BUTTON_DOWN)
        if hold_s:
            time.sleep(hold_s)
        self.control(name, BUTTON_UP)

    def focus_step(self, steps: int) -> None:
        """Relative focus move; negative = near, positive = far."""
        if steps == 0:
            return
        if not -7 <= steps <= 7:
            raise ValueError("focus step must be within -7..7 per command")
        self.control("near_far", steps)

    def get_all_props_raw(self) -> bytes:
        return self.transact(Op.SONY_GET_ALL_DEVICE_PROP_DATA).data

    def get_props(self) -> dict[int, "PropDesc"]:
        from .props import parse_props

        return parse_props(self.get_all_props_raw())

    def get_value(self, name: str) -> int:
        code = PROPS[name].code
        props = self.get_props()
        if code not in props:
            raise KeyError(f"camera did not report {name} (0x{code:04X})")
        return props[code].value

    def set_af_point(self, u: float, v: float) -> None:
        """Move the AF point (image-normalised). Uses the unverified 0xD2E4 encoding."""
        from .codes import encode_touch_af

        self.control("touch_af_position", encode_touch_af(u, v))

    def liveview(self):
        """Fetch and parse a live-view object (JPEG + focus frames)."""
        from .liveview import parse_liveview

        return parse_liveview(self.liveview_frame())

    def liveview_frame(self) -> bytes:
        """Return the raw live-view object; see ``extract_jpeg``."""
        return self.transact(Op.GET_OBJECT, LIVEVIEW_HANDLE).data


def parse_ext_device_info(data: bytes) -> list[int]:
    """Parse SDIO GetExtDeviceInfo: u16 version, then u32-counted u16 arrays.

    The first array lists property codes; a second (if present) lists
    control codes. Both are returned merged.
    """
    if len(data) < 2:
        return []
    off = 2
    codes: list[int] = []
    while off + 4 <= len(data):
        (n,) = struct.unpack_from("<I", data, off)
        off += 4
        if off + 2 * n > len(data):
            break
        codes += list(struct.unpack_from(f"<{n}H", data, off))
        off += 2 * n
    return codes


def extract_jpeg(liveview: bytes) -> bytes | None:
    """Locate the JPEG inside a live-view object by its SOI/EOI markers.

    Avoids depending on the exact (model-specific) header layout.
    """
    start = liveview.find(b"\xff\xd8")
    end = liveview.rfind(b"\xff\xd9")
    if start < 0 or end < start:
        return None
    return liveview[start : end + 2]
