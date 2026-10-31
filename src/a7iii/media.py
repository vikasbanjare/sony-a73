"""FFmpeg helpers: encode takes to ProRes/H.264/H.265 and make editing proxies.

Roadmap §7 (flush the pre-roll ring buffer to ProRes/H.265) and Phase 5
(background proxy transcoding during ingest). Requires ``ffmpeg`` on PATH.
"""

from __future__ import annotations

import io
import json
import shutil
import subprocess
from pathlib import Path
from typing import Iterable

import numpy as np

VIDEO_EXTS = {".mp4", ".mov", ".mxf", ".m4v"}

CODECS = {
    # 10-bit 4:2:2 ProRes 422 HQ: the usual intermediate for 8-bit 4:2:2 HDMI captures
    "prores": ["-c:v", "prores_ks", "-profile:v", "3", "-pix_fmt", "yuv422p10le", "-vendor", "apl0"],
    "prores_proxy": ["-c:v", "prores_ks", "-profile:v", "0", "-pix_fmt", "yuv422p10le"],
    "h264": ["-c:v", "libx264", "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p"],
    "h265": ["-c:v", "libx265", "-preset", "medium", "-crf", "20", "-pix_fmt", "yuv420p10le", "-tag:v", "hvc1"],
}


def ffmpeg_available() -> bool:
    return shutil.which("ffmpeg") is not None


def _fps_arg(fps: float) -> str:
    for nominal in (24, 30, 60, 120):
        if abs(fps - nominal * 1000 / 1001) < 1e-3:
            return f"{nominal * 1000}/1001"
    return f"{fps:g}"


def _to_rgb24(frame) -> np.ndarray:
    if isinstance(frame, (bytes, bytearray)):
        from PIL import Image

        return np.asarray(Image.open(io.BytesIO(frame)).convert("RGB"))
    f = np.asarray(frame)
    if f.dtype != np.uint8:
        f = np.clip(f * 255.0 + 0.5, 0, 255).astype(np.uint8)
    return f


def encode_frames(frames: Iterable, fps: float, out_path: str | Path, codec: str = "prores",
                  timecode: str | None = None) -> Path:
    """Encode RGB frames (float 0..1, uint8, or JPEG bytes) into a movie file."""
    if not ffmpeg_available():
        raise RuntimeError("ffmpeg not found on PATH")
    it = iter(frames)
    first = _to_rgb24(next(it))
    h, w = first.shape[:2]
    out = Path(out_path)
    cmd = ["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{w}x{h}",
           "-r", _fps_arg(fps), "-i", "-", *CODECS[codec]]
    if w % 2 or h % 2:
        cmd += ["-vf", "pad=ceil(iw/2)*2:ceil(ih/2)*2"]
    if timecode:
        cmd += ["-timecode", timecode]
    cmd.append(str(out))
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        proc.stdin.write(first.tobytes())
        for f in it:
            proc.stdin.write(_to_rgb24(f).tobytes())
        proc.stdin.close()
    except BrokenPipeError:
        pass
    err = proc.stderr.read().decode(errors="replace")
    if proc.wait() != 0:
        raise RuntimeError(f"ffmpeg failed: {err.strip()}")
    return out


def probe(path: str | Path) -> dict:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path)],
        capture_output=True, text=True, check=True,
    )
    return json.loads(out.stdout)


def make_proxy(src: str | Path, dst_dir: str | Path, height: int = 1080, codec: str = "h264",
               lut: str | Path | None = None) -> Path:
    """Edit-friendly proxy keeping audio, timecode and the source's frame rate.
    ``lut``: a .cube baked into the proxy (e.g. the fxdefault look)."""
    if not ffmpeg_available():
        raise RuntimeError("ffmpeg not found on PATH")
    src = Path(src)
    dst = Path(dst_dir) / (src.stem + ("_proxy.mov" if codec.startswith("prores") else "_proxy.mp4"))
    dst.parent.mkdir(parents=True, exist_ok=True)
    vcodec = CODECS[codec] if codec != "h264" else ["-c:v", "libx264", "-preset", "fast", "-crf", "23", "-pix_fmt", "yuv420p"]
    cmd = ["ffmpeg", "-y", "-loglevel", "error", "-i", str(src), "-map", "0:v:0", "-map", "0:a?",
           "-vf", (f"lut3d=file='{lut}'," if lut else "") + f"scale=-2:'min({height},ih)'", *vcodec, "-c:a", "aac", "-b:a", "192k",
           "-map_metadata", "0", str(dst)]
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        raise RuntimeError(f"proxy failed for {src.name}: {res.stderr.strip()}")
    return dst


def make_proxies(root: str | Path, dst_dir: str | Path, **kwargs) -> list[Path]:
    root = Path(root)
    return [make_proxy(p, dst_dir, **kwargs) for p in sorted(root.rglob("*")) if p.suffix.lower() in VIDEO_EXTS]
