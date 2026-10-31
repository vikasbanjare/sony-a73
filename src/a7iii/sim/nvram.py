"""Simulated ILCE-7M3 NVRAM for exercising the service-mode tool end to end.

The image persists to a JSON file so ``a7iii nvram dump`` -> ``apply`` ->
``restore`` can run as separate commands, just like on hardware. It also
contains stand-in "factory calibration" properties so the tests can prove
the write gate never touches them.
"""

from __future__ import annotations

import json
from pathlib import Path

from ..nvram.registry import ID_MODEL_CODE, ID_MODEL_NAME, ID_SERIAL_NUMBER, LANGUAGE_FIRST, LANGUAGE_LAST
from ..nvram.service import FakeSenserBackend

# Not real addresses: placeholders standing in for sensor/IBIS calibration tables.
SIM_CALIBRATION_PROPS = {0x00E80000 + i: bytes([0xA5, i]) for i in range(8)}


def factory_image(serial: str = "3301234", japan_region: bool = True) -> dict[int, bytes]:
    props = {
        ID_MODEL_NAME: b"ILCE-7M3\0",
        ID_MODEL_CODE: b"\x01",
        ID_SERIAL_NUMBER: serial.encode() + b"\0",
        **SIM_CALIBRATION_PROPS,
    }
    for i, pid in enumerate(range(LANGUAGE_FIRST, LANGUAGE_LAST + 1)):
        # A J1 (Japan) body ships with only Japanese + English enabled.
        props[pid] = b"\x01" if (not japan_region or i < 2) else b"\x02"
    return props


class PersistentSimBackend(FakeSenserBackend):
    def __init__(self, image_path: str | Path, serial: str = "3301234"):
        self.image_path = Path(image_path)
        if self.image_path.exists():
            raw = json.loads(self.image_path.read_text())
            props = {int(k, 16): bytes.fromhex(v) for k, v in raw.items()}
        else:
            props = factory_image(serial)
        super().__init__(props)

    def sync_backup(self) -> None:
        super().sync_backup()
        self.save()

    def save(self) -> None:
        self.image_path.write_text(json.dumps({f"0x{k:08x}": v.hex() for k, v in sorted(self.props.items())}, indent=1))
