import math

import numpy as np
import pytest

from a7iii.optics.gyro import GcsvLog, bmi270_scales, estimate_offset, read_gcsv, write_gcsv


def test_bmi270_scales():
    g, a = bmi270_scales(2000, 8)
    assert g == pytest.approx(math.radians(1 / 16.4))
    assert a == 1 / 4096


def test_gcsv_round_trip(tmp_path):
    rng = np.random.default_rng(0)
    t = np.arange(500) / 500.0
    gyro = rng.normal(0, 0.5, (500, 3))
    accel = rng.normal(0, 1, (500, 3))
    path = write_gcsv(tmp_path / "take.gcsv", GcsvLog(t, gyro, accel, orientation="YxZ"), readout_mode="s35_4k_24p")
    text = path.read_text()
    assert text.startswith("GYROFLOW IMU LOG\nversion,1.3")
    assert "frame_readout_time,13.80" in text
    log = read_gcsv(path)
    gscale, ascale = bmi270_scales()
    np.testing.assert_allclose(log.t, t, atol=1e-6)
    np.testing.assert_allclose(log.gyro, gyro, atol=gscale / 2 + 1e-12)
    np.testing.assert_allclose(log.accel, accel, atol=ascale / 2 + 1e-12)
    assert log.orientation == "YxZ"
    assert log.sample_rate == pytest.approx(500)


def test_read_rejects_other_files(tmp_path):
    p = tmp_path / "x.csv"
    p.write_text("a,b\n1,2\n")
    with pytest.raises(ValueError):
        read_gcsv(p)


def test_offset_estimation():
    rng = np.random.default_rng(1)
    # bursty camera motion
    t_imu = np.arange(0, 20, 1 / 500)
    motion = np.convolve(rng.random(t_imu.size) ** 8, np.ones(100) / 100, mode="same")
    true_offset = 0.37  # IMU clock is 0.37 s behind video
    t_video = np.arange(1, 19, 1 / 24)
    video_signal = np.interp(t_video, t_imu + true_offset, motion) + rng.normal(0, 0.001, t_video.size)
    est = estimate_offset(t_imu, motion, t_video, video_signal)
    assert est == pytest.approx(true_offset, abs=0.01)
