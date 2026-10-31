import json

import pytest
from fastapi.testclient import TestClient

from a7iii.cloud.api import create_app as create_cloud_app
from a7iii.cloud.api import sync_takes
from a7iii.cloud.store import Store
from a7iii.desk.app import build_sim_rig, create_app
from a7iii.nvram import FakeSenserBackend, NvramService
from a7iii.nvram.registry import ID_MODEL_CODE, ID_MODEL_NAME, ID_SERIAL_NUMBER


@pytest.fixture
def desk(tmp_path):
    rig = build_sim_rig("walking", media_dir=str(tmp_path / "takes"))
    with TestClient(create_app(rig, autorun=False)) as client:
        yield client, rig


def test_index_and_state(desk):
    client, _ = desk
    assert "A7III CONTROL DESK" in client.get("/").text
    st = client.get("/api/state").json()
    assert st["settings"]["fps"] == 23.976 and len(st["zones"]) == 10


def test_settings_drive_camera_over_ptp(desk):
    client, rig = desk
    r = client.post("/api/settings", json={"fps": 25, "angle": 180, "mains_hz": 50, "gamma": "S-Log3", "ei_base": "high"})
    assert r.status_code == 200
    assert str(rig.sim.state.shutter) == "1/50" and rig.sim.state.iso == 5000
    assert rig.sim.conversion_gain == "HCG"
    assert client.post("/api/settings", json={"ei": 99999}).status_code == 400


def test_tick_views_scopes_and_lut(desk):
    client, _ = desk
    for _ in range(3):
        t = client.post("/api/tick").json()
    assert t["shutter"] == "1/50" and "zones" in t and t["recording_iso"] == 100
    for view in ("normal", "falsecolor", "ei", "focusmap"):
        r = client.get(f"/api/view/{view}.jpg")
        assert r.status_code == 200 and r.content[:2] == b"\xff\xd8", view
    for kind in ("waveform", "vectorscope", "parade", "histogram"):
        r = client.get(f"/api/scope/{kind}.png")
        assert r.status_code == 200 and r.content[:4] == b"\x89PNG", kind
    cube = client.get("/api/lut/monitor.cube", params={"ei": 200, "size": 9}).text
    assert "LUT_3D_SIZE 9" in cube


def test_preroll_take_is_logged_and_saved(desk, tmp_path):
    client, rig = desk
    for _ in range(12):
        client.post("/api/tick")
    assert client.post("/api/record/start", params={"preroll": True}).status_code == 200
    assert rig.sim.state.recording  # movie_record pressed over PTP
    assert client.post("/api/record/start").status_code == 409
    for _ in range(6):
        client.post("/api/tick")
    rec = client.post("/api/record/stop").json()
    assert rec["frames"] == 18 and rec["preroll_frames"] == 12 and rec["preroll_s"] > 0.4
    assert not rig.sim.state.recording
    takes = client.get("/api/takes").json()
    assert len(takes) == 1 and takes[0]["settings"]["shutter"] == "1/50"
    assert len(list((tmp_path / "takes" / takes[0]["uid"]).glob("*.jpg"))) == 18


def test_ai_af_and_aperture_guard_events(desk):
    client, rig = desk
    client.post("/api/settings", json={"ai_af": True})
    for _ in range(10):
        t = client.post("/api/tick").json()
    assert t["af"]["status"] in ("sent", "rate limited", "within deadband")
    assert t["pdaf_ok"] is True
    rig.driver.set_prop("f_number", 1600)
    for _ in range(4):
        t = client.post("/api/tick").json()
    assert t["pdaf_ok"] is False and "PDAF DISABLED" in t["pdaf_message"]
    assert any(e["kind"] == "af_guard" for e in client.get("/api/events").json())


def test_af_point_and_rack(desk):
    client, rig = desk
    assert client.post("/api/af/point", json={"u": 0.25, "v": 0.5}).status_code == 200
    assert rig.sim.state.af_point == pytest.approx((0.25, 0.5), abs=1e-3)
    rig.driver.set_prop("focus_mode", 1)
    before = rig.sim.state.focus_step
    client.post("/api/focus/rack", json={"steps": -100, "duration_s": 0.5})
    assert rig.sim.state.focus_step == before - 100


def test_websocket_streams_video_and_telemetry(tmp_path):
    rig = build_sim_rig("wall", media_dir=str(tmp_path))
    with TestClient(create_app(rig, autorun=True, loop_fps=30)) as client:
        with client.websocket_connect("/ws") as ws:
            got_jpeg = got_tel = False
            for _ in range(6):
                msg = ws.receive()
                if msg.get("bytes"):
                    got_jpeg = msg["bytes"][:2] == b"\xff\xd8"
                elif msg.get("text"):
                    got_tel = "telemetry" in json.loads(msg["text"])
                if got_jpeg and got_tel:
                    break
            assert got_jpeg and got_tel


def test_cloud_sync_between_two_desks(tmp_path):
    server = TestClient(create_cloud_app(str(tmp_path / "cloud.sqlite"), token="s3cret"))
    assert server.get("/v1/health").status_code == 401
    auth = {"Authorization": "Bearer s3cret"}
    a, b = Store(), Store()
    a.upsert_take({"uid": "A-1", "camera": "ILCE-7M3", "started_at": 1.0, "settings": {"fps": 24}, "updated_at": 10.0})
    b.upsert_take({"uid": "B-1", "camera": "ILCE-7M3", "started_at": 2.0, "settings": {"fps": 25}, "updated_at": 11.0})
    sync_takes(a, server, token="s3cret")
    sync_takes(b, server, token="s3cret")
    sync_takes(a, server, token="s3cret")
    assert {t["uid"] for t in a.takes()} == {t["uid"] for t in b.takes()} == {"A-1", "B-1"}
    # stale updates lose
    b.upsert_take({"uid": "A-1", "camera": "ILCE-7M3", "started_at": 1.0, "settings": {}, "notes": "old", "updated_at": 5.0})
    assert next(t for t in b.takes() if t["uid"] == "A-1")["notes"] == ""

    cube = "LUT_3D_SIZE 2\n" + "0 0 0\n" * 8
    assert server.put("/v1/luts/match", json={"cube": cube}, headers=auth).status_code == 200
    assert server.get("/v1/luts/match", headers=auth).text == cube
    assert server.put("/v1/presets/HLG-Cine", json={"kind": "picture_profile", "body": {"gamma": "HLG3"}}, headers=auth).status_code == 200
    assert server.get("/v1/presets", headers=auth).json()[0]["body"]["gamma"] == "HLG3"

    be = FakeSenserBackend({ID_MODEL_NAME: b"ILCE-7M3\0", ID_MODEL_CODE: b"\x01", ID_SERIAL_NUMBER: b"42\0"})
    backup = NvramService(be).dump(prop_ids=[])
    sha = server.put("/v1/nvram", json={"backup_json": backup.to_json()}, headers=auth).json()["sha256"]
    assert sha == backup.sha256
    tampered = backup.to_json().replace('"42"', '"43"')
    assert server.put("/v1/nvram", json={"backup_json": tampered}, headers=auth).status_code == 400
    assert server.get(f"/v1/nvram/{sha}", headers=auth).json()["serial"] == "42"
