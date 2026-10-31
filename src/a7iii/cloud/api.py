"""Cloud sync API (roadmap packages/07-cloud-sync-api).

A FastAPI router that syncs presets, LUTs, take metadata and NVRAM backups
between machines. Mount it in any FastAPI app, or run it standalone with
``a7iii cloud --db sync.sqlite``. Auth: a shared bearer token
(``A7III_SYNC_TOKEN``); put it behind TLS (a reverse proxy) in production.
"""

from __future__ import annotations

import os
import time

from fastapi import APIRouter, Depends, FastAPI, Header, HTTPException, Response
from pydantic import BaseModel

from .store import Store


class TakeIn(BaseModel):
    uid: str
    camera: str
    started_at: float
    duration_s: float | None = None
    start_tc: str | None = None
    preroll_s: float = 0.0
    settings: dict = {}
    rating: int = 0
    notes: str = ""
    media_path: str | None = None
    updated_at: float | None = None


class PresetIn(BaseModel):
    kind: str
    body: dict


class LutIn(BaseModel):
    cube: str


class BackupIn(BaseModel):
    backup_json: str


def make_router(store: Store, token: str | None = None) -> APIRouter:
    token = token if token is not None else os.environ.get("A7III_SYNC_TOKEN")

    def auth(authorization: str | None = Header(default=None)) -> None:
        if token and authorization != f"Bearer {token}":
            raise HTTPException(401, "missing or bad bearer token")

    r = APIRouter(dependencies=[Depends(auth)])

    @r.get("/health")
    def health():
        return {"ok": True, "time": time.time()}

    @r.get("/takes")
    def get_takes(since: float = 0.0):
        return store.takes(since)

    @r.put("/takes")
    def put_takes(takes: list[TakeIn]):
        for t in takes:
            d = t.model_dump()
            if d["updated_at"] is None:
                d["updated_at"] = time.time()
            store.upsert_take(d)
        return {"stored": len(takes)}

    @r.get("/presets")
    def get_presets(kind: str | None = None):
        return store.presets(kind)

    @r.put("/presets/{name}")
    def put_preset(name: str, p: PresetIn):
        store.put_preset(name, p.kind, p.body)
        return {"name": name}

    @r.get("/luts")
    def list_luts():
        return store.luts()

    @r.put("/luts/{name}")
    def put_lut(name: str, body: LutIn):
        try:
            return {"name": name, "sha256": store.put_lut(name, body.cube)}
        except ValueError as e:
            raise HTTPException(400, str(e))

    @r.get("/luts/{name}")
    def get_lut(name: str):
        row = store.lut(name)
        if row is None:
            raise HTTPException(404, "no such LUT")
        return Response(row["cube"], media_type="text/plain", headers={"X-SHA256": row["sha256"]})

    @r.get("/nvram")
    def list_backups(serial: str | None = None):
        return store.nvram_backups(serial)

    @r.put("/nvram")
    def put_backup(body: BackupIn):
        try:
            return {"sha256": store.put_nvram_backup(body.backup_json)}
        except Exception as e:  # bad JSON or a broken seal
            raise HTTPException(400, f"rejected backup: {e}")

    @r.get("/nvram/{sha256}")
    def get_backup(sha256: str):
        body = store.nvram_backup(sha256)
        if body is None:
            raise HTTPException(404, "no such backup")
        return Response(body, media_type="application/json")

    return r


def create_app(db_path: str = "a7iii_sync.sqlite", token: str | None = None) -> FastAPI:
    app = FastAPI(title="A7III Cloud Sync")
    app.include_router(make_router(Store(db_path), token), prefix="/v1")
    return app


def sync_takes(local: Store, client, since: float = 0.0, token: str | None = None) -> dict:
    """Two-way take sync with a server via an HTTP client (httpx.Client or TestClient)."""
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    pushed = local.takes(since)
    payload = [{k: v for k, v in t.items() if k in TakeIn.model_fields} for t in pushed]
    client.put("/v1/takes", json=payload, headers=headers).raise_for_status()
    remote = client.get("/v1/takes", params={"since": since}, headers=headers)
    remote.raise_for_status()
    for t in remote.json():
        t.pop("id", None)  # row ids are per-database; uid is the identity
        local.upsert_take(t)
    return {"pushed": len(pushed), "pulled": len(remote.json())}
