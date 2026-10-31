"""Command-line entry point: ``a7iii <command>``."""

from __future__ import annotations

import argparse
import json
import math
import sys

from .cinema.cine_ei import CineEI
from .cinema.shutter import solve_shutter
from .color.profiles import PICTURE_PROFILES, native_isos, recommend_iso
from .color.transfer import middle_grey_signal
from .optics.af_guard import check_aperture
from .optics.dof import COC_FULL_FRAME_MM, depth_of_field, focus_bracket_plan, hyperfocal
from .optics.rolling_shutter import READOUT_MS


def _fmt_mm(mm: float) -> str:
    return "inf" if math.isinf(mm) else f"{mm / 1000:.3f} m"


def cmd_shutter(a) -> int:
    s = solve_shutter(a.fps, a.angle, a.mains, movie=not a.stills)
    print(f"{a.fps:g} fps @ {a.angle:g} deg -> ideal {s.ideal_seconds * 1000:.2f} ms")
    print(f"use {s.label}  (effective {s.effective_angle:.1f} deg, PTP 0xD20D value 0x{s.ptp_value:08X})")
    if s.flicker_free is not None:
        print(f"flicker-free under {a.mains:g} Hz: {'yes' if s.flicker_free else 'NO'}")
    for w in s.warnings:
        print(f"warning: {w}")
    return 0


def cmd_iso(a) -> int:
    lcg, hcg = native_isos(a.gamma)
    print(f"{a.gamma}: native ISO {lcg} (LCG) / {hcg} (HCG)")
    if a.need:
        print(f"for >= ISO {a.need:g}: use ISO {recommend_iso(a.gamma, a.need)}")
    curve = _curve_for_gamma(a.gamma)
    note = "" if curve != "rec709" else " (Rec.709 approximation)"
    print(f"18% grey sits at {middle_grey_signal(curve) * 100:.1f}% signal{note}")
    return 0


def _curve_for_gamma(gamma: str) -> str:
    g = gamma.lower().replace("-", "")
    if g in ("slog2", "slog3"):
        return g
    return "hlg" if g.startswith("hlg") else "rec709"


def cmd_ei(a) -> int:
    ei = CineEI(a.gamma, a.base)
    print(f"record at ISO {ei.recording_iso}; EI {a.ei:g} -> monitor offset {ei.monitor_offset_ev(a.ei):+.2f} EV")
    return 0


def cmd_dof(a) -> int:
    d = depth_of_field(a.focal, a.f_number, a.distance * 1000, a.coc)
    print(f"hyperfocal {_fmt_mm(hyperfocal(a.focal, a.f_number, a.coc))}")
    print(f"near {_fmt_mm(d.near)}  far {_fmt_mm(d.far)}  total {_fmt_mm(d.total)}")
    return 0


def cmd_bracket(a) -> int:
    plan = focus_bracket_plan(a.focal, a.f_number, a.near * 1000, a.far * 1000, overlap=a.overlap)
    print(f"{len(plan)} shots:")
    for i, d in enumerate(plan, 1):
        print(f"  {i:3d}  {_fmt_mm(d)}")
    return 0


def cmd_af(a) -> int:
    status = check_aperture(a.f_number, movie_mode=not a.stills)
    print(status.message)
    return 0 if status.ok else 2


def cmd_profiles(a) -> int:
    if a.name:
        print(json.dumps(PICTURE_PROFILES[a.name], indent=2))
    else:
        for name, p in PICTURE_PROFILES.items():
            print(f"{name:20s} {p['slot']:5s} {p['gamma']:8s} {p['color_mode']}")
    return 0


def cmd_luts(a) -> int:
    from .color.looks import write_lut_pack

    files = write_lut_pack(a.out, sizes=tuple(a.size))
    print(f"{len(files)} files in {a.out}: S-Log3 / S-Log2 / HLG -> Rec.709, looks technical / cinetone / portrait")
    return 0


def cmd_chart_sample(a) -> int:
    import subprocess
    import tempfile
    from pathlib import Path

    import numpy as np
    from PIL import Image

    from .color.colorchecker import sample_chart

    src = Path(a.image)
    if src.suffix.lower() in (".mp4", ".mov", ".mxf"):  # grab one frame with ffmpeg
        frame = Path(tempfile.mkdtemp()) / "frame.png"
        subprocess.run(["ffmpeg", "-v", "error", "-ss", str(a.at), "-i", str(src), "-frames:v", "1", str(frame)], check=True)
        src = frame
    img = np.asarray(Image.open(src).convert("RGB"), dtype=np.float64) / 255.0
    corners = [tuple(map(float, c.split(","))) for c in a.corners]
    patches = sample_chart(img, corners)
    np.savetxt(a.out, patches, delimiter=",", fmt="%.6f", header="R,G,B signal 0..1, ColorChecker patches 1-24")
    print(f"24 patches -> {a.out}  (white {patches[18].round(3)}, black {patches[23].round(3)})")
    return 0


