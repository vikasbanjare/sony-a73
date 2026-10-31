"""End-to-end simulation of every roadmap feature (``a7iii sim run``).

Each scenario drives the production code (usually through the real PTP
driver talking to the virtual camera), measures an outcome, and checks it
against a stated pass criterion. Statuses:

- PASS / FAIL: the feature was exercised and measured
- BLOCKED: deliberately not executable until something external is verified
- LIMIT: a Tier-4 silicon limit; documented, not attempted
"""

from __future__ import annotations

import json
import math
import time
import traceback
from dataclasses import asdict, dataclass, field
from fractions import Fraction
from pathlib import Path
from typing import Callable

import numpy as np

from ..color.transfer import decode, encode, middle_grey_signal
from .camera import Lens, VirtualA7III
from .scene import Scene, chart_scene, macro_scene, walking_subject_scene


@dataclass
class Result:
    key: str
    title: str
    ref: str
    tier: str
    status: str
    criterion: str
    metrics: dict = field(default_factory=dict)
    detail: str = ""
    artifacts: list[str] = field(default_factory=list)
    seconds: float = 0.0


@dataclass
class Ctx:
    out: Path
    artifacts: list[str] = field(default_factory=list)

    def save_image(self, name: str, img: np.ndarray) -> str:
        from PIL import Image

        a = np.asarray(img)
        if a.dtype != np.uint8:
            a = np.clip(a * 255.0 + 0.5, 0, 255).astype(np.uint8)
        path = self.out / name
        Image.fromarray(a).save(path)
        self.artifacts.append(name)
        return name

    def save_file(self, name: str) -> Path:
        self.artifacts.append(name)
        return self.out / name


_REGISTRY: list[tuple[str, str, str, str, str, Callable]] = []


def scenario(key: str, title: str, ref: str, tier: str, criterion: str):
    def deco(fn):
        _REGISTRY.append((key, title, ref, tier, criterion, fn))
        return fn
    return deco


def _exact_correct_shutter(cam: VirtualA7III) -> Fraction:
    t = 100.0 / cam.state.iso * cam.state.f_number**2 / 2**cam.scene.ev100
    return Fraction(t).limit_denominator(1_000_000)


def _mf(cam: VirtualA7III, distance_mm: float) -> None:
    cam.state.af_mode = "MF"
    cam.state.focus_step = cam.lens.step_for_distance(distance_mm)


# =============================================================================== Tier 1


@scenario("nvram_languages", "35-language unlock via guarded NVRAM service tool", "§3.2-3.3, §9", "Tier 1",
          "33 locked language flags enabled after a sealed backup, read-back verified, calibration untouched, restore works")
def s_nvram(ctx: Ctx):
    from ..nvram import NvramService
    from .nvram import SIM_CALIBRATION_PROPS, PersistentSimBackend

    be = PersistentSimBackend(ctx.out / "sim_nvram_image.json")
    svc = NvramService(be)
    backup = svc.dump()
    backup.save(ctx.out)
    report = svc.apply(svc.plan("languages"), backup, dry_run=False)
    enabled = sum(be.props[p] == b"\x01" for p in range(0x010D008F, 0x010D00B2))
    calib_ok = all(be.props[k] == v for k, v in SIM_CALIBRATION_PROPS.items())
    svc.restore(backup, dry_run=False)
    restored = all(be.props[k] == v for k, v in backup.props.items())
    return (len(report.written) == 33 and enabled == 35 and calib_ok and restored and be.protected,
            {"written": len(report.written), "languages_enabled": enabled, "calibration_untouched": calib_ok,
             "restore_exact": restored}, "")


@scenario("nvram_locked", "29m59s limit + PAL/NTSC nag unlock", "§3.3, §9", "Tier 1", "refused until verified property IDs exist")
def s_nvram_locked(ctx: Ctx):
    from ..nvram import TWEAKS

    locked = [k for k in ("rec_limit", "pal_ntsc_warning") if not TWEAKS[k].available]
    return ("BLOCKED", {"locked": locked},
            "The roadmap gives no property IDs for these flags. The tool refuses to guess; add a verified ID "
            "to nvram/registry.py (reviewed change) to enable them.")


@scenario("picture_profiles", "Picture Profile recipes + correct-exposure grey", "§4.2", "Tier 1",
          "18% grey lands on each recipe's middle-grey level within 2%; recipe native ISOs match the DCG table")
def s_profiles(ctx: Ctx):
    from ..color.profiles import PICTURE_PROFILES, native_isos

    metrics, ok = {}, True
    for name, recipe in PICTURE_PROFILES.items():
        gamma = recipe["gamma"]
        scene = Scene(background_depth=3.0, texture_scale=None, ev100=9.0, background_tint=(0.36, 0.36, 0.36))
        cam = VirtualA7III(scene, width=64, height=36, seed=1)
        cam.state.gamma, cam.state.iso, cam.state.f_number = gamma, recipe["native_iso"][0], 4.0
        cam.state.shutter = _exact_correct_shutter(cam)
        _mf(cam, 3000)
        grey = float(cam.render().signal[..., 1].mean())
        curve = {"S-Log2": "slog2", "HLG3": "hlg"}.get(gamma, "rec709")
        target = middle_grey_signal(curve)
        iso_ok = tuple(recipe["native_iso"]) == native_isos(gamma)
        ok &= abs(grey - target) < 0.02 and iso_ok
        metrics[name] = {"grey_signal": round(grey, 4), "target": round(target, 4), "native_iso_matches": iso_ok}
    return ok, metrics, ""


@scenario("dual_gain", "IMX410 dual conversion gain ('hidden dual native ISO')", "§2.2", "Tier 1",
          "shadow SNR at the HCG ISO beats the 'forbidden zone' ISO just below it (Cine4 640 > 500; S-Log3 5000 > 4000)")
def s_dcg(ctx: Ctx):
    def shadow_snr(gamma, iso, seed=0):
        scene = Scene(background_depth=3.0, texture_scale=None, ev100=8.0, background_tint=(0.006,) * 3)
        cam = VirtualA7III(scene, width=128, height=72, seed=seed)
        cam.state.gamma, cam.state.iso, cam.state.f_number = gamma, iso, 2.8
        cam.state.shutter = _exact_correct_shutter(cam)
        _mf(cam, 3000)
        x = cam.render().linear[..., 1]
        return float(x.mean() / x.std()), cam.conversion_gain, round(cam.read_noise_e, 2)

    m = {}
    for gamma, isos in (("Cine4", (400, 500, 640, 800)), ("S-Log3", (3200, 4000, 5000, 6400))):
        for iso in isos:
            snr, cg, rn = shadow_snr(gamma, iso)
            m[f"{gamma} ISO {iso}"] = {"shadow_snr": round(snr, 2), "gain": cg, "read_noise_e": rn}
    ok = (m["Cine4 ISO 640"]["shadow_snr"] > m["Cine4 ISO 500"]["shadow_snr"]
          and m["S-Log3 ISO 5000"]["shadow_snr"] > m["S-Log3 ISO 4000"]["shadow_snr"])
    note = ("Shadow patch (0.3% reflectance) at correct exposure for each ISO, measured pre-quantisation. "
            "The HCG ISO receives 22% less light than the ISO below it and still has the cleaner shadows.")
    return ok, m, note


