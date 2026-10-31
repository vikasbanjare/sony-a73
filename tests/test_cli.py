from a7iii.cli import main


def test_cli_commands_run(capsys):
    assert main(["shutter", "--fps", "23.976", "--mains", "50"]) == 0
    assert "1/50" in capsys.readouterr().out
    assert main(["iso", "slog3", "--need", "3200"]) == 0
    assert "ISO 5000" in capsys.readouterr().out
    assert main(["ei", "slog3", "1600"]) == 0
    assert main(["dof", "--focal", "50", "--f-number", "2", "--distance", "3"]) == 0
    assert main(["bracket", "--focal", "90", "--f-number", "8", "--near", "0.3", "--far", "0.5"]) == 0
    assert main(["af-guard", "16"]) == 2
    assert main(["profiles", "A7III-HLG-Cine"]) == 0
    assert main(["readout"]) == 0
    capsys.readouterr()
    assert main(["ei", "slog3", "12800"]) == 1


def test_cli_match(tmp_path, capsys):
    import numpy as np

    from a7iii.color.transfer import encode

    rng = np.random.default_rng(0)
    target_lin = rng.uniform(0.03, 0.7, (24, 3))
    source_lin = target_lin @ np.array([[1.1, -0.05, -0.05], [0.0, 0.95, 0.05], [0.02, -0.02, 1.0]]).T
    np.savetxt(tmp_path / "a.csv", encode("hlg", source_lin), delimiter=",")
    np.savetxt(tmp_path / "b.csv", encode("slog3", target_lin), delimiter=",")
    out = tmp_path / "m.cube"
    assert main(["match", "--source", str(tmp_path / "a.csv"), "--target", str(tmp_path / "b.csv"),
                 "--size", "17", "--out", str(out)]) == 0
    assert out.exists() and out.with_suffix(".dctl").exists()
    assert "final mean" in capsys.readouterr().out


def test_cli_offload(tmp_path, capsys):
    (tmp_path / "card").mkdir()
    (tmp_path / "card" / "a.MP4").write_bytes(b"x" * 100)
    args = ["offload", str(tmp_path / "card"), str(tmp_path / "d1"), str(tmp_path / "d2"), "--algorithm", "sha256", "--quiet"]
    assert main(args) == 0
    assert "2 copies made" in capsys.readouterr().out
    assert main(args) == 0
    assert "2 already present" in capsys.readouterr().out


def test_cli_nvram_rehearsal(tmp_path, capsys):
    img = str(tmp_path / "img.json")
    assert main(["nvram", "tweaks"]) == 0
    assert main(["nvram", "dump", "--sim", img, "--out", str(tmp_path)]) == 0
    backup = str(next(tmp_path.glob("NVRAM_BACKUP_*.json")))
    assert main(["nvram", "apply", "languages", "--sim", img, "--backup", backup]) == 0
    assert "dry run" in capsys.readouterr().out
    assert main(["nvram", "apply", "languages", "--sim", img, "--backup", backup, "--yes"]) == 0
    assert "wrote and verified 33" in capsys.readouterr().out
    assert main(["nvram", "apply", "rec_limit", "--sim", img, "--backup", backup, "--yes"]) == 1
    assert "no verified property IDs" in capsys.readouterr().err
    assert main(["nvram", "restore", "--sim", img, "--backup", backup, "--yes"]) == 0
    import json
    image = json.loads(open(img).read())
    assert image["0x010d00b1"] == "02" and image["0x00e80000"] == "a500"  # restored; calibration untouched
