"""PTP responder that makes ``VirtualA7III`` look like a USB camera.

``SimTransport`` implements the same ``write``/``read`` byte interface as
``UsbTransport``, so the production ``SonyCamera`` driver runs against the
simulator unmodified: every container is packed, parsed and validated.
"""

from __future__ import annotations

import io
import struct
from collections import deque
from fractions import Fraction

import numpy as np

from ..cinema.shutter import SHUTTER_SPEEDS, sony_ptp_shutter_value
from ..ptp.codes import (
    BUTTON_DOWN,
    LIVEVIEW_HANDLE,
    PROPS,
    SDIO_PROTOCOL_VERSION,
    ContainerType,
    DataType,
    Op,
    Response,
    decode_touch_af,
)
from ..ptp.container import Container, unpack_value
from ..ptp.liveview import FocusFrame, pack_liveview
from ..ptp.props import FORM_ENUM, FORM_RANGE, PropDesc, pack_props
from .camera import VirtualA7III

ISO_VALUES = [50, 64, 80, 100, 125, 160, 200, 250, 320, 400, 500, 640, 800, 1000, 1250, 1600, 2000, 2500,
              3200, 4000, 5000, 6400, 8000, 10000, 12800, 16000, 20000, 25600, 32000, 40000, 51200]
F_NUMBERS = [180, 200, 220, 250, 280, 320, 350, 400, 450, 500, 560, 630, 710, 800, 900, 1000, 1100, 1300,
             1400, 1600, 1800, 2000, 2200]


def _decode_shutter(value: int) -> Fraction:
    num, den = value >> 16, value & 0xFFFF
    if den == 0:
        raise ValueError("bulb not supported in simulator")
    return Fraction(num, den)


