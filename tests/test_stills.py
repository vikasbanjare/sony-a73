import numpy as np
import pytest
from scipy.ndimage import gaussian_filter, shift

from a7iii.stills import (
    MotionTrigger,
    PreCaptureBurst,
    bilinear_upsample,
    focus_stack,
    iterative_backprojection,
    phase_correlation,
    shift_and_add,
    stack,
)
from a7iii.stills.stack import dynamic_range_gain_ev, snr


def texture(h=96, w=128, seed=0):
    rng = np.random.default_rng(seed)
    return gaussian_filter(rng.random((h, w)), 1.2)


def psnr(a, b):
    return 10 * np.log10(1.0 / np.mean((a - b) ** 2))


def test_phase_correlation_subpixel():
    ref = texture()
    moved = shift(ref, (2.3, -1.7), order=3, mode="wrap")
    dy, dx = phase_correlation(ref, moved)
    assert dy == pytest.approx(2.3, abs=0.15) and dx == pytest.approx(-1.7, abs=0.15)


def _downsample(img, f=2):
    h, w = img.shape
    return img[: h - h % f, : w - w % f].reshape(h // f, f, w // f, f).mean(axis=(1, 3))


def test_superres_beats_single_frame_upsampling():
    rng = np.random.default_rng(1)
    hr = gaussian_filter(rng.random((160, 200)), 1.0)
    hr = (hr - hr.min()) / (hr.max() - hr.min())
    frames, offsets = [], []
    for k in range(12):
        oy, ox = rng.uniform(-2, 2, 2)  # hi-res pixels of hand tremor
        offsets.append((oy, ox))
        frames.append(_downsample(shift(hr, (oy, ox), order=3, mode="reflect")) + rng.normal(0, 0.01, (80, 100)))
    sr = iterative_backprojection(frames, factor=2)
    single = bilinear_upsample(frames[0], 2)
    assert shift_and_add(frames, factor=2).shape == sr.shape
    # Reconstruction is registered to frame 0, which carries its own tremor offset.
    hr = shift(hr, offsets[0], order=3, mode="reflect")
    crop = (slice(10, -10), slice(10, -10))
    gain = psnr(sr[crop], hr[crop]) - psnr(single[crop], hr[crop])
    assert gain > 6.0  # dB over single-frame upscaling


def test_stacking_improves_snr_by_sqrt_n():
    rng = np.random.default_rng(2)
    clean = np.full((40, 40), 0.2)
    frames = [clean + rng.normal(0, 0.05, clean.shape) for _ in range(16)]
    frames[3][10, 10] = 5.0  # satellite / hot pixel
    one = snr(frames[0])
    stacked = stack(frames, method="sigma_clip", align=False)
    assert snr(stacked) / one == pytest.approx(4.0, rel=0.25)
    assert stacked[10, 10] < 0.4  # outlier rejected
    assert dynamic_range_gain_ev(16) == pytest.approx(2.0)
    with pytest.raises(ValueError):
        stack(frames, method="nope")


def test_focus_stack_takes_sharpest_regions():
    sharp = texture(64, 64, 3)
    a = sharp.copy(); a[:, 32:] = gaussian_filter(sharp, 3)[:, 32:]   # left sharp
    b = sharp.copy(); b[:, :32] = gaussian_filter(sharp, 3)[:, :32]   # right sharp
    merged, idx = focus_stack([a, b], align=False)
    assert np.mean(idx[:, :28] == 0) > 0.95 and np.mean(idx[:, 36:] == 1) > 0.95
    err_merged = np.abs(merged - sharp)[4:-4, 4:-4].mean()
    assert err_merged < 0.3 * min(np.abs(a - sharp).mean(), np.abs(b - sharp).mean())


def test_motion_trigger_with_preroll():
    rng = np.random.default_rng(4)
    burst = PreCaptureBurst(MotionTrigger(roi=(0.4, 0.4, 0.6, 0.6)), pre_s=0.5, post_s=0.25)
    for i in range(60):  # 2.5 s at 24 fps; bird lands at t = 1.5 s
        t = i / 24
        f = np.full((60, 80), 0.3) + rng.normal(0, 0.01, (60, 80))
        if t >= 1.5:
            f[25:35, 35:45] = 0.9
        burst.feed(t, f)
    assert burst.trigger.fires == [pytest.approx(1.5, abs=1 / 24)]
    frames = burst.bursts[0]
    assert frames[0].timestamp < 1.5 - 0.4  # includes ~0.5 s before the event
    assert frames[-1].timestamp >= 1.5 + 0.25 - 1e-9