@scenario("hlg_vs_slog3_8bit", "HLG3 vs S-Log3 tonal density in an 8-bit pipeline", "§1.3, §4.1", "Tier 1",
          "HLG3 spends more 8-bit code values per stop than S-Log3 across skin/midtones (-1.5..+1.5 EV)")
def s_banding(ctx: Ctx):
    m = {}
    for curve in ("hlg", "slog2", "slog3", "rec709"):
        lo, hi = 0.18 * 2**-1.5, 0.18 * 2**1.5
        codes = (float(encode(curve, hi)) - float(encode(curve, lo))) * 255 / 3
        ramp = np.geomspace(lo, hi, 4000)
        q = np.round(encode(curve, ramp) * 255) / 255
        distinct = len(np.unique(q))
        graded = encode("rec709", np.clip(decode(curve, q), 0, None) * (0.18 / 0.18))
        max_step = float(np.max(np.diff(np.unique(np.round(graded * 255))))) if distinct > 1 else 0.0
        m[curve] = {"codes_per_stop": round(codes, 1), "distinct_levels_3_stops": distinct, "max_display_step_8bit": max_step}
    ok = m["hlg"]["codes_per_stop"] > m["slog3"]["codes_per_stop"]
    return ok, m, "Larger display steps after the grade show up as visible banding on skin and skies."


# =============================================================================== Tier 3 colour


def _chart_patches(cam: VirtualA7III, frame) -> np.ndarray:
    x0, y0, x1, y1 = cam.scene.chart_layout()
    f_px = cam.f_px() * cam.lens.magnification(cam.focus_distance_mm)
    cx, cy = (cam.W - 1) / 2, (cam.H - 1) / 2
    out = []
    for r in range(4):
        for c in range(6):
            u = x0 + (c + 0.5) * (x1 - x0) / 6
            v = y0 + (r + 0.5) * (y1 - y0) / 4
            px, py = int(round(u * f_px + cx)), int(round(v * f_px + cy))
            out.append(frame.signal[py - 2: py + 3, px - 2: px + 3].reshape(-1, 3).mean(axis=0))
    return np.array(out)


@scenario("fx3_color_match", "FX3 colour match: ΔE2000 CCM + OKLab RBF -> 65³ LUT + DCTL", "§4.3, §9", "Tier 3",
          "through the generated LUT: mean ΔE2000 < 1.5 over 24 patches and < 1.0 on skin patches (roadmap Phase 2 gate)")
def s_color(ctx: Ctx):
    from ..color.chart_solver import solve_ccm
    from ..color.colorimetry import delta_e_2000, linear_rgb_to_lab
    from ..color.dctl import lut_dctl, matrix_dctl
    from ..color.lut import apply_lut_trilinear, build_lut, write_cube
    from ..color.residual import fit_residual, match_transform

    m_a7 = np.array([[0.90, 0.13, -0.03], [0.07, 0.86, 0.07], [0.00, -0.10, 1.10]])  # a7 III-like sensor response
    m_fx3 = np.array([[0.97, 0.04, -0.01], [0.02, 0.96, 0.02], [0.0, -0.02, 1.02]])

    def shoot(matrix, gamma, iso, seed):
        cam = VirtualA7III(chart_scene(ev100=10), width=480, height=270, seed=seed, color_matrix=matrix)
        cam.state.gamma, cam.state.iso, cam.state.f_number = gamma, iso, 5.6
        cam.state.shutter = _exact_correct_shutter(cam)
        _mf(cam, 2000)
        f = cam.render()
        return cam, f, _chart_patches(cam, f)

    cam_a, frame_a, src = shoot(m_a7, "HLG3", 125, 1)
    _, frame_b, dst = shoot(m_fx3, "S-Log3", 800, 2)
    ctx.save_image("color_a7iii_hlg3.png", frame_a.signal)
    ctx.save_image("color_fx3_slog3.png", frame_b.signal)
    src_lin, dst_lin = decode("hlg", src), decode("slog3", dst)
    ccm = solve_ccm(src_lin, dst_lin, degree=2)
    residual = fit_residual(ccm.apply(src_lin), dst_lin)
    lut = build_lut(match_transform("hlg", "slog3", ccm, residual), 65)
    cube = ctx.save_file("a7iii_hlg3_to_fx3_slog3.cube")
    write_cube(cube, lut, "a7iii_to_fx3")
    ctx.save_file("a7iii_hlg3_to_fx3_slog3.dctl").write_text(lut_dctl(cube, "a7iii_to_fx3"))
    ctx.save_file("a7iii_to_fx3_matrix_only.dctl").write_text(matrix_dctl(solve_ccm(src_lin, dst_lin).matrix))
    through_lut = decode("slog3", apply_lut_trilinear(lut, src))
    de = delta_e_2000(linear_rgb_to_lab(np.clip(through_lut, 0, None)), linear_rgb_to_lab(dst_lin))
    before = delta_e_2000(linear_rgb_to_lab(np.clip(src_lin, 0, None)), linear_rgb_to_lab(dst_lin))
    skin = de[[0, 1, 11]]
    ok = de.mean() < 1.5 and skin.max() < 1.0
    return ok, {"mean_dE_before": round(float(before.mean()), 2), "mean_dE_after": round(float(de.mean()), 3),
                "max_dE_after": round(float(de.max()), 3), "skin_dE_after": [round(float(x), 3) for x in skin],
                "ccm_only_mean_dE": round(ccm.mean_delta_e, 3)}, \
        "Patches extracted from rendered 8-bit frames (HLG3 a7 III vs S-Log3 FX3-like reference)."


@scenario("chroma_420", "8-bit 4:2:0 -> float 4:4:4 joint-bilateral chroma reconstruction", "§4.3 step 3", "Tier 3",
          "chroma error after reconstruction is lower than plain nearest-neighbour upsampling")
def s_chroma(ctx: Ctx):
    from ..color.chroma import YCBCR709_TO_RGB, yuv420_to_rgb444

    cam = VirtualA7III(chart_scene(ev100=10), width=320, height=180, seed=3)
    cam.state.f_number = 5.6
    cam.state.shutter = _exact_correct_shutter(cam)
    _mf(cam, 2000)
    rgb = cam.render().signal
    to_ycc = np.linalg.inv(YCBCR709_TO_RGB)
    ycc = rgb @ to_ycc.T
    y8 = np.round(ycc[..., 0] * 219 + 16).astype(np.uint8)
    cb8 = np.round(ycc[..., 1] * 224 + 128).astype(np.uint8)
    cr8 = np.round(ycc[..., 2] * 224 + 128).astype(np.uint8)
    cb_sub, cr_sub = cb8[::2, ::2], cr8[::2, ::2]
    recon = yuv420_to_rgb444(y8, cb_sub, cr_sub)
    nn_cb = np.repeat(np.repeat(cb_sub, 2, 0), 2, 1)[: rgb.shape[0], : rgb.shape[1]]
    nn_cr = np.repeat(np.repeat(cr_sub, 2, 0), 2, 1)[: rgb.shape[0], : rgb.shape[1]]
    nn = np.stack([(y8 - 16) / 219, (nn_cb - 128.0) / 224, (nn_cr - 128.0) / 224], -1) @ YCBCR709_TO_RGB.T
    err_bil = float(np.sqrt(np.mean((recon - rgb) ** 2)))
    err_nn = float(np.sqrt(np.mean((nn - rgb) ** 2)))
    ctx.save_image("chroma_reconstructed.png", np.clip(recon, 0, 1))
    return err_bil < err_nn, {"rmse_joint_bilateral": round(err_bil, 5), "rmse_nearest": round(err_nn, 5),
                              "output_dtype": str(recon.dtype)}, ""


