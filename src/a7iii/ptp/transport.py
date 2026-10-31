"""Byte transports for PTP: a pyusb bulk transport and an in-memory mock."""

from __future__ import annotations

from collections import deque
from typing import Protocol

from .codes import SONY_VID


class Transport(Protocol):
    def write(self, data: bytes) -> None: ...
    def read(self, timeout_ms: int = 5000) -> bytes: ...
    def close(self) -> None: ...


class MockTransport:
    """Records writes and replays queued reads. Used by the unit tests."""

    def __init__(self) -> None:
        self.written: list[bytes] = []
        self.to_read: deque[bytes] = deque()

    def queue(self, *chunks: bytes) -> None:
        self.to_read.extend(chunks)

    def write(self, data: bytes) -> None:
        self.written.append(bytes(data))

    def read(self, timeout_ms: int = 5000) -> bytes:
        if not self.to_read:
            raise TimeoutError("mock transport has nothing queued")
        return self.to_read.popleft()

    def close(self) -> None:
        pass


class UsbTransport:
    """PTP bulk transport using pyusb (``pip install pyusb`` + libusb).

    The camera must be set to Setup > USB Connection: PC Remote.
    Untested against hardware in CI - see README "Hardware status".
    """

    PTP_INTERFACE_CLASS = 6  # Still Image

    def __init__(self, vid: int = SONY_VID, pid: int | None = None, max_packet: int = 512 * 1024):
        import usb.core
        import usb.util

        matcher = {"idVendor": vid} if pid is None else {"idVendor": vid, "idProduct": pid}
        dev = usb.core.find(**matcher)
        if dev is None:
            raise ConnectionError("no Sony camera found - is USB Connection set to 'PC Remote'?")
        cfg = dev.get_active_configuration()
        intf = usb.util.find_descriptor(cfg, bInterfaceClass=self.PTP_INTERFACE_CLASS)
        if intf is None:
            raise ConnectionError("camera exposes no PTP interface in its current USB mode")
        try:
            if dev.is_kernel_driver_active(intf.bInterfaceNumber):
                dev.detach_kernel_driver(intf.bInterfaceNumber)
        except (NotImplementedError, usb.core.USBError):
            pass
        usb.util.claim_interface(dev, intf)

        def ep(direction, kind):
            return usb.util.find_descriptor(
                intf,
                custom_match=lambda e: usb.util.endpoint_direction(e.bEndpointAddress) == direction
                and usb.util.endpoint_type(e.bmAttributes) == kind,
            )

        self._dev, self._intf = dev, intf
        self._out = ep(usb.util.ENDPOINT_OUT, usb.util.ENDPOINT_TYPE_BULK)
        self._in = ep(usb.util.ENDPOINT_IN, usb.util.ENDPOINT_TYPE_BULK)
        self._max = max_packet
        self._recover_if_stalled()

    def _recover_if_stalled(self) -> None:
        """A run that died mid-transfer leaves the pipe stuck, seen two ways on a real
        ILCE-7M3: halted endpoint (status 0x2009, Errno 32 on write) or an unread
        reply still queued (status OK, Errno 60 on write). Fix with PTP class
        requests and reads only - no camera settings are touched."""
        import struct
        import time

        import usb.core

        ifn = self._intf.bInterfaceNumber
        status = bytes(self._dev.ctrl_transfer(0xA1, 0x67, 0, ifn, 64))  # Get Device Status
        if len(status) < 4 or struct.unpack_from("<H", status, 2)[0] != 0x2001:
            for e in (self._out, self._in):
                e.clear_halt()
            self._dev.ctrl_transfer(0x21, 0x66, 0, ifn, None)  # Device Reset Request
            time.sleep(0.5)
        for _ in range(64):  # ponytail: bounded drain, ~32 MB max of stale data
            try:
                self._in.read(self._max, timeout=200)
            except usb.core.USBTimeoutError:
                break

    def write(self, data: bytes) -> None:
        self._out.write(data)

    def read(self, timeout_ms: int = 5000) -> bytes:
        import struct

        first = bytes(self._in.read(self._max, timeout=timeout_ms))
        if len(first) < 4:
            return first
        total = struct.unpack_from("<I", first)[0]
        buf = bytearray(first)
        while len(buf) < total:
            buf += bytes(self._in.read(self._max, timeout=timeout_ms))
        return bytes(buf)

    def close(self) -> None:
        import usb.util

        usb.util.release_interface(self._dev, self._intf)
        usb.util.dispose_resources(self._dev)