class SimTransport:
    def __init__(self, camera: VirtualA7III, jpeg_quality: int = 80):
        self.cam = camera
        self.jpeg_quality = jpeg_quality
        self._out: deque[bytes] = deque()
        self._pending: Container | None = None
        self.session_open = False
        self.sdio_phase = 0
        self.lv_sequence = 0
        self.log: list[tuple[int, tuple[int, ...]]] = []

    # --- transport interface ---------------------------------------------------

    def write(self, data: bytes) -> None:
        c = Container.unpack(data)
        if c.type == ContainerType.COMMAND:
            if c.code in (Op.SONY_SET_CONTROL_DEVICE_A, Op.SONY_SET_CONTROL_DEVICE_B):
                self._pending = c  # wait for the data phase
                return
            self._handle(c, None)
        elif c.type == ContainerType.DATA:
            if self._pending is None or self._pending.transaction_id != c.transaction_id:
                raise RuntimeError("data phase without matching command")
            cmd, self._pending = self._pending, None
            self._handle(cmd, c.payload)

    def read(self, timeout_ms: int = 5000) -> bytes:
        if not self._out:
            raise TimeoutError("simulated camera has nothing to send")
        return self._out.popleft()

    def close(self) -> None:
        pass

    # --- protocol --------------------------------------------------------------

    def _respond(self, cmd: Container, code: int, data: bytes | None = None) -> None:
        if data is not None:
            self._out.append(Container(ContainerType.DATA, cmd.code, cmd.transaction_id, data).pack())
        self._out.append(Container(ContainerType.RESPONSE, code, cmd.transaction_id).pack())

    def _handle(self, cmd: Container, payload: bytes | None) -> None:
        self.log.append((cmd.code, cmd.params))
        op = cmd.code
        if op == Op.OPEN_SESSION:
            code = Response.SESSION_ALREADY_OPEN if self.session_open else Response.OK
            self.session_open = True
            return self._respond(cmd, code)
        if not self.session_open:
            return self._respond(cmd, Response.SESSION_NOT_OPEN)
        if op == Op.CLOSE_SESSION:
            self.session_open = False
            self.sdio_phase = 0
            return self._respond(cmd, Response.OK)
        if op == Op.SONY_SDIO_CONNECT:
            phase = cmd.params[0]
            if phase != self.sdio_phase + 1 and not (phase == 3 and self.sdio_phase == 2):
                return self._respond(cmd, Response.GENERAL_ERROR)
            self.sdio_phase = phase
            return self._respond(cmd, Response.OK)
        if op == Op.SONY_GET_EXT_DEVICE_INFO:
            if self.sdio_phase < 2 or cmd.params[:1] != (SDIO_PROTOCOL_VERSION,):
                return self._respond(cmd, Response.GENERAL_ERROR)
            value_codes = [p.code for p in PROPS.values() if p.control == "value"]
            button_codes = [p.code for p in PROPS.values() if p.control == "button"]
            data = struct.pack("<H", SDIO_PROTOCOL_VERSION)
            data += struct.pack(f"<I{len(value_codes)}H", len(value_codes), *value_codes)
            data += struct.pack(f"<I{len(button_codes)}H", len(button_codes), *button_codes)
            return self._respond(cmd, Response.OK, data)
        if self.sdio_phase < 3 and op in (Op.SONY_SET_CONTROL_DEVICE_A, Op.SONY_SET_CONTROL_DEVICE_B,
                                          Op.SONY_GET_ALL_DEVICE_PROP_DATA):
            return self._respond(cmd, Response.SESSION_NOT_OPEN)
        if op == Op.SONY_SET_CONTROL_DEVICE_A:
            return self._respond(cmd, self._set_value(cmd.params[0], payload))
        if op == Op.SONY_SET_CONTROL_DEVICE_B:
            return self._respond(cmd, self._button(cmd.params[0], payload))
        if op == Op.SONY_GET_ALL_DEVICE_PROP_DATA:
            return self._respond(cmd, Response.OK, pack_props(self._descriptors()))
        if op == Op.GET_OBJECT and cmd.params[:1] == (LIVEVIEW_HANDLE,):
            return self._respond(cmd, Response.OK, self._liveview())
        return self._respond(cmd, Response.OPERATION_NOT_SUPPORTED)

    # --- property handling --------------------------------------------------------

    @staticmethod
    def _prop_by_code(code: int):
        for p in PROPS.values():
            if p.code == code:
                return p
        return None

    def _set_value(self, code: int, payload: bytes) -> int:
        prop = self._prop_by_code(code)
        if prop is None or prop.control != "value":
            return Response.OPERATION_NOT_SUPPORTED
        value = unpack_value(prop.datatype, payload)
        st = self.cam.state
        try:
            if prop.name == "iso":
                if value not in ISO_VALUES:
                    return Response.GENERAL_ERROR
                st.iso = value
            elif prop.name == "shutter_speed":
                t = _decode_shutter(value)
                if t not in SHUTTER_SPEEDS:
                    return Response.GENERAL_ERROR
                st.shutter = t
            elif prop.name == "f_number":
                if value / 100 < self.cam.lens.max_f_number - 1e-9 or value / 100 > 22:
                    return Response.GENERAL_ERROR
                st.f_number = value / 100
            elif prop.name == "focus_mode":
                st.af_mode = {1: "MF", 0x8004: "AF-C", 2: "AF-S"}.get(value, st.af_mode)
            else:
                return Response.OK  # accepted, no simulated effect (WB, program, bias)
        except ValueError:
            return Response.GENERAL_ERROR
        return Response.OK

    def _button(self, code: int, payload: bytes) -> int:
        prop = self._prop_by_code(code)
        if prop is None or prop.control != "button":
            return Response.OPERATION_NOT_SUPPORTED
        value = unpack_value(prop.datatype, payload)
        cam = self.cam
        if prop.name == "half_press":
            cam.state.half_pressed = value == BUTTON_DOWN
        elif prop.name == "shutter_release":
            if value == BUTTON_DOWN:
                if cam.state.movie_mode:
                    return Response.GENERAL_ERROR  # stills capture needs photo mode
                cam.capture_still()
        elif prop.name == "movie_record":
            if value == BUTTON_DOWN:
                cam.start_stop_record()
        elif prop.name == "near_far":
            if value == 0 or abs(value) > 7:
                return Response.GENERAL_ERROR
            cam.focus_move(value)
        elif prop.name == "touch_af_position":
            cam.set_af_point(*decode_touch_af(value))
        return Response.OK

    def _descriptors(self) -> list[PropDesc]:
        st = self.cam.state
        return [
            PropDesc(PROPS["iso"].code, DataType.UINT32, st.iso, form=FORM_ENUM, values=ISO_VALUES, default=100),
            PropDesc(PROPS["shutter_speed"].code, DataType.UINT32, sony_ptp_shutter_value(st.shutter),
                     form=FORM_ENUM, values=[sony_ptp_shutter_value(t) for t in SHUTTER_SPEEDS]),
            PropDesc(PROPS["f_number"].code, DataType.UINT16, round(st.f_number * 100),
                     form=FORM_ENUM, values=[f for f in F_NUMBERS if f >= self.cam.lens.max_f_number * 100 - 1e-6]),
            PropDesc(PROPS["focus_mode"].code, DataType.UINT16, 1 if st.af_mode == "MF" else 0x8004,
                     form=FORM_ENUM, values=[1, 2, 0x8004]),
            PropDesc(PROPS["exposure_bias"].code, DataType.INT16, 0, form=FORM_RANGE, range=(-3000, 3000, 333)),
            PropDesc(PROPS["white_balance"].code, DataType.UINT16, 2),
            PropDesc(PROPS["exposure_program"].code, DataType.UINT16, 0x8050 if st.movie_mode else 1),
        ]

    # --- live view -------------------------------------------------------------------

    def _liveview(self) -> bytes:
        from PIL import Image

        frame = self.cam.render()
        img = Image.fromarray((frame.signal * 255).astype(np.uint8))
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=self.jpeg_quality)
        u, v = self.cam.state.af_point
        in_focus = self._af_point_in_focus(frame)
        status = ("tracking" if self.cam.state.af_mode == "AF-C" else "focused") if in_focus else "unfocused"
        frames = [FocusFrame(u, v, 0.06, 0.1, status)]
        self.lv_sequence += 1
        return pack_liveview(buf.getvalue(), frames, self.lv_sequence, int(self.cam.t * 1000))

    def _af_point_in_focus(self, frame) -> bool:
        from ..optics.dof import depth_of_field

        u, v = self.cam.state.af_point
        y = int(v * (self.cam.H - 1))
        x = int(u * (self.cam.W - 1))
        d = float(frame.depth[y, x]) * 1000.0
        s = self.cam.focus_distance_mm
        if s == float("inf"):
            return d > 20000
        dof = depth_of_field(self.cam.lens.focal_mm, self.cam.state.f_number, s, 0.03)
        return dof.near <= d <= dof.far