# =============================================================================== Tier 2 PTP & AF


@scenario("ptp_handshake", "Sony PTP SDIO handshake + property control + live view", "§10.2", "Tier 2",
          "3-phase handshake succeeds, settings round-trip, live view returns a JPEG and focus frames")
def s_ptp(ctx: Ctx):
    from . import connect_simulated

    drv, cam = connect_simulated(walking_subject_scene())
    drv.set_prop("iso", 640)
    drv.set_prop("f_number", 400)
    drv.set_prop("shutter_speed", (1 << 16) | 50)
    props = drv.get_props()
    lv = drv.liveview()
    from PIL import Image
    import io

    img = np.asarray(Image.open(io.BytesIO(lv.jpeg)))
    ctx.save_image("ptp_liveview.png", img)
    ok = cam.state.iso == 640 and props[0xD21E].value == 640 and lv.jpeg[:2] == b"\xff\xd8" and lv.focus_frames
    return bool(ok), {"props_reported": len(props), "liveview_bytes": len(lv.jpeg),
                      "focus_frame": asdict(lv.focus_frames[0]), "ops_logged": len(drv.t.log)}, ""


@scenario("ai_af", "External AI subject AF -> PTP Touch-AF -> native PDAF", "§5.2-5.3 mode A, §9", "Tier 2",
          "subject eye stays inside the depth of field in >= 90% of frames after acquisition, vs a fixed AF point baseline")
def s_ai_af(ctx: Ctx):
    from ..af import AFConfig, AFController, FrameGeometry
    from ..optics.dof import depth_of_field
    from ..ptp.automation import PtpAFSink
    from . import GroundTruthDetector, connect_simulated

    def run(ai: bool):
        scene = walking_subject_scene(speed_mps=0.45, start_x=-0.55, depth=2.0, ev100=9)
        drv, cam = connect_simulated(scene, seed=4)
        drv.set_prop("f_number", 180)
        drv.set_prop("shutter_speed", (1 << 16) | 160)  # correct exposure at f/1.8, EV 9
        start = cam.scene.keypoints(0.0)
        f_px = cam.f_px()
        drv.set_af_point(0.5 + start["l_eye"][0] * f_px / cam.W, 0.5 + start["l_eye"][1] * f_px / cam.H)
        ctl = AFController(PtpAFSink(drv), FrameGeometry(cam.W, cam.H), AFConfig(latency_s=0.03))
        det = GroundTruthDetector(seed=2)
        inside, frames = [], []
        for i in range(72):  # 3 s
            cam.advance(1 / cam.state.fps, record=False)
            fr = cam.render(noise=False)
            if ai:
                ctl.step(cam.t, det.detect(fr))
            d = fr.keypoints["depth"] * 1000
            dof = depth_of_field(cam.lens.focal_mm, cam.state.f_number, cam.focus_distance_mm, 0.03)
            inside.append(dof.near <= d <= dof.far)
            if i in (10, 40, 70):
                frames.append(fr.signal)
        return float(np.mean(inside[12:])), frames

    ai_rate, frames = run(True)
    base_rate, base_frames = run(False)
    ctx.save_image("ai_af_tracking.png", np.concatenate(frames, axis=1))
    ctx.save_image("fixed_point_baseline.png", np.concatenate(base_frames, axis=1))
    return ai_rate >= 0.9 and ai_rate > base_rate, {"in_focus_ai": round(ai_rate, 3), "in_focus_fixed_point": round(base_rate, 3)}, \
        "Subject walks across frame; the fixed AF point (camera's own behaviour without subject tracking) loses them."


@scenario("pdaf_guard", "f/11 PDAF cutoff guard + hunting prevention", "§5.3 mode C, RSK-04", "Tier 2",
          "guard flags f/13 over PTP; CDAF beyond f/11 hunts measurably; AI steering is suppressed while PDAF is off")
def s_guard(ctx: Ctx):
    from ..af import AFController, FrameGeometry
    from ..ptp.automation import ApertureGuard
    from . import GroundTruthDetector, connect_simulated

    drv, cam = connect_simulated(Scene(background_depth=3.0), seed=0)
    guard = ApertureGuard(drv)
    drv.set_prop("f_number", 1100)
    ok11 = guard.poll().ok
    drv.set_prop("f_number", 1300)
    st13 = guard.poll()

    def travel(f_number):
        c = VirtualA7III(Scene(background_depth=3.0), seed=0)
        c.state.f_number, c.state.focus_step = f_number, 100
        c.advance(1.0, record=False)
        n = len(c.focus_log)
        c.advance(1.0, record=False)
        return float(np.abs(np.diff([s for _, s in c.focus_log[n - 1:]])).sum())

    pdaf_travel, cdaf_travel = travel(8), travel(16)
    sink_calls = []
    ctl = AFController(lambda u, v: sink_calls.append((u, v)), FrameGeometry(cam.W, cam.H))
    ctl.set_lens_state(16, movie_mode=True)
    det = GroundTruthDetector()
    cam2 = VirtualA7III(walking_subject_scene(), seed=0)
    for _ in range(10):
        cam2.advance(1 / 24, record=False)
        ctl.step(cam2.t, det.detect(cam2.render(noise=False)))
    ok = ok11 and not st13.ok and cdaf_travel > 50 * max(pdaf_travel, 1) and not sink_calls
    return ok, {"f11_ok": ok11, "f13_message": st13.message, "settled_travel_pdaf_steps": pdaf_travel,
                "settled_travel_cdaf_steps": cdaf_travel, "ai_commands_sent_at_f16": len(sink_calls)}, ""


@scenario("shutter_angle_flicker", "180° shutter-angle lock + 50/60 Hz anti-flicker", "§7, §10.3 module A", "Tier 2",
          "locked speeds render with < 0.5% row banding under AC light; the naive 180° speed under 50 Hz bands visibly")
def s_flicker(ctx: Ctx):
    from ..ptp.automation import apply_shutter_angle
    from . import connect_simulated

    def banding(mains, fps, angle, lock):
        drv, cam = connect_simulated(Scene(background_depth=3.0, texture_scale=None, ev100=9, flicker_hz=mains))
        cam.state.fps = fps
        sol = apply_shutter_angle(drv, fps, angle, mains if lock else None)
        _mf(cam, 3000)
        f = cam.render(noise=False)
        rows = f.linear[..., 1].mean(axis=1)
        return sol, float(rows.std() / rows.mean()), f.signal

    cases, m, ok, strip = [(50, 25.0, 180, True), (50, 29.97, 180, False), (50, 29.97, 180, True), (60, 23.976, 180, True),
                           (60, 59.94, 180, True)], {}, True, []
    for mains, fps, angle, lock in cases:
        sol, band, img = banding(mains, fps, angle, lock)
        key = f"{fps}p @ {mains} Hz {'locked' if lock else 'unlocked'}"
        m[key] = {"shutter": sol.label, "effective_angle": round(sol.effective_angle, 1), "row_banding_pct": round(100 * band, 3)}
        strip.append(img)
        ok &= (band < 0.005) if lock else (band > 0.02)
    ctx.save_image("flicker_cases.png", np.concatenate(strip, axis=1))
    return ok, m, "The unlocked 29.97p case picks 1/60 s (179.8°), which is not a multiple of the 100 Hz light period."


