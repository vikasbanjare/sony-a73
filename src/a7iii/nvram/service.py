"""Guarded service-mode NVRAM session (roadmap §3.2).

The low-level Senser transport is abstracted behind ``SenserBackend`` so
this module never talks USB directly. A production backend should wrap
Sony-PMCA-RE's ``SenserPlatformBackend`` per-property calls
(readBackup / writeBackup / setBackupProtection / syncBackup) - never the
bulk BACKUP_PDT_READ path (roadmap RSK-01).

Safety model:
1. Writes only to allowlisted IDs/values (``safety.validate_write``).
2. A sealed backup for *this* serial that contains every property being
   written must be supplied.
3. ``dry_run`` defaults to True and performs no writes at all.
4. Protection is re-enabled in ``finally`` even if a write fails, and each
   write is read back and verified before committing with sync.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, Protocol

from .backup import NvramBackup
from .registry import ID_MODEL_NAME, ID_SERIAL_NUMBER, IDENTITY_PROPS, TWEAKS
from .safety import UnsafeWriteError, is_writable, validate_write


class SenserBackend(Protocol):
    def read_backup(self, prop_id: int) -> bytes: ...
    def write_backup(self, prop_id: int, value: bytes) -> None: ...
    def set_backup_protection(self, enabled: bool) -> None: ...
    def sync_backup(self) -> None: ...


class VerificationError(RuntimeError):
    pass


def _text(raw: bytes) -> str:
    return raw.split(b"\0", 1)[0].decode("ascii", errors="replace").strip()


@dataclass
class PlannedWrite:
    prop_id: int
    old: bytes
    new: bytes

    @property
    def changes(self) -> bool:
        return self.old != self.new


@dataclass
class ApplyReport:
    dry_run: bool
    planned: list[PlannedWrite]
    written: list[int] = field(default_factory=list)


class NvramService:
    def __init__(self, backend: SenserBackend):
        self.b = backend

    def identify(self) -> tuple[str, str]:
        return _text(self.b.read_backup(ID_MODEL_NAME)), _text(self.b.read_backup(ID_SERIAL_NUMBER))

    def dump(self, prop_ids: Iterable[int] | None = None) -> NvramBackup:
        """Read-only dump of identity props plus every registered tweak prop."""
        model, serial = self.identify()
        ids = set(IDENTITY_PROPS)
        ids.update(prop_ids if prop_ids is not None else (p for t in TWEAKS.values() for p in t.prop_ids))
        return NvramBackup(model=model, serial=serial, props={pid: self.b.read_backup(pid) for pid in sorted(ids)})

    def plan(self, tweak_key: str) -> list[PlannedWrite]:
        tweak = TWEAKS[tweak_key]
        if not tweak.available or tweak.enable_value is None:
            raise UnsafeWriteError(f"tweak {tweak_key!r} has no verified property IDs for this model")
        return [PlannedWrite(pid, self.b.read_backup(pid), tweak.enable_value) for pid in tweak.prop_ids]

    def apply(self, writes: list[PlannedWrite], backup: NvramBackup, dry_run: bool = True) -> ApplyReport:
        model, serial = self.identify()
        if (backup.model, backup.serial) != (model, serial):
            raise UnsafeWriteError(f"backup is for {backup.model} #{backup.serial}, camera is {model} #{serial}")
        for w in writes:
            validate_write(w.prop_id, w.new)
            if w.prop_id not in backup.props:
                raise UnsafeWriteError(f"backup does not contain 0x{w.prop_id:08x}; take a fresh dump first")

        todo = [w for w in writes if w.changes]
        report = ApplyReport(dry_run=dry_run, planned=writes)
        if dry_run or not todo:
            return report

        self.b.set_backup_protection(False)
        try:
            for w in todo:
                self.b.write_backup(w.prop_id, w.new)
                if self.b.read_backup(w.prop_id) != w.new:
                    raise VerificationError(f"read-back mismatch on 0x{w.prop_id:08x}; not syncing")
                report.written.append(w.prop_id)
        finally:
            self.b.set_backup_protection(True)
        self.b.sync_backup()
        return report

    def restore(self, backup: NvramBackup, dry_run: bool = True) -> ApplyReport:
        """Write back original values for allowlisted props only."""
        writes = [
            PlannedWrite(pid, self.b.read_backup(pid), val)
            for pid, val in backup.props.items()
            if pid not in IDENTITY_PROPS and is_writable(pid)
        ]
        return self.apply(writes, backup, dry_run=dry_run)


class FakeSenserBackend:
    """In-memory backend for tests and dry rehearsals."""

    def __init__(self, props: dict[int, bytes]):
        self.props = dict(props)
        self.protected = True
        self.synced = 0
        self.log: list[tuple] = []

    def read_backup(self, prop_id: int) -> bytes:
        self.log.append(("read", prop_id))
        return self.props[prop_id]

    def write_backup(self, prop_id: int, value: bytes) -> None:
        self.log.append(("write", prop_id, value))
        if self.protected:
            raise PermissionError("backup protection enabled")
        self.props[prop_id] = bytes(value)

    def set_backup_protection(self, enabled: bool) -> None:
        self.log.append(("protect", enabled))
        self.protected = enabled

    def sync_backup(self) -> None:
        self.log.append(("sync",))
        self.synced += 1
