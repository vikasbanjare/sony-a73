import numpy as np
import pytest

from a7iii.audio import Timecode, decode_ltc, find_offset, generate_ltc, read_wav, repair_clipping, shift_signal, write_bwf
from a7iii.audio.ltc import decode_frame_bits, encode_frame_bits


def test_timecode_round_trip_non_drop():
    tc = Timecode.parse("01:02:03:04", 25)
    assert Timecode.from_frames(tc.to_frames(), 25) == tc
    assert str(tc + 21) == "01:02:04:00"


def test_drop_frame_skips_frames_0_and_1_each_minute():
    tc = Timecode.parse("00:00:59;29", 30)
    assert str(tc + 1) == "00:01:00;02"
    assert str(Timecode.parse("00:09:59;29", 30) + 1) == "00:10:00;00"  # every 10th minute keeps them
    for n in range(0, 200_000, 997):
        assert Timecode.from_frames(n, 30, True).to_frames() == n
    with pytest.raises(ValueError):
        Timecode(0, 1, 0, 0, 30, drop_frame=True)
    # one hour of 29.97 DF is 107892 frames -> ~3600.0 real seconds
    assert Timecode.parse("01:00:00;00", 30).seconds_since_midnight(30000 / 1001) == pytest.approx(3600, abs=0.01)


def test_ltc_bits_round_trip():
    tc = Timecode.parse("23:59:58;29", 30)
    bits = encode_frame_bits(tc, user_bits=0xDEADBEEF)
    assert bits[64:] == [0, 0, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 0, 1]
    assert (80 - sum(bits)) % 2 == 0  # polarity correction
    back, user = decode_frame_bits(bits, 30)
    assert back == tc and user == 0xDEADBEEF


@pytest.mark.parametrize("fps,actual", [(24, 24000 / 1001), (25, 25.0), (30, 30.0)])
def test_ltc_audio_round_trip(fps, actual):
    start = Timecode.parse("10:00:00:00", fps)
    audio = generate_ltc(start, 30, actual_fps=actual)
    rng = np.random.default_rng(0)
    noisy = 0.3 * audio + rng.normal(0, 0.01, audio.shape)
    frames = decode_ltc(noisy, fps)
    assert len(frames) >= 28
    first = frames[0]
    k = first.timecode.to_frames() - start.to_frames()
    assert first.sample == pytest.approx(k * 48000 / actual, abs=3)
    tcs = [f.timecode.to_frames() for f in frames]
    assert np.all(np.diff(tcs) == 1)


def test_audio_sync_and_mux(tmp_path):
    rng = np.random.default_rng(1)
    sr = 48000
    speech = np.convolve(rng.normal(0, 1, sr * 2), np.ones(30) / 30, mode="same") * 0.3
    camera = shift_signal(speech, 0, len(speech)) + rng.normal(0, 0.01, len(speech))
    recorder = shift_signal(speech, -1234, len(speech) + 2000) + rng.normal(0, 0.01, len(speech) + 2000)
    off = find_offset(camera, recorder, max_lag=5000)
    assert off == 1234
    aligned = shift_signal(recorder, off, len(camera))
    assert np.corrcoef(aligned[2000:-2000], camera[2000:-2000])[0, 1] > 0.9

    start = Timecode.parse("12:00:00:00", 25)
    path = write_bwf(tmp_path / "take.wav", [camera, camera, aligned, aligned * 0.25], sr, 24, start=start)
    data, rate, info = read_wav(path)
    assert data.shape == (len(camera), 4) and rate == sr
    assert info["time_reference"] == 12 * 3600 * sr
    np.testing.assert_allclose(data[:, 0], np.clip(camera, -1, 1), atol=2e-6)
    f32, _, _ = read_wav(write_bwf(tmp_path / "f.wav", [camera], sr, 32))
    np.testing.assert_allclose(f32[:, 0], camera, atol=1e-6)


def test_safety_track_repairs_clipping():
    t = np.arange(4800) / 48000
    clean = 1.6 * np.sin(2 * np.pi * 220 * t) * np.exp(-((t - 0.05) / 0.02) ** 2)  # a shout
    primary = np.clip(clean, -1, 1)
    safety = clean * 10 ** (-12 / 20)
    fixed, n = repair_clipping(primary, safety, -12)
    assert n > 0
    assert np.max(np.abs(fixed - clean)) < 0.02
    same, n0 = repair_clipping(primary * 0.5, safety, -12)
    assert n0 == 0 and np.array_equal(same, primary * 0.5)
