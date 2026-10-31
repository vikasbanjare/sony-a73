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
