"""Virtual ILCE-7M3: lens, IMX410-like sensor, picture profiles and AF.

Physics model (all documented so results can be reasoned about):

Exposure. Scene brightness is EV100. At "correct" exposure for ISO S,
t/N^2 * 2^EV100 = 100/S, and an 18% grey patch then encodes at the
profile's middle-grey level.

Sensor / dual conversion gain. Photoelectrons e = R * K * t/N^2 * 2^EV100
with K chosen so that full well (63,000 e-) is +3.3 EV above grey at
analog ISO 100. Analog gain = ISO * 100 / profile base ISO, so S-Log3 at
ISO 800 uses the same analog gain as Standard at ISO 100. Analog gain >=
640 switches to HCG. Input-referred read noise =
sqrt(pre^2 + (post * 100 / gain)^2) with pre = 3.2 e- (LCG) or 1.1 e- (HCG).

Optics. Thin lens with defocus blur from the circle of confusion of each
pixel's depth, focus breathing as a focus-dependent magnification, and a
stepper focus motor (1000 steps, 1/distance linear).

AF. PDAF (always in stills; in movie only up to f/11) measures the depth at
the AF point and drives the motor straight there. Beyond f/11 in movie,
contrast-detect AF hill-climbs and hunts.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from fractions import Fraction

import numpy as np
from scipy.ndimage import gaussian_filter

from ..color.profiles import native_isos
from ..color.transfer import encode
from ..optics.rolling_shutter import READOUT_MS
from .scene import Scene

FULL_WELL_E = 63_000.0
GREY_HEADROOM_EV = 3.3
K_ELECTRONS = FULL_WELL_E / 2**GREY_HEADROOM_EV / 0.18  # e- per unit reflectance at correct ISO 100 exposure
READ_NOISE_PRE = {"LCG": 3.2, "HCG": 1.1}
READ_NOISE_POST_AT_BASE = 8.0
HCG_SWITCH_ANALOG = 640

FOCUS_STEPS = 1000
NEAR_FAR_STEP_SIZES = {1: 1, 2: 3, 3: 10, 4: 20, 5: 40, 6: 80, 7: 160}

SENSOR_W_MM = {"ff": 35.6, "s35": 23.5}


def gamma_curve(gamma: str) -> str:
    g = gamma.lower().replace("-", "")
    if g in ("slog2", "slog3"):
        return g
    return "hlg" if g.startswith("hlg") else "rec709"


@dataclass
class Lens:
    focal_mm: float = 50.0
    min_focus_mm: float = 450.0
    max_f_number: float = 1.8
    breathing_k1: float = -0.10  # magnification change vs focus (s(d) = 1 + k1 * f/(d-f))
    af_speed_steps_s: float = 2500.0  # PDAF motor speed

    def distance_for_step(self, step: float) -> float:
        inv = (1.0 - step / FOCUS_STEPS) / self.min_focus_mm
        return math.inf if inv <= 1e-9 else 1.0 / inv

    def step_for_distance(self, d_mm: float) -> float:
        if math.isinf(d_mm):
            return FOCUS_STEPS
        return float(np.clip(FOCUS_STEPS * (1.0 - self.min_focus_mm / max(d_mm, self.min_focus_mm)), 0, FOCUS_STEPS))

    def magnification(self, d_mm: float) -> float:
        if math.isinf(d_mm):
            return 1.0
        return 1.0 + self.breathing_k1 * self.focal_mm / (d_mm - self.focal_mm)


@dataclass
class Frame:
    t: float
    signal: np.ndarray  # (H, W, 3) encoded, 8-bit quantised, float 0..1
    linear: np.ndarray  # (H, W, 3) camera-linear sensor values (x, pre-curve, noisy)
    depth: np.ndarray  # (H, W) metres
    keypoints: dict | None  # pixel-normalised ground truth
    meta: dict = field(default_factory=dict)


@dataclass
class CameraState:
    iso: int = 100
    shutter: Fraction = Fraction(1, 50)
    f_number: float = 4.0
    gamma: str = "Cine4"
    movie_mode: bool = True
    fps: float = 23.976
    readout_mode: str = "ff_4k_24p"
    focus_step: float = 700.0
    af_mode: str = "AF-C"  # "AF-C" or "MF"
    af_point: tuple[float, float] = (0.5, 0.5)  # image-normalised
    recording: bool = False
    steadyshot: bool = True
    half_pressed: bool = False


class VirtualA7III:
    """Stateful simulated body. Advance time with ``advance(dt)``."""

    def __init__(self, scene: Scene, lens: Lens | None = None, width: int = 320, height: int = 180,
                 seed: int = 0, color_matrix: np.ndarray | None = None, supersample: int = 1):
        self.scene = scene
        self.lens = lens or Lens()
        self.W, self.H = width, height
        self.supersample = supersample  # >1 integrates each pixel's area (box pixel aperture)
        self.state = CameraState()
        self.t = 0.0
        self.rng = np.random.default_rng(seed)
        self.rotation = lambda t: (np.zeros_like(t), np.zeros_like(t))  # (yaw, pitch) radians vs time
        # Camera-native colour response: sensor RGB = M @ scene RGB (identity = ideal).
        self.color_matrix = np.eye(3) if color_matrix is None else np.asarray(color_matrix)
        self.recorded: list[Frame] = []
        self.captured: list[Frame] = []
        self.focus_log: list[tuple[float, float]] = []  # (t, focus step)
        self._cdaf_dir = 1.0
        self._cdaf_step = 40.0
        self._cdaf_last = None
        self._last_depth: np.ndarray | None = None
        self._next_frame_t = 1.0 / self.state.fps
        self.firmware = "4.04"
        self.model = "ILCE-7M3"

    # --- derived quantities ------------------------------------------------------

    @property
    def focus_distance_mm(self) -> float:
        return self.lens.distance_for_step(self.state.focus_step)

    @property
    def analog_gain(self) -> float:
        return self.state.iso * 100.0 / self._profile_base()

    def _profile_base(self) -> int:
        try:
            return native_isos(self.state.gamma)[0]
        except ValueError:
            return 100

    @property
    def conversion_gain(self) -> str:
        return "HCG" if self.analog_gain >= HCG_SWITCH_ANALOG * 0.97 else "LCG"

    @property
    def read_noise_e(self) -> float:
        return math.hypot(READ_NOISE_PRE[self.conversion_gain], READ_NOISE_POST_AT_BASE * 100.0 / self.analog_gain)

    @property
    def pdaf_available(self) -> bool:
        return not self.state.movie_mode or self.state.f_number <= 11.0 + 1e-6

    def sensor_width_mm(self) -> float:
        return SENSOR_W_MM["s35" if self.state.readout_mode.startswith("s35") else "ff"]

    def f_px(self) -> float:
        return self.lens.focal_mm / self.sensor_width_mm() * self.W

    # --- control surface (used by the PTP device) --------------------------------

    def set_af_point(self, u: float, v: float) -> None:
        self.state.af_point = (float(np.clip(u, 0, 1)), float(np.clip(v, 0, 1)))

    def focus_move(self, value: int) -> None:
        size = NEAR_FAR_STEP_SIZES[min(abs(value), 7)]
        # Sony: negative = near. Near means a closer focus distance = lower motor step.
        self.state.focus_step = float(np.clip(self.state.focus_step + math.copysign(size, value), 0, FOCUS_STEPS))
        self.focus_log.append((self.t, self.state.focus_step))

    def start_stop_record(self) -> None:
        if not self.state.movie_mode:
            return
        self.state.recording = not self.state.recording

    def capture_still(self) -> Frame:
        frame = self.render(still=True)
        self.captured.append(frame)
        return frame

    # --- time & AF ---------------------------------------------------------------

    def advance(self, dt: float, record: bool = True) -> None:
        """Advance simulated time, running AF each frame and recording frames as they fall due.

        Frame times are locked to the frame clock, so the result doesn't depend
        on how callers chunk ``dt``.
        """
        end = self.t + dt
        while self.t < end - 1e-12:
            target = min(self._next_frame_t, end)
            self._run_af(target - self.t)
            self.t = target
            if self.t >= self._next_frame_t - 1e-12:
                if record and self.state.recording:
                    self.recorded.append(self.render())
                self._next_frame_t += 1.0 / self.state.fps

    def _depth_at_af_point(self) -> float:
        u, v = self.state.af_point
        if self._last_depth is None:
            self._last_depth = self.render(noise=False).depth
        d = self._last_depth
        y = int(np.clip(v * (self.H - 1), 0, self.H - 1))
        x = int(np.clip(u * (self.W - 1), 0, self.W - 1))
        # PDAF measures over a small patch; take the nearest surface in it.
        return float(np.min(d[max(0, y - 2): y + 3, max(0, x - 2): x + 3])) * 1000.0

    def _run_af(self, dt: float) -> None:
        if dt <= 0:
            return
        if self.state.af_mode == "MF" or (not self.state.movie_mode and not self.state.half_pressed):
            return
        self._last_depth = self.render(noise=False).depth
        if self.pdaf_available:
            target = self.lens.step_for_distance(self._depth_at_af_point())
            delta = target - self.state.focus_step
            move = float(np.clip(delta, -self.lens.af_speed_steps_s * dt, self.lens.af_speed_steps_s * dt))
            self.state.focus_step += move
        else:
            self._cdaf_iterate()
        self.focus_log.append((self.t + dt, self.state.focus_step))

    def _cdaf_iterate(self) -> None:
        """Contrast-detect hill climb with wobble: it overshoots and hunts by design."""
        c = self._contrast_at_af_point()
        if self._cdaf_last is not None and c < self._cdaf_last:
            self._cdaf_dir *= -1
            self._cdaf_step = max(8.0, self._cdaf_step * 0.7)
        self._cdaf_last = c
        self.state.focus_step = float(np.clip(self.state.focus_step + self._cdaf_dir * self._cdaf_step, 0, FOCUS_STEPS))

    def _contrast_at_af_point(self) -> float:
        f = self.render(noise=False)
        u, v = self.state.af_point
        y, x = int(v * (self.H - 1)), int(u * (self.W - 1))
        patch = f.linear[max(0, y - 10): y + 10, max(0, x - 10): x + 10, 1]
        return float(np.var(np.diff(patch, axis=1)))

    # --- rendering ---------------------------------------------------------------

    def exposure_seconds(self) -> float:
        return float(self.state.shutter)

    def render(self, still: bool = False, noise: bool = True) -> Frame:
        s = self.state
        H, W = self.H, self.W
        f_px = self.f_px() * self.lens.magnification(self.focus_distance_mm)
        cx, cy = (W - 1) / 2, (H - 1) / 2
        readout = 0.0 if still else READOUT_MS.get(s.readout_mode, 24.4) / 1000.0
        t_row = self.t + readout * np.arange(H) / H

        ss = self.supersample
        sub = (np.arange(ss) + 0.5) / ss - 0.5  # sub-pixel sample offsets
        xs = (np.arange(W)[:, None] + sub[None, :]).ravel()
        ys = (np.arange(H)[:, None] + sub[None, :]).ravel()
        t_rows_ss = np.repeat(t_row, ss)
        yaw, pitch = self.rotation(t_rows_ss)
        px = (xs - cx) / f_px
        py = (ys - cy) / f_px
        u = px[None, :] + yaw[:, None]
        v = py[:, None] + pitch[:, None] + np.zeros((1, W * ss))
        radiance, depth = self.scene.sample(u, v, t_rows_ss)
        if ss > 1:
            radiance = radiance.reshape(H, ss, W, ss, 3).mean(axis=(1, 3))
            depth = depth.reshape(H, ss, W, ss).min(axis=(1, 3))

        # Defocus: blur each pixel by the CoC of its depth (layered approximation).
        radiance = self._defocus(radiance, depth, f_px)

        # Exposure + flicker (per row: each row integrates its own window).
        t_exp = self.exposure_seconds()
        light = self.scene.flicker_factor(t_row, t_exp)[:, None, None]
        photometric = t_exp / s.f_number**2 * 2**self.scene.ev100
        sensor_rgb = np.clip(radiance @ self.color_matrix.T, 0.0, None)
        electrons = sensor_rgb * light * photometric * K_ELECTRONS

        full_well = FULL_WELL_E * 100.0 / max(self.analog_gain, 100.0)
        if noise:
            electrons = self.rng.poisson(np.clip(electrons, 0, 4 * FULL_WELL_E)).astype(np.float64)
            electrons += self.rng.normal(0.0, self.read_noise_e, electrons.shape)
        electrons = np.clip(electrons, 0.0, full_well)

        # Curve-input value: equals reflectance at correct exposure.
        x = electrons * s.iso / (100.0 * K_ELECTRONS)
        curve = gamma_curve(s.gamma)
        signal = np.clip(encode(curve, x), 0.0, 1.0)
        signal = np.round(signal * 255.0) / 255.0  # 8-bit pipeline

        kp = None
        gt = self.scene.keypoints(self.t)
        if gt is not None:
            yaw0, pitch0 = (float(a[0]) for a in self.rotation(np.array([self.t])))
            kp = {}
            for name, (a, b) in gt.items():
                if name == "depth":
                    kp[name] = a
                    continue
                kp[name] = ((a - yaw0) * f_px / W + cx / W, (b - pitch0) * f_px / H + cy / H)

        return Frame(self.t, signal, x, depth, kp, meta={
            "iso": s.iso, "shutter": str(s.shutter), "f_number": s.f_number, "gamma": s.gamma,
            "focus_mm": self.focus_distance_mm, "conversion_gain": self.conversion_gain,
            "read_noise_e": self.read_noise_e, "pdaf": self.pdaf_available,
        })

    def _defocus(self, radiance: np.ndarray, depth: np.ndarray, f_px: float) -> np.ndarray:
        s_mm = self.focus_distance_mm
        f = self.lens.focal_mm
        N = self.state.f_number
        A = f / N
        d_mm = depth * 1000.0
        if math.isinf(s_mm):
            coc_mm = A * f / np.maximum(d_mm - f, 1e-3)
        else:
            coc_mm = A * f / (s_mm - f) * np.abs(d_mm - s_mm) / d_mm
        coc_px = coc_mm / self.sensor_width_mm() * self.W
        sigma = coc_px / 2.5
        levels = np.array([0.0, 0.5, 1.0, 1.6, 2.5, 4.0, 6.0, 9.0])
        if sigma.max() <= 0.15:
            return radiance
        stack = [radiance if lv == 0 else gaussian_filter(radiance, sigma=(lv, lv, 0)) for lv in levels]
        idx = np.clip(np.searchsorted(levels, sigma) - 1, 0, len(levels) - 2)
        lo, hi = levels[idx], levels[idx + 1]
        w = np.clip((sigma - lo) / (hi - lo), 0, 1)[..., None]
        stack = np.stack(stack)
        rows, cols = np.indices(sigma.shape)
        return (1 - w) * stack[idx, rows, cols] + w * stack[idx + 1, rows, cols]

    # --- convenience ------------------------------------------------------------

    def correct_shutter_for_scene(self) -> Fraction:
        """Shutter giving 'correct' exposure for the current ISO/aperture (stills helper)."""
        from ..cinema.shutter import SHUTTER_SPEEDS

        t_ideal = 100.0 / self.state.iso * self.state.f_number**2 / 2**self.scene.ev100
        return min(SHUTTER_SPEEDS, key=lambda t: abs(math.log2(float(t) / t_ideal)))
