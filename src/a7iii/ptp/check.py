"""Real-camera PTP validation (roadmap §6.3 / PTP-02..04): what does this body actually accept?

Read-only by default. ``write=True`` changes exposure settings to a neighbouring
value, reads them back and restores the original; ``capture`` takes one still and
``record`` a 2 s clip (both land on the card). Every step is recorded, failures
included, so the report doubles as the supported-property matrix.
"""

from __future__ import annotations

import time
from dataclasses import asdict, dataclass

from .codes import PROPS
from .session import STEP_KEYS, PTPError, SonyCamera, extract_jpeg

WRITE_TESTS = ("white_balance", "exposure_bias", "shutter_speed", "iso", "f_number")


@dataclass
class Check:
    name: str
    ok: bool | None  # None = skipped
    detail: str


def _neighbour(desc) -> int | None:
    """A different legal value next to the current one, or None if there is none."""
    if desc.values:
        vals = list(desc.values)
        if desc.value in vals:
            i = vals.index(desc.value)
            return vals[i + 1] if i + 1 < len(vals) else (vals[i - 1] if i else None)
        return vals[0] if vals[0] != desc.value else None
    if desc.range:
        lo, hi, step = desc.range
        step = step or 1
        return desc.value + step if desc.value + step <= hi else (desc.value - step if desc.value - step >= lo else None)
    return None


def _liveview(cam: SonyCamera, frames: int) -> Check:
    denied = 0
    got = 0
    t0 = time.monotonic()
    deadline = t0 + 10 + frames
    while got < frames and time.monotonic() < deadline:
        try:
            if extract_jpeg(cam.liveview_frame()):
                got += 1
        except PTPError as e:
            if e.code != 0x200F:
                return Check("live view", False, f"{got} frames, then {e}")
            denied += 1  # Access Denied until live view is ready
            time.sleep(0.2)
    fps = got / max(time.monotonic() - t0, 1e-6)
    return Check("live view", got == frames, f"{got}/{frames} frames, {fps:.1f} fps, {denied} access-denied retries")


def run(cam: SonyCamera, write: bool = False, capture: bool = False, record: bool = False,
        frames: int = 30, settle_s: float = 3.0) -> list[Check]:
    out: list[Check] = []
    codes = cam.connect()
    out.append(Check("connect", True, f"{len(codes)} property codes"))
    try:
        props = cam.get_props()
    except Exception as e:  # the descriptor layout is the least-verified part of the protocol
        out.append(Check("read properties", False, f"{type(e).__name__}: {e}"))
        return out
    out.append(Check("read properties", True, f"{len(props)} descriptors parsed"))
    for name, p in PROPS.items():
        d = props.get(p.code)
        if d is None:
            out.append(Check(f"prop {name}", None, f"0x{p.code:04X} not reported"))
        else:
            choices = f", {len(d.values)} choices" if d.values else (f", range {d.range}" if d.range else "")
            out.append(Check(f"prop {name}", True, f"value {d.value}, {'writable' if d.writable else 'read-only'}{choices}"))
    out.append(_liveview(cam, frames))

    if write:
        for name in WRITE_TESTS:
            d = props.get(PROPS[name].code)
            if d is not None and not d.writable and name in STEP_KEYS:  # a7 III: one stop per step
                try:
                    up = cam.step(name, 1)
                    back = cam.step(name, -1) if up != d.value else up
                    out.append(Check(f"step {name}", up != d.value and back == d.value,
                                     f"{d.value} -> {up} -> {back} (step control)"))
                except PTPError as e:
                    out.append(Check(f"step {name}", False, str(e)))
                continue
            new = _neighbour(d) if d is not None and d.writable else None
            if new is None:
                out.append(Check(f"write {name}", None, "not reported, read-only or no other value"))
                continue
            old = d.value
            try:
                cam.set_prop(name, new)
                now = cam.wait_value(name, new, settle_s)
                cam.set_prop(name, old)
                back = cam.wait_value(name, old, settle_s)
                out.append(Check(f"write {name}", now == new and back == old,
                                 f"{old} -> {new}: read {now}; restored -> read {back}"))
            except PTPError as e:
                out.append(Check(f"write {name}", False, f"{old} -> {new}: {e}"))
        try:
            cam.focus_step(1)
            cam.focus_step(-1)
            out.append(Check("focus step", True, "near/far +1 then -1 accepted"))
        except PTPError as e:
            out.append(Check("focus step", False, str(e)))
    if capture:
        try:
            cam.press("half_press", hold_s=0.5)
            cam.press("shutter_release", hold_s=0.2)
            out.append(Check("shutter release", True, "accepted; check the card for the still"))
        except PTPError as e:
            out.append(Check("shutter release", False, str(e)))
    if record:
        try:
            cam.press("movie_record")
            time.sleep(2.0)
            cam.press("movie_record")
            out.append(Check("movie record", True, "start/stop accepted; check the card for a ~2 s clip"))
        except PTPError as e:
            out.append(Check("movie record", False, str(e)))
    return out


def as_dicts(checks: list[Check]) -> list[dict]:
    return [asdict(c) for c in checks]
