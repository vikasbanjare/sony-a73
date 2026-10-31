"""SQLite-backed store shared by the Control Desk (shot log) and the cloud sync API."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
import time
from pathlib import Path

SCHEMA = (Path(__file__).with_name("schema.sql")).read_text()


class Store:
    def __init__(self, path: str | Path = ":memory:"):
        self.path = str(path)
        self._lock = threading.Lock()
        self.db = sqlite3.connect(self.path, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.executescript(SCHEMA)

    def _exec(self, sql: str, args: tuple = ()) -> sqlite3.Cursor:
        with self._lock:
            cur = self.db.execute(sql, args)
            self.db.commit()
            return cur

    def _all(self, sql: str, args: tuple = ()) -> list[dict]:
        with self._lock:
            return [dict(r) for r in self.db.execute(sql, args).fetchall()]

    # --- shoots & takes ---------------------------------------------------------

    def create_shoot(self, name: str, notes: str = "") -> int:
        return self._exec("INSERT INTO shoots(name, created_at, notes) VALUES (?, ?, ?)", (name, time.time(), notes)).lastrowid

    def upsert_take(self, take: dict) -> None:
        """Insert or update by ``uid``; last writer wins on ``updated_at``."""
        t = {k: v for k, v in dict(take).items() if v is not None}
        t.setdefault("updated_at", time.time())
        t.setdefault("preroll_s", 0.0)
        t.setdefault("rating", 0)
        t.setdefault("notes", "")
        t.setdefault("settings_json", json.dumps(t.pop("settings", {})))
        cols = ["uid", "shoot_id", "camera", "started_at", "duration_s", "start_tc", "preroll_s",
                "settings_json", "rating", "notes", "media_path", "updated_at"]
        vals = tuple(t.get(c) for c in cols)
        existing = self._all("SELECT updated_at FROM takes WHERE uid = ?", (t["uid"],))
        if existing and existing[0]["updated_at"] > t["updated_at"]:
            return  # stale update
        self._exec(
            f"INSERT INTO takes({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))}) "
            f"ON CONFLICT(uid) DO UPDATE SET {', '.join(f'{c}=excluded.{c}' for c in cols[1:])}",
            vals,
        )

    def takes(self, since: float = 0.0) -> list[dict]:
        rows = self._all("SELECT * FROM takes WHERE updated_at > ? ORDER BY started_at", (since,))
        for r in rows:
            r["settings"] = json.loads(r.pop("settings_json"))
        return rows

    def log_event(self, kind: str, payload: dict, take_uid: str | None = None, t: float | None = None) -> None:
        self._exec("INSERT INTO events(take_uid, t, kind, payload) VALUES (?, ?, ?, ?)",
                   (take_uid, t if t is not None else time.time(), kind, json.dumps(payload)))

    def events(self, take_uid: str | None = None) -> list[dict]:
        if take_uid is None:
            return self._all("SELECT * FROM events ORDER BY t")
        return self._all("SELECT * FROM events WHERE take_uid = ? ORDER BY t", (take_uid,))

    # --- presets, LUTs, NVRAM backups -------------------------------------------

    def put_preset(self, name: str, kind: str, body: dict) -> None:
        self._exec("INSERT INTO presets(name, kind, body_json, updated_at) VALUES (?, ?, ?, ?) "
                   "ON CONFLICT(name) DO UPDATE SET kind=excluded.kind, body_json=excluded.body_json, "
                   "updated_at=excluded.updated_at", (name, kind, json.dumps(body), time.time()))

    def presets(self, kind: str | None = None) -> list[dict]:
        rows = self._all("SELECT * FROM presets" + (" WHERE kind = ?" if kind else ""), (kind,) if kind else ())
        for r in rows:
            r["body"] = json.loads(r.pop("body_json"))
        return rows

    def put_lut(self, name: str, cube_text: str) -> str:
        size = next((int(line.split()[1]) for line in cube_text.splitlines() if line.startswith("LUT_3D_SIZE")), 0)
        if not size:
            raise ValueError("not a 3D .cube file")
        digest = hashlib.sha256(cube_text.encode()).hexdigest()
        self._exec("INSERT INTO luts(name, size, sha256, cube, updated_at) VALUES (?, ?, ?, ?, ?) "
                   "ON CONFLICT(name) DO UPDATE SET size=excluded.size, sha256=excluded.sha256, cube=excluded.cube, "
                   "updated_at=excluded.updated_at", (name, size, digest, cube_text, time.time()))
        return digest

    def lut(self, name: str) -> dict | None:
        rows = self._all("SELECT * FROM luts WHERE name = ?", (name,))
        return rows[0] if rows else None

    def luts(self) -> list[dict]:
        return self._all("SELECT name, size, sha256, updated_at FROM luts ORDER BY name")

    def put_nvram_backup(self, backup_json: str) -> str:
        from ..nvram.backup import NvramBackup

        backup = NvramBackup.from_json(backup_json)  # verifies the seal
        self._exec("INSERT OR IGNORE INTO nvram_backups(sha256, serial, model, body_json, created_at) VALUES (?, ?, ?, ?, ?)",
                   (backup.sha256, backup.serial, backup.model, backup_json, backup.created))
        return backup.sha256

    def nvram_backups(self, serial: str | None = None) -> list[dict]:
        q = "SELECT sha256, serial, model, created_at FROM nvram_backups"
        return self._all(q + (" WHERE serial = ?" if serial else "") + " ORDER BY created_at", (serial,) if serial else ())

    def nvram_backup(self, sha256: str) -> str | None:
        rows = self._all("SELECT body_json FROM nvram_backups WHERE sha256 = ?", (sha256,))
        return rows[0]["body_json"] if rows else None
