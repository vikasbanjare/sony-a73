import shutil
import subprocess
from pathlib import Path

import numpy as np
import pytest

from a7iii.optics.gyro import read_gcsv
from a7iii.optics.gyroshoe_host import GyroShoeError, GyroShoeLink, SimulatedGyroShoe
from a7iii.sim import HandheldMotion, SimulatedIMU

FIRMWARE = Path(__file__).resolve().parents[1] / "firmware" / "gyroshoe"


def test_protocol_against_simulated_device(tmp_path):
    clock = {"t": 10.0}
    motion = HandheldMotion(seed=3)
    dev = SimulatedGyroShoe(tmp_path / "sd", motion, SimulatedIMU(), lambda: clock["t"])
    link = GyroShoeLink(dev)
    link.start("A001C001", 1_700_000_000_000)
    assert link.status()["logging"]
    with pytest.raises(GyroShoeError):
        link.start("again", 0)
    clock["t"] = 11.0
    link.mark(1_700_000_001_000)
    clock["t"] = 12.0
    samples, dropped = link.stop()
    assert samples == 1000 and dropped == 0
    log = read_gcsv(tmp_path / "sd" / "A001C001.gcsv")
    yaw_rate, _ = motion.rates(log.t + 10.0)
    assert np.corrcoef(log.gyro[:, 0], yaw_rate)[0, 1] > 0.95
    marks = (tmp_path / "sd" / "A001C001.marks.csv").read_text().splitlines()
    assert marks[1] == "mark,1700000001000,1000000"
    with pytest.raises(ValueError):
        link.start("bad name", 0)


@pytest.mark.skipif(shutil.which("g++") is None, reason="needs g++")
def test_firmware_compiles_against_api_stubs():
    res = subprocess.run(
        ["g++", "-std=gnu++17", "-Wall", "-Wextra", "-Werror", "-fsyntax-only", "-x", "c++",
         "-I", str(FIRMWARE / "test_stubs"), str(FIRMWARE / "gyroshoe.ino")],
        capture_output=True, text=True,
    )
    assert res.returncode == 0, res.stderr


def test_firmware_and_python_agree_on_format():
    src = (FIRMWARE / "gyroshoe.ino").read_text()
    assert "GYRO_LSB_PER_DPS = 16.4f" in src and "ACCEL_LSB_PER_G = 4096.0f" in src
    assert 'println("version,1.3")' in src and "tscale,1e-06" in src
    for cmd in ("START ", "STOP", "MARK ", "STATUS"):
        assert f'"{cmd}' in src
