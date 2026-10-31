"""Registry of NVRAM backup properties this project is willing to touch.

Everything not listed here is READ-ONLY in code (roadmap RSK-02). Entries
with ``prop_ids`` empty are known targets whose IDs have not been verified
for ILCE-7M3 FW 4.04; they cannot be written until a verified ID is added
here in a reviewed change.
"""

from __future__ import annotations

from dataclasses import dataclass

# Read-only identification properties (roadmap §3.2).
ID_MODEL_NAME = 0x003E0005
ID_MODEL_CODE = 0x00E70000
ID_SERIAL_NUMBER = 0x00E70003

LANGUAGE_FIRST = 0x010D008F
LANGUAGE_LAST = 0x010D00B1
LANGUAGE_ENABLED = b"\x01"
LANGUAGE_DISABLED = b"\x02"


@dataclass(frozen=True)
class Tweak:
    key: str
    description: str
    prop_ids: tuple[int, ...]
    allowed_values: tuple[bytes, ...]
    enable_value: bytes | None

    @property
    def available(self) -> bool:
        return bool(self.prop_ids)


TWEAKS: dict[str, Tweak] = {
    t.key: t
    for t in [
        Tweak(
            key="languages",
            description="Enable all menu languages (bitmap 0x010d008f..0x010d00b1)",
            prop_ids=tuple(range(LANGUAGE_FIRST, LANGUAGE_LAST + 1)),
            allowed_values=(LANGUAGE_ENABLED, LANGUAGE_DISABLED),
            enable_value=LANGUAGE_ENABLED,
        ),
        Tweak(
            key="rec_limit",
            description="Disable 29m59s movie recording limit",
            prop_ids=(),  # ID not yet verified for ILCE-7M3 - intentionally unwritable
            allowed_values=(),
            enable_value=None,
        ),
        Tweak(
            key="pal_ntsc_warning",
            description="Suppress PAL/NTSC switch warning",
            prop_ids=(),  # ID not yet verified for ILCE-7M3 - intentionally unwritable
            allowed_values=(),
            enable_value=None,
        ),
    ]
}

WRITABLE: dict[int, tuple[bytes, ...]] = {
    pid: t.allowed_values for t in TWEAKS.values() for pid in t.prop_ids
}

IDENTITY_PROPS = (ID_MODEL_NAME, ID_MODEL_CODE, ID_SERIAL_NUMBER)
