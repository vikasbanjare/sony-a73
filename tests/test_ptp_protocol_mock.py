import struct

import pytest

from a7iii.ptp.codes import ContainerType, Op, Response
from a7iii.ptp.container import Container, command
from a7iii.ptp.session import PTPError, SonyCamera, extract_jpeg, parse_ext_device_info
from a7iii.ptp.transport import MockTransport


def ok(tid, *params):
    return Container(ContainerType.RESPONSE, Response.OK, tid, struct.pack(f"<{len(params)}I", *params)).pack()


def data(op, tid, payload):
    return Container(ContainerType.DATA, op, tid, payload).pack()


def test_command_packing():
    raw = command(Op.OPEN_SESSION, 0, 1).pack()
    assert raw == struct.pack("<IHHII", 16, 1, 0x1002, 0, 1)
    c = Container.unpack(raw)
    assert c.params == (1,) and c.code == Op.OPEN_SESSION


def test_unpack_rejects_truncated():
    with pytest.raises(ValueError):
        Container.unpack(b"\x20\x00\x00\x00\x01\x00")
    with pytest.raises(ValueError):
        Container.unpack(struct.pack("<IHHI", 40, 3, 0x2001, 1))


def test_handshake_sequence():
    t = MockTransport()
    info = struct.pack("<H", 0xC8) + struct.pack("<I3H", 3, 0x5007, 0xD20D, 0xD21E) + struct.pack("<I1H", 1, 0xD2C1)
    t.queue(
        ok(0),  # OpenSession (tid 0)
        ok(1),  # connect phase 1
        ok(2),  # connect phase 2
        data(Op.SONY_GET_EXT_DEVICE_INFO, 3, info), ok(3),
        ok(4),  # connect phase 3
    )
    cam = SonyCamera(t)
    codes = cam.connect()
    assert codes == [0x5007, 0xD20D, 0xD21E, 0xD2C1]
    sent = [Container.unpack(w) for w in t.written]
    assert [(c.code, c.params) for c in sent] == [
        (Op.OPEN_SESSION, (1,)),
        (Op.SONY_SDIO_CONNECT, (1, 0, 0)),
        (Op.SONY_SDIO_CONNECT, (2, 0, 0)),
        (Op.SONY_GET_EXT_DEVICE_INFO, (0xC8,)),
        (Op.SONY_SDIO_CONNECT, (3, 0, 0)),
    ]


def test_set_prop_uses_control_a_with_data_phase():
    t = MockTransport()
    t.queue(ok(1))
    SonyCamera(t).set_prop("iso", 640)
    cmd, dat = (Container.unpack(w) for w in t.written)
    assert cmd.code == Op.SONY_SET_CONTROL_DEVICE_A and cmd.params == (0xD21E,)
    assert dat.type == ContainerType.DATA and dat.payload == struct.pack("<I", 640)


def test_buttons_use_control_b():
    t = MockTransport()
    t.queue(ok(1), ok(2))
    SonyCamera(t).press("shutter_release", hold_s=0)
    cmds = [Container.unpack(w) for w in t.written[::2]]
    datas = [Container.unpack(w).payload for w in t.written[1::2]]
    assert all(c.code == Op.SONY_SET_CONTROL_DEVICE_B and c.params == (0xD2C2,) for c in cmds)
    assert datas == [struct.pack("<H", 2), struct.pack("<H", 1)]


def test_property_kind_mismatch_rejected():
    cam = SonyCamera(MockTransport())
    with pytest.raises(ValueError):
        cam.set_prop("shutter_release", 2)
    with pytest.raises(ValueError):
        cam.control("iso", 100)
    with pytest.raises(ValueError):
        cam.focus_step(9)


def test_error_response_raises():
    t = MockTransport()
    t.queue(Container(ContainerType.RESPONSE, Response.DEVICE_BUSY, 1).pack())
    with pytest.raises(PTPError, match="DEVICE_BUSY"):
        SonyCamera(t).set_prop("f_number", 280)


def test_parse_real_sony_liveview_layout():
    from a7iii.ptp.liveview import FocusFrame, pack_liveview, parse_liveview

    jpeg = b"\xff\xd8" + b"img" * 50 + b"\xff\xd9"
    # header bytes seen on a real ILCE-7M3: offset 1012, then info block, JPEG at offset
    blob = struct.pack("<II", 1012, len(jpeg)) + b"\x55" * 1004 + jpeg
    assert parse_liveview(blob).jpeg == jpeg
    # simulator layout still parses
    sim = parse_liveview(pack_liveview(jpeg, [FocusFrame(0.5, 0.5, 0.1, 0.1, "focused")], 7, 99))
    assert sim.jpeg == jpeg and sim.sequence == 7 and len(sim.focus_frames) == 1


def test_liveview_jpeg_extraction():
    jpeg = b"\xff\xd8" + b"img" + b"\xff\xd9"
    blob = b"\x00" * 8 + struct.pack("<II", len(jpeg), 0) + jpeg + b"\x00" * 4
    t = MockTransport()
    t.queue(data(Op.GET_OBJECT, 1, blob), ok(1))
    assert extract_jpeg(SonyCamera(t).liveview_frame()) == jpeg
    assert extract_jpeg(b"no image") is None


def test_parse_ext_device_info_tolerates_truncation():
    assert parse_ext_device_info(b"") == []
    assert parse_ext_device_info(struct.pack("<HI", 0xC8, 99) + b"\x00\x50") == []
