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
    return 0 if rep.ok else 3


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

    s = sub.add_parser("match", help="chart-match two cameras into a .cube LUT + DCTL")
    s.add_argument("--source", required=True, help="CSV of source patch R,G,B (signal 0..1)")
    s.add_argument("--target", required=True, help="CSV of reference patch R,G,B (signal 0..1)")
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
    s.set_defaults(func=cmd_offload)

    s = sub.add_parser("readout", help="rolling-shutter readout times")
    s.set_defaults(func=cmd_readout)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