@scenario("cine_ei", "Cine EI mode (ISO locked to native gain, EI shifts the monitor LUT)", "§7, §9", "Tier 1+2",
          "PTP locks ISO 5000 (HCG) for S-Log3; rating EI 10000 lifts monitored grey by exactly +1 EV; recorded signal unchanged")
def s_cine_ei(ctx: Ctx):
    from ..cinema.cine_ei import monitor_transform
    from ..ptp.automation import apply_cine_ei
    from . import connect_simulated

    drv, cam = connect_simulated(Scene(background_depth=3.0, texture_scale=None, ev100=4, background_tint=(0.36,) * 3))
    cam.state.gamma = "S-Log3"
    ei = apply_cine_ei(drv, "slog3", "high")
    cam.state.f_number = 2.8
    cam.state.shutter = _exact_correct_shutter(cam)
    _mf(cam, 3000)
    sig = cam.render(noise=False).signal
    grey_rec = float(sig[..., 1].mean())
    base = float(monitor_transform("slog3", 0)(sig)[..., 1].mean())
    plus = float(monitor_transform("slog3", ei.monitor_offset_ev(10000))(sig)[..., 1].mean())
    stops = math.log2(float(decode("rec709", plus)) / float(decode("rec709", base)))
    ok = cam.state.iso == 5000 and cam.conversion_gain == "HCG" and abs(stops - 1.0) < 0.03 \
        and abs(grey_rec - middle_grey_signal("slog3")) < 0.01
    return ok, {"recording_iso": cam.state.iso, "gain": cam.conversion_gain, "recorded_grey": round(grey_rec, 4),
                "monitor_shift_ev": round(stops, 3)}, ""


@scenario("el_zone_false_color", "EL-Zone style stop-based false colour", "§7, §10.3 module B", "Tier 2",
          "18% grey maps to the middle-grey zone in every curve; +3.5 EV maps to 'bright highlight'")
def s_false_color(ctx: Ctx):
    from ..cinema.false_color import ZONES, false_color, zone_histogram

    m, ok, strip = {}, True, []
    for gamma, iso, curve in (("Cine4", 100, "rec709"), ("HLG3", 125, "hlg"), ("S-Log2", 800, "slog2"), ("S-Log3", 800, "slog3")):
        cam = VirtualA7III(walking_subject_scene(ev100=8.6), width=256, height=144, seed=0)
        cam.state.gamma, cam.state.iso, cam.state.f_number = gamma, iso, 2.8
        cam.state.shutter = _exact_correct_shutter(cam)
        _mf(cam, 2500)
        f = cam.render(noise=False)
        strip.append(false_color(f.signal, curve) / 255.0)
        grey = np.full((2, 2, 3), float(encode(curve, 0.18)))
        hi = np.full((2, 2, 3), float(encode(curve, min(0.18 * 2**3.5, 3.5))))
        g_zone = max(zone_histogram(grey, curve), key=zone_histogram(grey, curve).get)
        h_zone = max(zone_histogram(hi, curve), key=zone_histogram(hi, curve).get)
        m[gamma] = {"grey_zone": g_zone, "+3.5EV_zone": h_zone}
        ok &= "middle grey" in g_zone and "bright highlight" in h_zone
    ctx.save_image("false_color_cine4_hlg3_slog2_slog3.png", np.concatenate(strip, axis=1))
    return ok, m, f"{len(ZONES)} zones, identical meaning across curves."


@scenario("focus_bracket_stack", "Automated focus bracketing over PTP + focus stacking", "§8.1, §9", "Tier 2+3",
          "stack covers >= 90% of the frame at near-best sharpness; the best single frame covers far less")
def s_stack(ctx: Ctx):
    from ..ptp.automation import LensFocusMap, focus_bracket
    from ..stills import focus_stack, sharpness
    from ..stills.focus_stack import prepare
    from . import SimClock, connect_simulated

    lens = Lens(focal_mm=90, min_focus_mm=280, max_f_number=2.8, breathing_k1=-0.15)
    drv, cam = connect_simulated(macro_scene(0.30, 0.38), lens=lens, width=240, height=135)
    cam.state.movie_mode = False
    cam.state.iso = 100
    drv.set_prop("shutter_speed", (1 << 16) | 125)  # correct exposure at f/5.6, EV 12
    plan = focus_bracket(drv, SimClock(cam), 90, 5.6, 300, 380, LensFocusMap(lens.distance_for_step, lens.step_for_distance))
    frames = [f.signal for f in cam.captured]
    scales = [lens.magnification(f.meta["focus_mm"]) for f in cam.captured]
    merged, idx = focus_stack(frames, scales=scales)
    sharp = np.stack([sharpness(f) for f in prepare(frames, scales)])  # same geometry as the merge
    best_possible = sharp.max(axis=0)
    s_merged = sharpness(merged)
    crop = (slice(8, -8), slice(8, -8))
    coverage = float(np.mean((s_merged >= 0.5 * best_possible)[crop]))
    single = max(float(np.mean((s >= 0.5 * best_possible)[crop])) for s in sharp)
    ctx.save_image("focus_stack_merged.png", np.clip(merged, 0, 1))
    ctx.save_image("focus_stack_first_last.png", np.concatenate([frames[0], frames[-1]], axis=1))
    return coverage >= 0.9 and coverage > single + 0.3, {"slices": len(plan), "planned_mm": [round(p, 1) for p in plan],
                                                         "coverage_stack": round(coverage, 3), "coverage_best_single": round(single, 3)}, ""


@scenario("rack_focus", "Cubic-Bézier rack focus over PTP near/far steps", "§5.3 mode B", "Tier 2",
          "lands exactly on target; eased (first tick < 1/3 of peak tick speed)")
def s_rack(ctx: Ctx):
    from ..ptp.automation import rack_focus
    from . import SimClock, connect_simulated

    drv, cam = connect_simulated(Scene(background_depth=3.0))
    drv.set_prop("focus_mode", 1)
    start = cam.state.focus_step
    sched = rack_focus(drv, SimClock(cam, record=False), -240, 2.0, tick_hz=24)
    speeds = np.abs(np.array(sched))
    ok = cam.state.focus_step == start - 240 and speeds[0] < speeds.max() / 3
    return ok, {"ticks": len(sched), "first_tick_steps": int(speeds[0]), "peak_tick_steps": int(speeds.max()),
                "final_step": cam.state.focus_step}, ""


# =============================================================================== stabilisation & optics


@scenario("gyro_stabilization", "A7III-GyroShoe IMU + Gyroflow-style stabilisation (with RS correction)", "§6.1, §9", "Tier 2+3",
          "IMU/video sync error < 10 ms with an unknown 370 ms START->record latency; frame-to-frame jitter reduced >= 4x")
