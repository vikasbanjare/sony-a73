import json

import pytest

from a7iii.ingest import offload, verify_manifest


@pytest.fixture
def card(tmp_path):
    src = tmp_path / "card"
    clip = src / "PRIVATE" / "M4ROOT" / "CLIP"
    clip.mkdir(parents=True)
    (clip / "C0001.MP4").write_bytes(b"\x00" * 10_000 + b"video")
    (clip / "C0001M01.XML").write_text("<meta/>")
    (src / "DCIM").mkdir()
    (src / "DCIM" / "DSC00001.ARW").write_bytes(b"raw" * 1000)
    (src / ".DS_Store").write_bytes(b"junk")
    return src


def test_offload_to_two_destinations(card, tmp_path):
    a, b = tmp_path / "ssd_a", tmp_path / "ssd_b"
    rep = offload(card, [a, b], algorithm="sha256")
    assert rep.ok and len(rep.files) == 3
    for d in (a, b):
        assert (d / "PRIVATE/M4ROOT/CLIP/C0001.MP4").read_bytes().endswith(b"video")
        assert not list(d.rglob("*.partial"))
        assert not (d / ".DS_Store").exists()
    assert all(verify_manifest(m) == [] for m in rep.manifests)


def test_resume_skips_identical_and_flags_conflicts(card, tmp_path):
    a = tmp_path / "a"
    offload(card, [a], algorithm="sha256")
    (a / "DCIM/DSC00001.ARW").write_bytes(b"something else")
    rep = offload(card, [a], algorithm="sha256")
    statuses = {f.rel: f.status[str(a)] for f in rep.files}
    assert statuses["PRIVATE/M4ROOT/CLIP/C0001.MP4"] == "skipped"
    assert statuses["DCIM/DSC00001.ARW"].startswith("conflict")
    assert not rep.ok and rep.problems()
    assert (a / "DCIM/DSC00001.ARW").read_bytes() == b"something else"  # never overwritten


def test_manifest_detects_later_corruption(card, tmp_path):
    a = tmp_path / "a"
    rep = offload(card, [a], algorithm="sha256")
    (a / "PRIVATE/M4ROOT/CLIP/C0001M01.XML").write_text("<tampered/>")
    assert verify_manifest(rep.manifests[0]) == ["hash mismatch: PRIVATE/M4ROOT/CLIP/C0001M01.XML"]
    data = json.loads(rep.manifests[0].read_text())
    assert data["algorithm"] == "sha256" and len(data["files"]) == 3


def test_rejects_destination_inside_source(card):
    with pytest.raises(ValueError):
        offload(card, [card / "backup"])