def _load_patches(path: str):
    import numpy as np

    rows = np.loadtxt(path, delimiter=",", ndmin=2, comments="#")
    if rows.shape[1] != 3:
        raise ValueError(f"{path}: expected 3 columns (R,G,B signal values in 0..1)")
    return rows


def cmd_match(a) -> int:
    from pathlib import Path

    import numpy as np

    from .color.chart_solver import solve_ccm
    from .color.colorimetry import delta_e_2000, linear_rgb_to_lab
    from .color.dctl import lut_dctl
    from .color.lut import build_lut, write_cube
    from .color.residual import fit_residual, match_transform
    from .color.transfer import decode

    src = decode(a.source_curve, _load_patches(a.source))
    if a.target == "colorchecker":  # no reference camera: match X-Rite's published patch values
        from .color.colorchecker import reference_linear

        dst = reference_linear()
    else:
        dst = decode(a.target_curve, _load_patches(a.target))
    if src.shape != dst.shape:
        raise ValueError("source and target must have the same number of patches")
    ccm = solve_ccm(src, dst, degree=a.degree)
    residual = None if a.no_residual else fit_residual(ccm.apply(src), dst)
    final = residual(ccm.apply(src)) if residual else ccm.apply(src)
    de = delta_e_2000(linear_rgb_to_lab(np.clip(final, 0, None)), linear_rgb_to_lab(dst))
    out = Path(a.out)
    write_cube(out, build_lut(match_transform(a.source_curve, a.target_curve, ccm, residual), a.size), title=out.stem)
    out.with_suffix(".dctl").write_text(lut_dctl(out, out.stem))
    print(f"CCM mean dE2000 {ccm.mean_delta_e:.2f}; final mean {de.mean():.2f}, max {de.max():.2f}")
    print(f"wrote {out} and {out.with_suffix('.dctl')}")
    return 0


def cmd_offload(a) -> int:
    from .ingest import offload

    rep = offload(a.source, a.dest, algorithm=a.algorithm, progress=None if a.quiet else lambda rel: print(f"  {rel}"))
    copied = sum(s == "copied" for f in rep.files for s in f.status.values())
    skipped = sum(s == "skipped" for f in rep.files for s in f.status.values())
    print(f"{len(rep.files)} files, {copied} copies made, {skipped} already present ({rep.algorithm})")
    for p in rep.problems():
        print(f"PROBLEM: {p}")
    for m in rep.manifests:
        print(f"manifest: {m}")
    if a.proxies and rep.ok:
        from .media import make_proxies

        lut = None
        if a.look != "none":  # bake a look into the proxies so they arrive graded
            from pathlib import Path

            from .color.looks import look_transform
            from .color.lut import build_lut, write_cube

            source, look = a.look.split(":", 1) if ":" in a.look else ("std709", a.look)
            lut = Path(a.proxies) / f"_look_{source}_{look}.cube"
            lut.parent.mkdir(parents=True, exist_ok=True)
            write_cube(lut, build_lut(look_transform(source, look), 33), title=f"{source} {look}")
        made = make_proxies(a.dest[0], a.proxies, lut=lut)
        print(f"{len(made)} proxies in {a.proxies}" + (f" with look {a.look}" if lut else ""))
    return 0 if rep.ok else 3


def cmd_ptp_check(a) -> int:
    from .ptp import SonyCamera, UsbTransport
    from .ptp.check import as_dicts, run

    if a.sim:
        from .sim import SimTransport, VirtualA7III, walking_subject_scene

        transport = SimTransport(VirtualA7III(walking_subject_scene()))
    else:  # pragma: no cover - needs hardware
        transport = UsbTransport()
    checks = run(SonyCamera(transport), write=a.write, capture=a.capture, record=a.record, frames=a.frames)
    for c in checks:
        print(f"{'SKIP' if c.ok is None else ('PASS' if c.ok else 'FAIL'):5s} {c.name:24s} {c.detail}")
    if a.json:
        from pathlib import Path

        Path(a.json).write_text(json.dumps(as_dicts(checks), indent=2))
        print(f"report: {a.json}")
    return 0 if all(c.ok is not False for c in checks) else 4