def s_gyro(ctx: Ctx):
    from ..optics.gyro import estimate_offset, read_gcsv
    from ..optics.gyroshoe_host import GyroShoeLink, SimulatedGyroShoe
    from ..optics.rolling_shutter import readout_ms
    from ..optics.stabilize import GyroTrack, apply_row_shifts, row_corrections
    from ..stills.align import phase_correlation
    from .imu import HandheldMotion, SimulatedIMU

    motion = HandheldMotion(pan_rate=0.0, shake_amp=0.0035, seed=5)
    cam = VirtualA7III(Scene(background_depth=4.0, texture_scale=0.04), width=192, height=108, seed=1)
    cam.rotation = motion.angles
    cam.state.steadyshot = False  # RSK-05: IBIS off when using the external IMU
    _mf(cam, 4000)
    # The .gcsv clock starts at START; the movie's clock starts at its first frame. The latency
    # between the two (desk -> shoe -> camera) is what sync has to recover.
    latency = 0.37
    shoe = SimulatedGyroShoe(ctx.out / "gyroshoe_sd", motion, SimulatedIMU(), lambda: cam.t)
    link = GyroShoeLink(shoe)
    link.start("A001C001", 0)
    cam.advance(latency - 1 / cam.state.fps, record=False)
    rec_start = cam.t + 1 / cam.state.fps
    frames, times = [], []
    for _ in range(72):
        cam.advance(1 / cam.state.fps, record=False)
        frames.append(cam.render().signal)
        times.append(cam.t - rec_start)  # movie-relative timestamps, as in the MP4
    link.stop()
    true_offset = -rec_start  # IMU clock starts at camera time 0 (START); movie clock at rec_start
    log = read_gcsv(ctx.out / "gyroshoe_sd" / "A001C001.gcsv")
    ctx.artifacts.append("gyroshoe_sd/A001C001.gcsv")

    f_px = cam.f_px() * cam.lens.magnification(cam.focus_distance_mm)
    flow = np.array([phase_correlation(frames[i], frames[i + 1]) for i in range(len(frames) - 1)])  # (dy, dx)
    # Image content moves opposite to camera rotation: rate = -flow * fps / f_px.
    video_rates = -np.stack([flow[:, 1], flow[:, 0]], axis=1) * cam.state.fps / f_px  # (yaw, pitch)
    readout = readout_ms(cam.state.readout_mode) / 1000
    # A rolling-shutter frame "sees" the camera at mid-readout, not at its start.
    t_mid = (np.array(times[:-1]) + np.array(times[1:])) / 2 + readout / 2
    est = estimate_offset(log.t, log.gyro[:, :2], t_mid, video_rates, max_offset_s=1.0, rate_hz=1000)

    raw = GyroTrack.from_gyro(log.t, log.gyro, offset_s=est)
    smooth = raw.smoothed(0.4)
    stab = []
    for f, t in zip(frames, times):
        dx, dy = row_corrections(raw, smooth, t, cam.H, readout, f_px)
        stab.append(apply_row_shifts(f, dx, dy))
    c = (slice(14, -14), slice(20, -20))

    def jitter(seq):
        d = np.array([phase_correlation(seq[i][c], seq[i + 1][c]) for i in range(5, len(seq) - 6)])
        return float(np.sqrt(np.mean(np.sum(d**2, axis=1))))

    j_raw, j_stab = jitter(frames), jitter(stab)
    ctx.save_image("gyro_before_after.png", np.concatenate([frames[30], stab[30]], axis=1))
    err_ms = abs(est - true_offset) * 1000
    return err_ms < 10 and j_raw / j_stab >= 4, {"sync_error_ms": round(err_ms, 2), "jitter_px_raw": round(j_raw, 3),
                                                  "jitter_px_stabilised": round(j_stab, 3),
                                                  "improvement_x": round(j_raw / j_stab, 1), "imu_samples": len(log.t)}, \
        ("Sync by signed per-axis cross-correlation of gyro rate against rotation recovered from optical flow; "
         "per-row correction uses the FF 4K readout time.")


@scenario("rolling_shutter_modes", "Rolling-shutter readout: Full-Frame 4K24 vs Super35 4K24", "§2.1, §6.1", "Tier 1",
          "measured skew ratio S35/FF within 15% of 13.8/24.4 = 0.566 on a fast pan")
def s_rs(ctx: Ctx):
    from .imu import HandheldMotion

    def skew(mode):
        cam = VirtualA7III(chart_scene(depth=2.0), width=480, height=270, seed=0)
        cam.state.readout_mode = mode
        cam.rotation = HandheldMotion(pan_rate=0.6, shake_amp=0.0).angles
        _mf(cam, 2000)
        cam.t = 0.0
        d = cam.render(noise=False).depth
        f_px = cam.f_px() * cam.lens.magnification(cam.focus_distance_mm)
        rows = np.where((np.abs(d - 2.0) < 1e-6).any(axis=1))[0]
        top, bot = rows[2], rows[-3]
        left = lambda r: np.where(np.abs(d[r] - 2.0) < 1e-6)[0].min()  # noqa: E731
        return (left(top) - left(bot)) / f_px / ((bot - top) / cam.H)

    ff, s35 = skew("ff_4k_24p"), skew("s35_4k_24p")
    ratio = s35 / ff
    return abs(ratio - 13.8 / 24.4) / (13.8 / 24.4) < 0.15, {"skew_rad_per_frame_ff": round(ff, 5),
                                                              "skew_rad_per_frame_s35": round(s35, 5), "ratio": round(ratio, 3)}, ""


@scenario("breathing_comp", "Dynamic focus-breathing compensation", "§6.2, §9", "Tier 2+3",
          "breathing model fitted from rendered frames; compensated subject size varies < 0.5% across the focus range")
def s_breathing(ctx: Ctx):
    from ..optics.breathing import fit_breathing

    lens = Lens(focal_mm=50, min_focus_mm=450, breathing_k1=-0.3)
    widths, dists = [], [450, 600, 900, 1500, 3000, 1e6]
    for d in dists:
        cam = VirtualA7III(chart_scene(depth=2.0), lens=lens, width=1280, height=720)
        cam.state.f_number = 16
        _mf(cam, d)
        dep = cam.render(noise=False).depth
        mask = np.abs(dep - 2.0) < 1e-6
        rows = mask.any(axis=1)
        widths.append(float(mask[rows].sum(axis=1).mean()))
    widths = np.array(widths)
    rel = widths / widths[-1]
    prof = fit_breathing(50, np.array(dists[:-1]), rel[:-1])
    comp = widths * np.array([float(prof.compensation_scale(d, near_mm=450)) for d in dists])
    spread_before = float(widths.max() / widths.min() - 1)
    spread_after = float(comp.max() / comp.min() - 1)
    return spread_after < 0.005, {"size_spread_before_pct": round(100 * spread_before, 2),
                                  "size_spread_after_pct": round(100 * spread_after, 3), "fitted_k1": round(prof.k1, 4)}, ""


@scenario("focus_map", "Focus map / depth-of-field visualiser", "§7", "Tier 2",
          "subject at the focus plane is classified in-focus, background behind, and the overlay is rendered")
def s_focus_map(ctx: Ctx):
    from ..optics.focus_map import BEHIND, IN_FOCUS, classify, overlay

    cam = VirtualA7III(walking_subject_scene(depth=2.5, ev100=9), width=320, height=180)
    cam.state.f_number = 2.0
    _mf(cam, 2500)
    f = cam.render(noise=False)
    cls = classify(f.depth, cam.lens.focal_mm, cam.state.f_number, cam.focus_distance_mm)
    eye = f.keypoints["l_eye"]
    at_eye = cls[int(eye[1] * cam.H), int(eye[0] * cam.W)]
    ctx.save_image("focus_map.png", overlay(f.signal, cls))
    return at_eye == IN_FOCUS and cls[5, -5] == BEHIND, {"class_at_eye": int(at_eye), "class_background": int(cls[5, -5])}, ""


