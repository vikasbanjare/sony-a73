"""The Control Desk engine: one object that owns the camera link and every live tool.

Hardware and simulation take the same path. In simulation the driver is a
real ``SonyCamera`` talking to ``SimTransport``, so the desk exercises the
production PTP code.
"""

from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path

import numpy as np

from ..af import AFConfig, AFController, FrameGeometry
from ..cinema.cine_ei import CineEI, monitor_transform
from ..cinema.false_color import ZONES, false_color, zone_histogram
from ..cinema.framing import desqueeze, draw_guides, standard_guides
from ..cinema.ring_buffer import PreRollBuffer
from ..cinema.scopes import clipping_report, histogram, rgb_parade, to_image, vectorscope, waveform, luma
from ..cinema.shutter import solve_shutter
from ..cloud.store import Store
from ..optics.af_guard import check_aperture, f_number_from_ptp
from ..optics.focus_map import classify, overlay
from ..ptp.automation import PtpAFSink, apply_cine_ei, apply_shutter_angle
from .sources import VideoSource, encode_jpeg, encode_png

VIEWS = ("normal", "falsecolor", "ei", "focusmap")


def curve_for_gamma(gamma: str) -> str:
    g = gamma.lower().replace("-", "")
    if g in ("slog2", "slog3"):
        return g
    return "hlg" if g.startswith("hlg") else "rec709"


@dataclass
class DeskSettings:
    fps: float = 23.976
    angle: float = 180.0
    mains_hz: float | None = 50.0
    gamma: str = "Cine4"
    ei_base: str = "low"
    ei: float | None = None
    squeeze: float = 1.0
    guides: bool = True
    ai_af: bool = False
    preroll_s: float = 10.0
    take_codec: str = "jpeg"  # "jpeg" (frame folder), or "prores" / "h264" / "h265" via ffmpeg


@dataclass
class Take:
    uid: str
    started_at: float
    preroll_frames: int
    frames: list[tuple[float, bytes]] = field(default_factory=list)


