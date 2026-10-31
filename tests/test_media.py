import numpy as np
import pytest

from a7iii.media import encode_frames, ffmpeg_available, make_proxies, probe

pytestmark = pytest.mark.skipif(not ffmpeg_available(), reason="ffmpeg not installed")


@pytest.mark.parametrize("codec,name", [("prores", "prores"), ("h264", "h264"), ("h265", "hevc")])
def test_encode_frames(tmp_path, codec, name):
    frames = [np.full((64, 96, 3), i / 24) for i in range(24)]
    out = encode_frames(frames, 23.976, tmp_path / f"take.{'mov' if codec == 'prores' else 'mp4'}", codec,
                        timecode="01:00:00:00")
    info = probe(out)
    v = info["streams"][0]
    assert v["codec_name"] == name and v["width"] == 96 and int(v["nb_frames"]) == 24
    assert v["r_frame_rate"] == "24000/1001"


def test_proxies(tmp_path):
    src = tmp_path / "card" / "PRIVATE" / "M4ROOT" / "CLIP"
    src.mkdir(parents=True)
    encode_frames([np.zeros((240, 320, 3))] * 10, 25, src / "C0001.MP4", "h264")
    made = make_proxies(tmp_path / "card", tmp_path / "proxies", height=120)
    assert len(made) == 1 and probe(made[0])["streams"][0]["height"] == 120


def test_desk_take_encoded_to_prores(tmp_path):
    from fastapi.testclient import TestClient

    from a7iii.desk.app import build_sim_rig, create_app

    rig = build_sim_rig("wall", media_dir=str(tmp_path))
    with TestClient(create_app(rig, autorun=False)) as client:
        client.post("/api/settings", json={"take_codec": "prores"})
        for _ in range(5):
            client.post("/api/tick")
        client.post("/api/record/start", params={"preroll": True})
        for _ in range(5):
            client.post("/api/tick")
        rec = client.post("/api/record/stop").json()
    v = probe(rec["media_path"])["streams"][0]
    assert v["codec_name"] == "prores" and int(v["nb_frames"]) == 10