def _lan_ips() -> list[str]:
    """Addresses a phone on the same network can reach; the UDP trick needs no packets sent."""
    import socket

    ips = []
    for probe in ("10.255.255.255", "192.168.255.255", "172.31.255.255"):
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect((probe, 1))
            ip = s.getsockname()[0]
            s.close()
            if ip not in ips and not ip.startswith("127."):
                ips.append(ip)
        except OSError:
            pass
    return ips or ["<this computer's IP>"]


def cmd_desk(a) -> int:
    import uvicorn

    from .desk.app import build_sim_rig, create_app

    if a.sim:
        rig = build_sim_rig(a.scene, media_dir=a.media, db=a.db)
    else:  # pragma: no cover - needs hardware
        from .cloud.store import Store
        from .desk.rig import Rig
        from .desk.sources import PTPLiveViewSource, UVCSource
        from .ptp import SonyCamera, UsbTransport

        driver = None
        if a.ptp:
            import time

            while True:  # on a rig the camera may be off at boot: wait for it instead of dying
                try:
                    driver = SonyCamera(UsbTransport())
                    driver.connect()
                    break
                except (ConnectionError, OSError) as e:
                    if not a.wait:
                        raise
                    hint = ""
                    if "Access denied" in str(e):  # another process holds the USB interface
                        hint = " - another program has the camera: close other desks, then `killall ptpcamerad` (macOS)"
                    print(f"camera not ready ({e}){hint}; retrying in 3 s", file=sys.stderr)
                    time.sleep(3)
        source = UVCSource(a.uvc) if a.uvc is not None else PTPLiveViewSource(driver)
        rig = Rig(source, driver=driver, store=Store(a.db), media_dir=a.media)
    urls = [f"http://{ip}:{a.port}" for ip in _lan_ips()] if a.host == "0.0.0.0" else [f"http://{a.host}:{a.port}"]
    print(f"A7III Control Desk on {' or '.join(urls)}  ({'simulated camera' if a.sim else 'hardware'})")
    if a.host == "0.0.0.0":
        print("on your phone, open that address in Safari, then Share -> Add to Home Screen")
    if a.ptp:
        from pathlib import Path

        print(f"Record: full-quality clip on the camera's SD card; low-res reference copy in {Path(a.media).resolve()}")
    uvicorn.run(create_app(rig, loop_fps=a.fps), host=a.host, port=a.port, log_level="warning")
    return 0


def cmd_cloud(a) -> int:
    import uvicorn

    from .cloud.api import create_app

    uvicorn.run(create_app(a.db, a.token), host=a.host, port=a.port, log_level="warning")
    return 0


def _nvram_backend(a):
    if a.sim:
        from .sim.nvram import PersistentSimBackend

        return PersistentSimBackend(a.sim)
    raise SystemExit(
        "No hardware Senser backend ships with this project on purpose: writing NVRAM through\n"
        "unverified service-mode code can brick a body. Use --sim IMAGE to rehearse, and see\n"
        "docs/ROADMAP_REVIEW.md for what must be verified before a hardware backend is added."
    )


def cmd_nvram(a) -> int:
    from .nvram import TWEAKS, NvramBackup, NvramService

    if a.action == "tweaks":
        for t in TWEAKS.values():
            state = f"{len(t.prop_ids)} props" if t.available else "LOCKED (no verified property ID)"
            print(f"{t.key:18s} {state:34s} {t.description}")
        return 0
    if a.action == "verify":
        b = NvramBackup.load(a.backup)
        print(f"OK {b.model} #{b.serial}: {len(b.props)} properties, sha256 {b.sha256}")
        return 0
    svc = NvramService(_nvram_backend(a))
    if a.action == "dump":
        path = svc.dump().save(a.out)
        print(f"read-only dump written to {path}")
        return 0
    backup = NvramBackup.load(a.backup)
    if a.action == "apply":
        writes = svc.plan(a.tweak)
        report = svc.apply(writes, backup, dry_run=not a.yes)
    else:  # restore
        report = svc.restore(backup, dry_run=not a.yes)
    changes = [w for w in report.planned if w.changes]
    print(f"{len(changes)} of {len(report.planned)} properties would change")
    for w in changes[:10]:
        print(f"  0x{w.prop_id:08x}: {w.old.hex()} -> {w.new.hex()}")
    if report.dry_run:
        print("dry run - nothing written. Re-run with --yes to write.")
    else:
        print(f"wrote and verified {len(report.written)} properties, committed with sync."
              " Power-cycle the camera (remove the battery for 10 s).")
    return 0


