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
    DataType,
    Op,
    Response,
)

# Properties a real ILCE-7M3 (FW 4.04) reports as get-only but moves one stop per
# SetControlDeviceB +1/-1, ~0.9 s per step. Key: grows when stepping +1.
STEP_KEYS = {
    "iso": lambda v: v,
    "f_number": lambda v: v,
    "shutter_speed": lambda v: -(v >> 16) / max(v & 0xFFFF, 1),  # +1 = shorter exposure
}
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
        if name in STEP_KEYS:
            desc = self.get_props().get(prop.code)
            if desc is not None and not desc.writable:  # the body only accepts steps for this one
                self._step_to(name, value)
                return
        self.transact(Op.SONY_SET_CONTROL_DEVICE_A, prop.code, data_out=pack_value(prop.datatype, value))

    def wait_value(self, name: str, value: int, timeout_s: float = 3.0) -> int:
        """Poll until the body reports ``value`` (a real a7 III applies writes ~1 s late). Returns the last read."""
        deadline = time.monotonic() + timeout_s
        while True:
            now = self.get_value(name)
            if now == value or time.monotonic() >= deadline:
                return now
            time.sleep(0.15)

    def step(self, name: str, direction: int, timeout_s: float = 3.0) -> int:
        """Move a stepped property one stop (+1/-1) and return the new value once the body reports it."""
        old = self.get_value(name)
        self.transact(Op.SONY_SET_CONTROL_DEVICE_B, PROPS[name].code, data_out=pack_value(DataType.INT8, direction))
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            new = self.get_value(name)
            if new != old:
                return new
            time.sleep(0.15)
        return old  # at the end of its range, or the body ignored it

    def _step_to(self, name: str, target: int, max_steps: int = 40) -> None:
        key = STEP_KEYS[name]
        cur = self.get_value(name)
        for _ in range(max_steps):
            gap = key(target) - key(cur)
            if gap == 0:
                return
            new = self.step(name, 1 if gap > 0 else -1)
            if new == cur:
                raise RuntimeError(f"{name} stopped at {cur} before reaching {target}")
            if (key(target) - key(new)) * gap < 0:
                return  # ponytail: target isn't a stop on this body; keep the first one past it
            cur = new
        raise RuntimeError(f"{name} did not reach {target} in {max_steps} steps")

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