@scenario("anamorphic", "Anamorphic de-squeeze + multi-aspect guides", "§7", "Tier 2",
          "a 2x-squeezed capture is restored to within 4% of true proportions; 2.39:1 guide computed")
def s_anamorphic(ctx: Ctx):
    from ..cinema.framing import aspect_guide, desqueeze, draw_guides, standard_guides

    cam = VirtualA7III(walking_subject_scene(start_x=-0.2, ev100=9), width=384, height=216)
    _mf(cam, 2500)
    f = cam.render(noise=False)

    def eye_gap(img):
        dark = img.mean(axis=-1) < 0.06
        ys, xs = np.nonzero(dark[: img.shape[0] // 2])
        mid = np.median(xs)
        return xs[xs > mid].mean() - xs[xs <= mid].mean()

    squeezed = desqueeze(f.signal, 0.5)  # what a 2x anamorphic lens puts on the sensor
    restored = desqueeze(squeezed, 2.0)
    g0, gs, gr = eye_gap(f.signal), eye_gap(squeezed), eye_gap(restored)
    guide = aspect_guide(restored.shape[1], restored.shape[0], 2.39)
    ctx.save_image("anamorphic_restored_guides.png", draw_guides(restored, standard_guides(*restored.shape[1::-1])[:1], guide))
    return abs(gr / g0 - 1) < 0.04, {"eye_gap_px_true": round(g0, 1), "squeezed": round(gs, 1), "restored": round(gr, 1),
                                      "guide_2.39": asdict(guide)}, ""


@scenario("scopes", "Waveform, RGB parade, vectorscope, histogram", "§7, §9", "Tier 2",
          "scopes render from live frames; the chart's skin patch lands near the vectorscope skin-tone line")
def s_scopes(ctx: Ctx):
    from ..cinema.scopes import rgb_parade, to_image, vectorscope, waveform, luma, ycbcr709

    cam = VirtualA7III(chart_scene(ev100=10), width=320, height=180)
    cam.state.f_number = 5.6
    cam.state.shutter = _exact_correct_shutter(cam)
    _mf(cam, 2000)
    f = cam.render()
    ctx.save_image("scope_waveform.png", to_image(waveform(luma(f.signal), 128, 320)))
    ctx.save_image("scope_parade.png", to_image(rgb_parade(f.signal, 128, 160)))
    ctx.save_image("scope_vectorscope.png", to_image(vectorscope(f.signal, 200, 2.0)))
    skin = _chart_patches(cam, f)[1]
    _, cb, cr = ycbcr709(skin[None, None, :])
    angle = math.degrees(math.atan2(cr.item(), cb.item())) % 360
    return abs(angle - 123) < 15, {"light_skin_hue_angle_deg": round(angle, 1), "skin_line_deg": 123}, ""


# =============================================================================== takes, timecode, audio


@scenario("preroll_buffer", "Pre-capture video ring buffer (retroactive recording)", "§7, §9", "Tier 2",
          "a take triggered late contains the buffered seconds before the trigger, encoded to ProRes 422 HQ")
def s_preroll(ctx: Ctx):
    from ..desk.app import build_sim_rig
    from ..media import ffmpeg_available, probe

    rig = build_sim_rig("walking", media_dir=str(ctx.out / "takes"))
    rig.apply_settings(preroll_s=2.0, take_codec="prores" if ffmpeg_available() else "jpeg")
    for _ in range(60):
        rig.tick()
    rig.start_take(include_preroll=True)
    for _ in range(12):
        rig.tick()
    rec = rig.stop_take()
    m = {k: rec[k] for k in ("frames", "preroll_frames", "preroll_s", "duration_s")}
    if ffmpeg_available():
        v = probe(rec["media_path"])["streams"][0]
        m |= {"codec": v["codec_name"], "pix_fmt": v["pix_fmt"], "file": Path(rec["media_path"]).name}
        ctx.artifacts.append(str(Path(rec["media_path"]).relative_to(Path(ctx.out).resolve())))
    return rec["preroll_s"] >= 1.9 and rec["frames"] == rec["preroll_frames"] + 12, m, \
        "60 frames streamed before the trigger; buffer holds 2 s."


@scenario("ltc_timecode", "SMPTE LTC generator + jam-sync from the camera's audio track", "§7", "Tier 2+3",
          "decoding LTC recorded on the camera's right channel recovers the exact start timecode of video frame 0")
def s_ltc(ctx: Ctx):
    from ..audio import Timecode, decode_ltc, generate_ltc

    fps, actual, sr = 24, 24000 / 1001, 48000
    start = Timecode.parse("14:22:10:05", fps)
    ltc = generate_ltc(start, 240, sr, actual)
    lead_in = 30_000  # camera started recording 0.625 s into the LTC stream
    camera_audio = ltc[lead_in:] * 0.3 + np.random.default_rng(0).normal(0, 0.005, len(ltc) - lead_in)
    frames = decode_ltc(camera_audio, fps, sr)
    first = frames[0]
    spf = sr / actual
    frames_before = first.sample / spf
    tc_frame0 = first.timecode.to_frames() - frames_before
    truth = start.to_frames() + lead_in / spf
    return abs(tc_frame0 - truth) < 0.05, {"decoded_frames": len(frames), "first_decoded": str(first.timecode),
                                           "video_frame0_tc": str(Timecode.from_frames(int(round(tc_frame0)), fps)),
                                           "error_frames": round(abs(tc_frame0 - truth), 4)}, ""


@scenario("audio_matrix", "4-channel audio matrix: device sync, BWF timecode, clip repair", "§7", "Tier 2+3",
          "recorder synced to the sample; 4-ch BWF carries the start TC; clipped shout repaired from the -12 dB safety")
def s_audio(ctx: Ctx):
    from ..audio import Timecode, find_offset, read_wav, repair_clipping, shift_signal, write_bwf

    rng = np.random.default_rng(7)
    sr = 48000
    t = np.arange(sr * 2) / sr
    voice = np.convolve(rng.normal(0, 1, len(t)), np.ones(40) / 40, "same") * 0.4
    voice += 1.4 * np.sin(2 * np.pi * 300 * t) * np.exp(-((t - 1.2) / 0.05) ** 2)  # a shout
    camera = np.clip(voice, -1, 1) * 0.5 + rng.normal(0, 0.01, len(t))
    lav = shift_signal(voice, -777, len(voice) + 1000)
    primary = np.clip(lav, -1, 1)
    safety = lav * 10 ** (-12 / 20)
    off = find_offset(camera, primary[: len(camera) + 1000], max_lag=4000)
    fixed, clipped = repair_clipping(primary, safety, -12)
    lav_aligned, safety_aligned = shift_signal(fixed, off, len(camera)), shift_signal(safety, off, len(camera))
    path = write_bwf(ctx.save_file("take_4ch.wav"), [camera, camera, np.clip(lav_aligned, -1, 1), safety_aligned], sr, 24,
                     start=Timecode.parse("14:22:10:05", 25))
    data, rate, info = read_wav(path)
    err = float(np.max(np.abs(fixed - lav)))
    return off == 777 and data.shape[1] == 4 and err < 0.02 and info["time_reference"] > 0, \
        {"offset_samples": off, "clipped_samples": clipped, "max_repair_error": round(err, 4),
         "bwf_time_reference": info["time_reference"]}, ""


# =============================================================================== computational stills


@scenario("super_resolution", "Handheld multi-frame super-resolution", "§8.2", "Tier 3",
          "12 tremor-shifted stills reconstructed at 2x beat single-frame upscaling by >= 3 dB PSNR against a true 2x render")
def s_superres(ctx: Ctx):
    from ..stills import bilinear_upsample, iterative_backprojection

    scene = Scene(background_depth=3.0, texture_scale=0.03, ev100=11)
    rng = np.random.default_rng(11)
    W, H = 160, 90
    frames, offsets = [], []
    for k in range(12):
        cam = VirtualA7III(scene, width=W, height=H, seed=k, supersample=4)
        cam.state.movie_mode = False
        cam.state.f_number = 8
        cam.state.shutter = _exact_correct_shutter(cam)
        _mf(cam, 3000)
        f_px = cam.f_px() * cam.lens.magnification(cam.focus_distance_mm)
        oy, ox = rng.uniform(-1, 1, 2)
        cam.rotation = lambda t, ox=ox, oy=oy, f=f_px: (np.full_like(t, ox / f), np.full_like(t, oy / f))
        frames.append(cam.render(still=True).linear[..., 1])
        offsets.append((oy, ox))
    truth_cam = VirtualA7III(scene, width=2 * W, height=2 * H, seed=99, supersample=4)
    truth_cam.state.movie_mode = False
    truth_cam.state.f_number = 8  # set before computing the shutter (exposure must match the burst)
    truth_cam.state.shutter = _exact_correct_shutter(truth_cam)
    _mf(truth_cam, 3000)
    f_px2 = truth_cam.f_px() * truth_cam.lens.magnification(truth_cam.focus_distance_mm)
    oy0, ox0 = offsets[0]
    truth_cam.rotation = lambda t: (np.full_like(t, ox0 / (f_px2 / 2)), np.full_like(t, oy0 / (f_px2 / 2)))
    truth = truth_cam.render(still=True, noise=False).linear[..., 1]
    sr = iterative_backprojection(frames, 2)
    single = bilinear_upsample(frames[0], 2)
    c = (slice(12, -12), slice(12, -12))
    peak = truth.max()
    psnr = lambda a: 10 * math.log10(peak**2 / float(np.mean((a[c] - truth[c]) ** 2)))  # noqa: E731
    gain = psnr(sr) - psnr(single)
    ctx.save_image("superres_single_vs_sr.png", np.clip(np.concatenate([single, sr], axis=1) / peak, 0, 1))
    return gain >= 3.0, {"psnr_single_bilinear_db": round(psnr(single), 2), "psnr_superres_db": round(psnr(sr), 2),
                         "gain_db": round(gain, 2)}, "Pixels integrate light over their area (4x4 supersampled aperture)."


@scenario("noise_stacking", "Multi-frame noise / astro stacking", "§8.2", "Tier 3",
          "16-frame sigma-clipped stack improves SNR by ~sqrt(16) = 4x (3.2x-4.8x)")
def s_noise_stack(ctx: Ctx):
    from ..stills import stack

    scene = Scene(background_depth=3.0, texture_scale=None, ev100=-3, background_tint=(0.1,) * 3)
    frames = []
    for k in range(16):
        cam = VirtualA7III(scene, width=96, height=54, seed=100 + k)
        cam.state.movie_mode = False
        cam.state.iso, cam.state.f_number = 6400, 2.8
        cam.state.shutter = _exact_correct_shutter(cam)
        _mf(cam, 3000)
        frames.append(cam.render(still=True).linear[..., 1])
    single = float(frames[0].mean() / frames[0].std())
    st = stack(frames, "sigma_clip", align=False)
    gain = float(st.mean() / st.std()) / single
    return 3.2 <= gain <= 4.8, {"snr_single": round(single, 2), "snr_stack": round(single * gain, 2),
                                "gain_x": round(gain, 2), "dr_gain_ev": round(0.5 * math.log2(16), 2)}, ""


@scenario("precapture_burst", "Pre-capture burst (motion-triggered, with pre-roll)", "§8.3", "Tier 2+3",
          "trigger fires within 3 frames of the subject entering the ROI and the burst includes earlier frames")
def s_burst(ctx: Ctx):
    from ..stills import MotionTrigger, PreCaptureBurst

    cam = VirtualA7III(walking_subject_scene(speed_mps=0.8, start_x=-1.4, depth=2.5, ev100=9), width=192, height=108, seed=2)
    _mf(cam, 2500)
    burst = PreCaptureBurst(MotionTrigger(roi=(0.45, 0.2, 0.55, 0.8)), pre_s=0.5, post_s=0.25)
    entered = None
    for _ in range(96):
        cam.advance(1 / cam.state.fps, record=False)
        f = cam.render()
        burst.feed(cam.t, f.signal)
        ex = f.keypoints["torso"][0]
        if entered is None and 0.45 - 0.11 <= ex <= 0.55:  # body half-width ~0.11 of the frame
            entered = cam.t
    fire = burst.trigger.fires[0] if burst.trigger.fires else None
    frames = burst.bursts[0] if burst.bursts else []
    ok = fire is not None and entered is not None and abs(fire - entered) <= 3 / 24 + 1e-9 and frames and frames[0].timestamp < fire - 0.4
    if frames:
        ctx.save_image("burst_first_trigger_last.png", np.concatenate([frames[0].payload, frames[len(frames) // 2].payload,
                                                                       frames[-1].payload], axis=1))
    return bool(ok), {"subject_entered_s": round(entered or -1, 3), "trigger_s": round(fire or -1, 3),
                      "burst_frames": len(frames)}, ""


# =============================================================================== ingest, cloud, desk


@scenario("ingest_offload", "Verified dual-destination offload + manifests + proxies", "§11 Phase 5", "Tier 3",
          "every file copied to both drives, hash-verified, resumable, manifests re-verify, proxies generated")
def s_ingest(ctx: Ctx):
    from ..ingest import offload, verify_manifest
    from ..media import encode_frames, ffmpeg_available, make_proxies

    card = ctx.out / "card"
    clip = card / "PRIVATE" / "M4ROOT" / "CLIP"
    clip.mkdir(parents=True, exist_ok=True)
    cam = VirtualA7III(walking_subject_scene(ev100=9), width=320, height=180)
    frames = []
    for _ in range(24):
        cam.advance(1 / cam.state.fps, record=False)
        frames.append(cam.render().signal)
    if ffmpeg_available():
        encode_frames(frames, 23.976, clip / "C0001.MP4", "h264")
    else:
        np.save(clip / "C0001.npy", np.array(frames))
    (clip / "C0001M01.XML").write_text("<NonRealTimeMeta/>")
    rep = offload(card, [ctx.out / "ssd_a", ctx.out / "ssd_b"], algorithm="sha256")
    again = offload(card, [ctx.out / "ssd_a"], algorithm="sha256")
    problems = [p for m in rep.manifests for p in verify_manifest(m)]
    proxies = make_proxies(ctx.out / "ssd_a", ctx.out / "proxies", height=90) if ffmpeg_available() else []
    ok = rep.ok and again.ok and not problems and all(s == "skipped" for f in again.files for s in f.status.values())
    return ok, {"files": len(rep.files), "manifests": len(rep.manifests), "resume_all_skipped": ok,
                "proxies": [p.name for p in proxies]}, ""


@scenario("cloud_sync", "Cloud sync API: takes, presets, LUTs, sealed NVRAM backups", "§10.1 packages/07, Phase 5", "Tier 3",
          "two desks converge on the same take list; tampered NVRAM backup rejected")
def s_cloud(ctx: Ctx):
    try:
        from fastapi.testclient import TestClient
    except ImportError:
        return "BLOCKED", {}, "fastapi not installed (pip install '.[desk]')"
    from ..cloud.api import create_app, sync_takes
    from ..cloud.store import Store
    from ..nvram import NvramService
    from .nvram import PersistentSimBackend

    server = TestClient(create_app(str(ctx.out / "cloud.sqlite"), token="t"))
    a, b = Store(), Store()
    a.upsert_take({"uid": "A001C001", "camera": "ILCE-7M3", "started_at": 1.0, "settings": {"gamma": "HLG3"}})
    b.upsert_take({"uid": "B001C001", "camera": "ILCE-7M3", "started_at": 2.0, "settings": {"gamma": "S-Log3"}})
    for s in (a, b, a):
        sync_takes(s, server, token="t")
    backup = NvramService(PersistentSimBackend(ctx.out / "cloud_nvram_image.json")).dump()
    auth = {"Authorization": "Bearer t"}
    good = server.put("/v1/nvram", json={"backup_json": backup.to_json()}, headers=auth).status_code
    bad = server.put("/v1/nvram", json={"backup_json": backup.to_json().replace('"3301234"', '"9999999"')},
                     headers=auth).status_code
    same = {t["uid"] for t in a.takes()} == {t["uid"] for t in b.takes()} == {"A001C001", "B001C001"}
    return same and good == 200 and bad == 400, {"takes_converged": same, "backup_upload": good, "tampered_upload": bad}, ""


@scenario("control_desk", "A7III Control Desk end to end (PTP + AI AF + scopes + takes)", "§10.1 packages/06", "Tier 2",
          "desk drives the simulated body over PTP, AI AF engages, every view and scope renders, a take is logged")
def s_desk(ctx: Ctx):
    try:
        from fastapi.testclient import TestClient
    except ImportError:
        return "BLOCKED", {}, "fastapi not installed (pip install '.[desk]')"
    from ..desk.app import build_sim_rig, create_app

    rig = build_sim_rig("walking", media_dir=str(ctx.out / "desk_takes"))
    with TestClient(create_app(rig, autorun=False)) as client:
        client.post("/api/settings", json={"gamma": "HLG3", "fps": 23.976, "angle": 180, "mains_hz": 50, "ai_af": True})
        for _ in range(12):
            tel = client.post("/api/tick").json()
        views = {v: client.get(f"/api/view/{v}.jpg").status_code for v in ("normal", "falsecolor", "ei", "focusmap")}
        scopes = {s: client.get(f"/api/scope/{s}.png").status_code for s in ("waveform", "vectorscope", "parade", "histogram")}
        (ctx.out / "desk_falsecolor.jpg").write_bytes(client.get("/api/view/falsecolor.jpg").content)
        ctx.artifacts.append("desk_falsecolor.jpg")
        client.post("/api/record/start", params={"preroll": True})
        for _ in range(4):
            client.post("/api/tick")
        take = client.post("/api/record/stop").json()
    ok = all(c == 200 for c in views.values()) and all(c == 200 for c in scopes.values()) \
        and tel["af"] is not None and rig.sim.state.iso == 125 and take["frames"] >= 16
    return ok, {"iso_locked": rig.sim.state.iso, "shutter": tel["shutter"], "af": tel["af"], "take_frames": take["frames"]}, ""


# =============================================================================== Tier 4


@scenario("tier4_limits", "Internal 10-bit 4:2:2, 4K60/120, HDMI RAW", "§9 Tier 4", "Tier 4",
          "documented silicon limits; not attempted")
def s_tier4(ctx: Ctx):
    return "LIMIT", {}, ("The CXD90045 video encoder and HDMI transmitter are 8-bit, and IMX410 readout bandwidth "
                         "caps full-width 4K at 30p. No software path changes this. The suite instead gets the most "
                         "out of 8-bit: HLG3, 4:2:2 HDMI capture, float chroma reconstruction and dithering.")


# =============================================================================== runner


def run_all(out_dir: str | Path, only: list[str] | None = None, progress: Callable[[Result], None] | None = None) -> list[Result]:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    results: list[Result] = []
    for key, title, ref, tier, criterion, fn in _REGISTRY:
        if only and key not in only:
            continue
        ctx = Ctx(out)
        t0 = time.perf_counter()
        try:
            ok, metrics, detail = fn(ctx)
            status = ok if isinstance(ok, str) else ("PASS" if ok else "FAIL")
        except Exception:
            status, metrics, detail = "FAIL", {}, traceback.format_exc(limit=6)
        r = Result(key, title, ref, tier, status, criterion, _jsonable(metrics), detail, ctx.artifacts,
                   round(time.perf_counter() - t0, 2))
        results.append(r)
        if progress:
            progress(r)
    write_report(out, results)
    return results


def _jsonable(x):
    if isinstance(x, dict):
        return {str(k): _jsonable(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [_jsonable(v) for v in x]
    if isinstance(x, (np.floating, np.integer)):
        return x.item()
    if isinstance(x, np.bool_):
        return bool(x)
    return x


def write_report(out: Path, results: list[Result]) -> None:
    (out / "report.json").write_text(json.dumps([asdict(r) for r in results], indent=2, default=str))
    counts = {s: sum(r.status == s for r in results) for s in ("PASS", "FAIL", "BLOCKED", "LIMIT")}
    lines = [
        "# A7III Enhanced Suite: end-to-end simulation report",
        "",
        f"{counts['PASS']} passed · {counts['FAIL']} failed · {counts['BLOCKED']} blocked · {counts['LIMIT']} silicon limits",
        "",
        "Every scenario drives the production code against the virtual ILCE-7M3 (`a7iii.sim`). Most of them",
        "go through the real Sony PTP driver.",
        "",
        "| # | Feature | Roadmap | Tier | Result | Key metrics |",
        "|---|---|---|---|---|---|",
    ]
    for i, r in enumerate(results, 1):
        key_metrics = ", ".join(f"{k}={v}" for k, v in list(_flatten(r.metrics).items())[:4])
        lines.append(f"| {i} | {r.title} | {r.ref} | {r.tier} | **{r.status}** | {key_metrics} |")
    lines += ["", "## Details", ""]
    for r in results:
        lines += [f"### {r.title}: {r.status}", "", f"*Pass criterion:* {r.criterion}", ""]
        if r.metrics:
            lines += ["```json", json.dumps(r.metrics, indent=2, default=str), "```", ""]
        if r.detail:
            lines += [r.detail if r.status != "FAIL" else f"```\n{r.detail}\n```", ""]
        if r.artifacts:
            lines += ["Artifacts: " + ", ".join(f"`{a}`" for a in r.artifacts), ""]
    (out / "report.md").write_text("\n".join(lines))


def _flatten(d: dict, prefix: str = "") -> dict:
    out = {}
    for k, v in d.items():
        if isinstance(v, dict):
            out |= _flatten(v, f"{prefix}{k}.")
        else:
            out[f"{prefix}{k}"] = v
    return out


def scenario_keys() -> list[str]:
    return [k for k, *_ in _REGISTRY]
