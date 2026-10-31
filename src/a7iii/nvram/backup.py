"""SHA-256-sealed NVRAM property backups (roadmap §3.2 step 1)."""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass, field
from pathlib import Path


class BackupIntegrityError(ValueError):
    pass


def _digest(serial: str, model: str, props: dict[int, bytes]) -> str:
    h = hashlib.sha256()
    h.update(f"{model}\0{serial}\0".encode())
    for pid in sorted(props):
        h.update(pid.to_bytes(4, "big"))
        h.update(len(props[pid]).to_bytes(4, "big"))
        h.update(props[pid])
    return h.hexdigest()


@dataclass
class NvramBackup:
    model: str
    serial: str
    props: dict[int, bytes]
    created: float = field(default_factory=time.time)

    @property
    def sha256(self) -> str:
        return _digest(self.serial, self.model, self.props)

    def to_json(self) -> str:
        return json.dumps(
            {
                "format": "a7iii-nvram-backup/1",
                "model": self.model,
                "serial": self.serial,
                "created": self.created,
                "props": {f"0x{pid:08x}": val.hex() for pid, val in sorted(self.props.items())},
                "sha256": self.sha256,
            },
            indent=2,
        )

    def save(self, directory: str | Path) -> Path:
        path = Path(directory) / f"NVRAM_BACKUP_{self.serial}_{int(self.created)}.json"
        path.write_text(self.to_json())
        return path

    @classmethod
    def from_json(cls, text: str) -> "NvramBackup":
        raw = json.loads(text)
        if raw.get("format") != "a7iii-nvram-backup/1":
            raise BackupIntegrityError("unrecognised backup format")
        backup = cls(
            model=raw["model"],
            serial=raw["serial"],
            props={int(k, 16): bytes.fromhex(v) for k, v in raw["props"].items()},
            created=raw["created"],
        )
        if backup.sha256 != raw.get("sha256"):
            raise BackupIntegrityError("backup checksum mismatch - file was modified or corrupted")
        return backup

    @classmethod
    def load(cls, path: str | Path) -> "NvramBackup":
        return cls.from_json(Path(path).read_text())