def cmd_sim(a) -> int:
    from .sim.scenarios import run_all, scenario_keys

    if a.list:
        print("\n".join(scenario_keys()))
        return 0
    only = a.only.split(",") if a.only else None
    if only:
        unknown = set(only) - set(scenario_keys())
        if unknown:
            raise ValueError(f"unknown scenarios: {sorted(unknown)}")
    results = run_all(a.out, only, progress=lambda r: print(f"{r.status:7s} {r.seconds:5.1f}s  {r.title}", flush=True))
    counts = {s: sum(r.status == s for r in results) for s in ("PASS", "FAIL", "BLOCKED", "LIMIT")}
    print(f"\n{counts['PASS']} passed, {counts['FAIL']} failed, {counts['BLOCKED']} blocked, "
          f"{counts['LIMIT']} silicon limits -> {a.out}/report.md")
    return 0 if counts["FAIL"] == 0 else 4


def cmd_readout(a) -> int:
    for mode, ms in READOUT_MS.items():
        print(f"{mode:14s} {ms:5.1f} ms")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="a7iii", description="Sony a7 III companion tools")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("shutter", help="shutter-angle lock with anti-flicker")
    s.add_argument("--fps", type=float, required=True)
    s.add_argument("--angle", type=float, default=180.0)
    s.add_argument("--mains", type=float, choices=[50.0, 60.0], help="mains frequency for flicker-free snapping")
    s.add_argument("--stills", action="store_true", help="allow speeds slower than the frame interval")
    s.set_defaults(func=cmd_shutter)

    s = sub.add_parser("iso", help="native (dual conversion gain) ISOs for a gamma")
    s.add_argument("gamma")
    s.add_argument("--need", type=float, help="minimum ISO required")
    s.set_defaults(func=cmd_iso)

    s = sub.add_parser("ei", help="Cine EI monitoring offset")
    s.add_argument("gamma")
    s.add_argument("ei", type=float)
    s.add_argument("--base", choices=["low", "high"], default="low")
    s.set_defaults(func=cmd_ei)

    s = sub.add_parser("dof", help="depth of field")
    s.add_argument("--focal", type=float, required=True, help="mm")
    s.add_argument("--f-number", type=float, required=True)
    s.add_argument("--distance", type=float, required=True, help="metres")
    s.add_argument("--coc", type=float, default=COC_FULL_FRAME_MM, help="mm")
    s.set_defaults(func=cmd_dof)

    s = sub.add_parser("bracket", help="focus-stacking plan")
    s.add_argument("--focal", type=float, required=True)
    s.add_argument("--f-number", type=float, required=True)
    s.add_argument("--near", type=float, required=True, help="metres")
    s.add_argument("--far", type=float, required=True, help="metres")
    s.add_argument("--overlap", type=float, default=0.1)
    s.set_defaults(func=cmd_bracket)

    s = sub.add_parser("af-guard", help="check PDAF availability for an aperture")
    s.add_argument("f_number", type=float)
    s.add_argument("--stills", action="store_true")
    s.set_defaults(func=cmd_af)

    s = sub.add_parser("profiles", help="list or show picture-profile recipes")
    s.add_argument("name", nargs="?", choices=sorted(PICTURE_PROFILES))
    s.set_defaults(func=cmd_profiles)

    s = sub.add_parser("luts", help="write the FX-style LUT pack (log/HLG -> Rec.709 looks)")
    s.add_argument("--out", default="luts")
    s.add_argument("--size", type=int, nargs="+", default=[33, 65], help="LUT sizes")
    s.set_defaults(func=cmd_luts)

    s = sub.add_parser("chart-sample", help="read the 24 ColorChecker patches from a still or clip into a CSV")
    s.add_argument("image", help="PNG/JPEG/TIFF still, or MP4/MOV clip (one frame is grabbed)")
    s.add_argument("--corners", nargs=4, required=True, metavar="X,Y",
                   help="pixel centres of dark skin, bluish green, white, black")
    s.add_argument("--at", type=float, default=1.0, help="seconds into a clip")
    s.add_argument("--out", default="patches.csv")
    s.set_defaults(func=cmd_chart_sample)

    s = sub.add_parser("match", help="chart-match two cameras into a .cube LUT + DCTL")
    s.add_argument("--source", required=True, help="CSV of source patch R,G,B (signal 0..1)")
    s.add_argument("--target", required=True,
                   help="CSV of reference patch R,G,B (signal 0..1), or 'colorchecker' for the built-in "
                        "X-Rite values (use with --target-curve rec709)")
    s.add_argument("--source-curve", default="hlg", choices=["slog2", "slog3", "hlg", "rec709"])
    s.add_argument("--target-curve", default="slog3", choices=["slog2", "slog3", "hlg", "rec709"])
    s.add_argument("--degree", type=int, default=1, choices=[1, 2, 3])
    s.add_argument("--size", type=int, default=65, help="LUT size (33 or 65)")
    s.add_argument("--no-residual", action="store_true", help="skip the OKLab RBF stage")
    s.add_argument("--out", default="a7iii_match.cube")
    s.set_defaults(func=cmd_match)

    s = sub.add_parser("offload", help="verified copy of a card to one or more destinations")
    s.add_argument("source")
    s.add_argument("dest", nargs="+")
    s.add_argument("--algorithm", choices=["xxh3_128", "sha256", "blake2b"])
    s.add_argument("--quiet", action="store_true")
    s.add_argument("--proxies", help="after a clean offload, make H.264 proxies of video files into this folder")
    s.add_argument("--look", default="fxdefault",
                   help="look baked into proxies: LOOK for default-mode footage, or SOURCE:LOOK "
                        "(e.g. slog3:cinetone); 'none' for untouched proxies")
    s.set_defaults(func=cmd_offload)

    s = sub.add_parser("ptp-check", help="validate what the connected camera accepts over PTP (read-only by default)")
    s.add_argument("--write", action="store_true", help="also set exposure to a neighbouring value, read back, restore")
    s.add_argument("--capture", action="store_true", help="also take one still")
    s.add_argument("--record", action="store_true", help="also record a ~2 s clip")
    s.add_argument("--frames", type=int, default=30, help="live-view frames to pull")
    s.add_argument("--json", help="write the report here")
    s.add_argument("--sim", action="store_true", help="run against the virtual a7 III")
    s.set_defaults(func=cmd_ptp_check)

    s = sub.add_parser("desk", help="run the A7III Control Desk web app")
    s.add_argument("--sim", action="store_true", help="use the virtual a7 III")
    s.add_argument("--scene", default="walking", choices=["walking", "approaching", "chart", "wall"])
    s.add_argument("--uvc", type=int, help="HDMI capture device index")
    s.add_argument("--ptp", action="store_true", help="control the camera over USB PTP")
    s.add_argument("--wait", action="store_true", help="with --ptp: keep retrying until the camera appears (rig/boot use)")
    s.add_argument("--host", default="127.0.0.1")
    s.add_argument("--port", type=int, default=8000)
    s.add_argument("--fps", type=float, default=12.0, help="desk refresh rate")
    s.add_argument("--db", default="a7iii_desk.sqlite")
    s.add_argument("--media", default="takes")
    s.set_defaults(func=cmd_desk)

    s = sub.add_parser("cloud", help="run the cloud sync API")
    s.add_argument("--db", default="a7iii_sync.sqlite")
    s.add_argument("--token", default=None, help="bearer token (or A7III_SYNC_TOKEN)")
    s.add_argument("--host", default="0.0.0.0")
    s.add_argument("--port", type=int, default=8080)
    s.set_defaults(func=cmd_cloud)

    s = sub.add_parser("nvram", help="guarded service-mode NVRAM tool (backup first, allowlist only)")
    s.add_argument("action", choices=["tweaks", "dump", "apply", "restore", "verify"])
    s.add_argument("tweak", nargs="?", help="tweak key for apply (see 'tweaks')")
    s.add_argument("--sim", metavar="IMAGE", help="use a simulated camera NVRAM image (JSON, created if missing)")
    s.add_argument("--backup", help="sealed backup JSON (required for apply/restore/verify)")
    s.add_argument("--out", default=".", help="folder for dump")
    s.add_argument("--yes", action="store_true", help="actually write (default is a dry run)")
    s.set_defaults(func=cmd_nvram)

    s = sub.add_parser("sim", help="run the end-to-end simulation of every roadmap feature")
    s.add_argument("--out", default="sim_report", help="folder for report.md, report.json and images")
    s.add_argument("--only", help="comma-separated scenario keys")
    s.add_argument("--list", action="store_true", help="list scenario keys")
    s.set_defaults(func=cmd_sim)

    s = sub.add_parser("readout", help="rolling-shutter readout times")
    s.set_defaults(func=cmd_readout)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except (ValueError, PermissionError) as e:  # PermissionError covers refused NVRAM writes
        print(f"error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
