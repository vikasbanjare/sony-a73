"""Write gate for NVRAM properties (roadmap RSK-02). Deny by default."""

from __future__ import annotations

from .registry import WRITABLE


class UnsafeWriteError(PermissionError):
    pass


def validate_write(prop_id: int, value: bytes) -> None:
    allowed = WRITABLE.get(prop_id)
    if allowed is None:
        raise UnsafeWriteError(f"property 0x{prop_id:08x} is not on the write allowlist")
    if bytes(value) not in allowed:
        raise UnsafeWriteError(
            f"value {bytes(value).hex()} not permitted for 0x{prop_id:08x} (allowed: {[v.hex() for v in allowed]})"
        )


def is_writable(prop_id: int) -> bool:
    return prop_id in WRITABLE