class Rig:
    def __init__(self, source: VideoSource, driver=None, store: Store | None = None, detector=None,
                 sim_camera=None, media_dir: str | Path = "takes", camera_name: str = "ILCE-7M3"):
        self.source = source
        self.driver = driver
        self.store = store or Store()
        self.detector = detector
        self.sim = sim_camera
        self.media_dir = Path(media_dir)
        self.camera_name = camera_name
        self.settings = DeskSettings()
        self.preroll = PreRollBuffer(self.settings.preroll_s)
        self.take: Take | None = None
        self.last_t = 0.0
        self.last_frame: np.ndarray | None = None
        self.last_jpeg: bytes | None = None
        self.last_af = None
        self.guard_status = None
        self.f_number: float | None = None
        self.shutter = None
        self.ticks = 0
        self.af: AFController | None = None
        self.messages: list[str] = []

    # --- settings ----------------------------------------------------------------

    def apply_settings(self, push: bool = True, **changes) -> dict:
        """Validate and adopt settings; ``push=False`` plans without touching a real body's exposure."""
        for k in changes:
            if not hasattr(self.settings, k):
                raise ValueError(f"unknown setting {k!r}")
        candidate = replace(self.settings, **changes)
        ei = CineEI(candidate.gamma, candidate.ei_base)
        ei.recording_iso  # validates gamma / base
        if candidate.ei:
            ei.monitor_offset_ev(candidate.ei)  # validates the EI range
        if candidate.take_codec not in ("jpeg", "prores", "h264", "h265"):
            raise ValueError("take_codec must be jpeg, prores, h264 or h265")
        if candidate.squeeze <= 0 or candidate.preroll_s <= 0:
            raise ValueError("squeeze and pre-roll must be positive")
        self.settings = s = candidate
        if s.preroll_s != self.preroll.seconds:
            self.preroll = PreRollBuffer(s.preroll_s)
        if self.sim is not None:  # body-menu settings PTP can't reach: set them on the simulated body
            self.sim.state.gamma = s.gamma
            self.sim.state.fps = s.fps
        if self.driver is not None and push:
            self.shutter = apply_shutter_angle(self.driver, s.fps, s.angle, s.mains_hz)
            apply_cine_ei(self.driver, s.gamma, s.ei_base)
        else:
            self.shutter = solve_shutter(s.fps, s.angle, s.mains_hz)
        if s.ai_af and self.af is None and self.driver is not None and self.last_frame is not None:
            H, W = self.last_frame.shape[:2]
            self.af = AFController(PtpAFSink(self.driver), FrameGeometry(W, H), AFConfig())
        if not s.ai_af:
            self.af = None
        return self.state()

    def cine_ei(self) -> CineEI:
        return CineEI(self.settings.gamma, self.settings.ei_base)

    # --- main loop ------------------------------------------------------------------

    def tick(self) -> dict:
        t, frame = self.source.read()
        self.last_t, self.last_frame = t, frame
        self.last_jpeg = encode_jpeg(frame)
        self.ticks += 1
        if self.take is not None:
            self.take.frames.append((t, self.last_jpeg))
        else:
            self.preroll.push(t, self.last_jpeg, len(self.last_jpeg))

        if self.driver is not None and self.ticks % 3 == 1:  # ~ 8-10 Hz at 24-30 fps
            f = self._f_number()
            if f is not None:
                self.f_number = f
                status = check_aperture(f, movie_mode=True)
                if self.guard_status is not None and status.ok != self.guard_status.ok:
                    self.store.log_event("af_guard", {"ok": status.ok, "message": status.message},
                                         self.take.uid if self.take else None, t)
                self.guard_status = status

        if self.settings.ai_af and self.driver is not None:
            if self.af is None:
                H, W = frame.shape[:2]
                self.af = AFController(PtpAFSink(self.driver), FrameGeometry(W, H), AFConfig())
            if self.f_number is not None:
                self.af.set_lens_state(self.f_number, movie_mode=True)
            dets = self.detector.detect(getattr(self.source, "last", frame)) if self.detector else []
            self.last_af = self.af.step(t, dets)
        return self.telemetry()

    def _f_number(self) -> float | None:
        try:
            return f_number_from_ptp(self.driver.get_value("f_number"))
        except Exception:
            return None

    # --- takes ----------------------------------------------------------------------

    def start_take(self, include_preroll: bool = False) -> str:
        if self.take is not None:
            raise RuntimeError("already recording")
        if self.driver is not None:
            self.driver.press("movie_record", hold_s=0)
        now = self.last_t
        pre = self.preroll.flush() if include_preroll else []
        if not include_preroll:
            self.preroll.flush()
        uid = f"{self.camera_name}-{int(time.time() * 1000)}"
        self.take = Take(uid, now, len(pre), [(f.timestamp, f.payload) for f in pre])
        return uid

    def stop_take(self) -> dict:
        if self.take is None:
            raise RuntimeError("not recording")
        if self.driver is not None:
            self.driver.press("movie_record", hold_s=0)
        take, self.take = self.take, None
        folder = self.media_dir / take.uid
        folder.mkdir(parents=True, exist_ok=True)
        media_path = folder
        if self.settings.take_codec == "jpeg" or not take.frames:
            for i, (_, jpeg) in enumerate(take.frames):
                (folder / f"{i:06d}.jpg").write_bytes(jpeg)
        else:
            from ..media import encode_frames

            ext = ".mov" if self.settings.take_codec == "prores" else ".mp4"
            media_path = encode_frames((j for _, j in take.frames), self.settings.fps, folder / f"{take.uid}{ext}",
                                       codec=self.settings.take_codec)
        first = take.frames[0][0] if take.frames else take.started_at
        last = take.frames[-1][0] if take.frames else take.started_at
        record = {
            "uid": take.uid,
            "camera": self.camera_name,
            "started_at": first,
            "duration_s": last - first,
            "preroll_s": max(0.0, take.started_at - first),
            "settings": self._settings_snapshot(),
            "media_path": str(media_path),
        }
        self.store.upsert_take(record)
        return record | {"frames": len(take.frames), "preroll_frames": take.preroll_frames}

    def _settings_snapshot(self) -> dict:
        snap = asdict(self.settings)
        if self.shutter is not None:
            snap["shutter"] = self.shutter.label
            snap["effective_angle"] = round(self.shutter.effective_angle, 2)
        if self.sim is not None:
            snap["iso"] = self.sim.state.iso
            snap["f_number"] = self.sim.state.f_number
        return snap

    # --- views & scopes ----------------------------------------------------------------

    def render_view(self, view: str = "normal") -> np.ndarray:
        if self.last_frame is None:
            raise RuntimeError("no frame yet")
        f = np.asarray(self.last_frame, dtype=np.float64)
        curve = curve_for_gamma(self.settings.gamma)
        if view == "falsecolor":
            out = false_color(f, curve) / 255.0
        elif view == "ei":
            offset = self.cine_ei().monitor_offset_ev(self.settings.ei) if self.settings.ei else 0.0
            out = monitor_transform(curve, offset)(f)
        elif view == "focusmap":
            if self.sim is None or self.source.last is None:
                raise ValueError("focus map needs depth (simulator, or a depth model on hardware)")
            st = self.sim.state
            cls = classify(self.source.last.depth, self.sim.lens.focal_mm, st.f_number, self.sim.focus_distance_mm)
            out = overlay(f, cls)
        elif view == "normal":
            out = f
        else:
            raise ValueError(f"unknown view {view!r}; choose from {VIEWS}")
        if self.settings.squeeze != 1.0:
            out = desqueeze(out, self.settings.squeeze, keep_height=False)
        if self.settings.guides:
            H, W = out.shape[:2]
            g = standard_guides(W, H)
            out = draw_guides(out, g[:1] + g[4:5])
        return np.clip(out, 0, 1)

    def scope_png(self, kind: str) -> bytes:
        f = self.last_frame
        if f is None:
            raise RuntimeError("no frame yet")
        if kind == "waveform":
            img = to_image(waveform(luma(f), 128, 256))
        elif kind == "parade":
            img = to_image(rgb_parade(f, 128, 128))
        elif kind == "vectorscope":
            img = to_image(vectorscope(f, 192, gain=2.0))
        elif kind == "histogram":
            h = histogram(f, 128).astype(float)
            img = np.zeros((96, 128, 3), np.uint8)
            for c in range(3):
                heights = (h[c] / (h.max() or 1) * 95).astype(int)
                for x, hgt in enumerate(heights):
                    img[95 - hgt:, x, c] = 220
        else:
            raise ValueError(f"unknown scope {kind!r}")
        return encode_png(img)

    # --- state -----------------------------------------------------------------------

    def telemetry(self) -> dict:
        f = self.last_frame
        curve = curve_for_gamma(self.settings.gamma)
        out = {
            "t": self.last_t,
            "recording": self.take is not None,
            "take_frames": len(self.take.frames) if self.take else 0,
            "preroll_s": round(self.preroll.duration, 2),
            "shutter": self.shutter.label if self.shutter else None,
            "effective_angle": round(self.shutter.effective_angle, 1) if self.shutter else None,
            "flicker_free": self.shutter.flicker_free if self.shutter else None,
            "pdaf_ok": None if self.guard_status is None else self.guard_status.ok,
            "pdaf_message": None if self.guard_status is None else self.guard_status.message,
            "recording_iso": self._recording_iso(),
        }
        if f is not None:
            small = f[::4, ::4]
            out["zones"] = zone_histogram(small, curve)
            out["clipping"] = clipping_report(small)
        if self.sim is not None:
            st = self.sim.state
            out |= {"iso": st.iso, "f_number": st.f_number, "conversion_gain": self.sim.conversion_gain,
                    "focus_mm": round(self.sim.focus_distance_mm, 1), "gamma": st.gamma}
        if self.last_af is not None:
            out["af"] = {"status": self.last_af.status, "sent": self.last_af.sent,
                         "part": self.last_af.point.part if self.last_af.point else None}
        return out

    def _recording_iso(self) -> int | None:
        try:
            return self.cine_ei().recording_iso
        except ValueError:
            return None

    def state(self) -> dict:
        return {"settings": asdict(self.settings), "telemetry": self.telemetry(),
                "zones": [{"from": z[0] if np.isfinite(z[0]) else None, "rgb": z[1], "label": z[2]} for z in ZONES]}
