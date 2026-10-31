"""Camera automation over PTP (roadmap §5.3, §7, §8.1, §10.3).

Every routine takes a ``SonyCamera`` and a ``Clock``. ``WallClock`` sleeps
in real time for hardware; the simulator supplies a clock that advances
simulated time instead, so the exact same code is exercised in tests.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Callable, Protocol

from ..cinema.cine_ei import CineEI
from ..cinema.shutter import ShutterSolution, solve_shutter
from ..optics.af_guard import AFGuardStatus, check_aperture, f_number_from_ptp
from ..optics.dof import focus_bracket_plan
from ..optics.rack_focus import EASE_IN_OUT, rack_schedule
from .session import SonyCamera


class Clock(Protocol):
    def now(self) -> float: ...
    def sleep(self, seconds: float) -> None: ...


class WallClock:
    def now(self) -> float:
        return time.monotonic()

    def sleep(self, seconds: float) -> None:
        time.sleep(max(0.0, seconds))


# --- exposure ------------------------------------------------------------------


def apply_shutter_angle(cam: SonyCamera, fps: float, angle: float = 180.0, mains_hz: float | None = None) -> ShutterSolution:
    """Solve the shutter angle and push the chosen speed to the camera."""
    sol = solve_shutter(fps, angle, mains_hz, movie=True)
    cam.set_prop("shutter_speed", sol.ptp_value)
    return sol


def apply_cine_ei(cam: SonyCamera, gamma: str, base: str = "low") -> CineEI:
    """Lock the recording ISO to a native (LCG/HCG) value."""
    ei = CineEI(gamma, base)
    cam.set_prop("iso", ei.recording_iso)
    return ei


# --- PDAF guard ------------------------------------------------------------------


@dataclass
class ApertureGuard:
    cam: SonyCamera
    movie_mode: bool = True
    on_change: Callable[[AFGuardStatus], None] | None = None
    last: AFGuardStatus | None = None

    def poll(self) -> AFGuardStatus:
        f = f_number_from_ptp(self.cam.get_value("f_number"))
        status = check_aperture(f, self.movie_mode)
        if self.on_change and (self.last is None or status.ok != self.last.ok):
            self.on_change(status)
        self.last = status
        return status

    def run(self, clock: Clock, duration_s: float, rate_hz: float = 10.0) -> list[AFGuardStatus]:
        out = []
        for _ in range(max(1, round(duration_s * rate_hz))):
            out.append(self.poll())
            clock.sleep(1.0 / rate_hz)
        return out


# --- focus motor helpers -----------------------------------------------------------


@dataclass
class FocusMotorModel:
    """How the body's near/far step commands map to motor steps.

    ``step_sizes`` must be calibrated per body/lens on hardware (send one
    command of each size and watch the distance scale); defaults match the
    simulator.
    """

    step_sizes: dict[int, int] = field(default_factory=lambda: {1: 1, 2: 3, 3: 10, 4: 20, 5: 40, 6: 80, 7: 160})

    def decompose(self, steps: int) -> list[int]:
        """Signed near/far command values that move ``steps`` motor steps (+ = far)."""
        out: list[int] = []
        remaining = abs(steps)
        sign = 1 if steps > 0 else -1
        for cmd, size in sorted(self.step_sizes.items(), key=lambda kv: -kv[1]):
            while remaining >= size:
                out.append(sign * cmd)
                remaining -= size
        return out


def move_focus(cam: SonyCamera, steps: int, motor: FocusMotorModel, clock: Clock | None = None,
               settle_s: float = 0.0) -> int:
    cmds = motor.decompose(steps)
    for c in cmds:
        cam.focus_step(c)
        if clock and settle_s:
            clock.sleep(settle_s)
    return len(cmds)


# --- focus bracketing (stills) -------------------------------------------------------


@dataclass
class LensFocusMap:
    """Distance <-> motor-step mapping for a lens (calibrated, or from a lens model)."""

    distance_for_step: Callable[[float], float]
    step_for_distance: Callable[[float], float]
    max_step: int = 1000


def focus_bracket(
    cam: SonyCamera,
    clock: Clock,
    focal_mm: float,
    f_number: float,
    near_mm: float,
    far_mm: float,
    lens_map: LensFocusMap,
    motor: FocusMotorModel | None = None,
    overlap: float = 0.1,
    settle_s: float = 0.15,
) -> list[float]:
    """Plan a stack, drive focus to each slice and fire a still. Returns the planned distances.

    The camera must be in photo mode with MF selected. Starts by racking fully
    near so the motor position is known (open-loop stepping thereafter).
    """
    motor = motor or FocusMotorModel()
    plan = focus_bracket_plan(focal_mm, f_number, near_mm, far_mm, overlap=overlap)
    cam.set_prop("focus_mode", 1)  # MF
    move_focus(cam, -lens_map.max_step - 200, motor)  # hard stop at MFD = step 0
    position = 0
    for d in plan:
        target = round(lens_map.step_for_distance(d))
        move_focus(cam, target - position, motor)
        position = target
        clock.sleep(settle_s)
        cam.press("shutter_release", hold_s=0)
        clock.sleep(settle_s)
    return plan


# --- rack focus (movie) ----------------------------------------------------------------


def rack_focus(cam: SonyCamera, clock: Clock, total_steps: int, duration_s: float, tick_hz: float = 30.0,
               motor: FocusMotorModel | None = None, ease=EASE_IN_OUT) -> list[int]:
    """Execute an eased A->B focus pull by streaming near/far commands."""
    motor = motor or FocusMotorModel()
    if 1 not in motor.step_sizes or motor.step_sizes[1] != 1:
        raise ValueError("rack focus needs a 1-step command to place every step exactly")
    schedule = rack_schedule(total_steps, duration_s, tick_hz, ease)
    for steps in schedule:
        move_focus(cam, steps, motor)
        clock.sleep(1.0 / tick_hz)
    return schedule


# --- AF sink -----------------------------------------------------------------------------


class PtpAFSink:
    """``AFController`` sink that moves the camera's AF point over PTP."""

    def __init__(self, cam: SonyCamera):
        self.cam = cam
        self.sent = 0

    def __call__(self, u: float, v: float) -> None:
        self.cam.set_af_point(u, v)
        self.sent += 1


__all__ = [
    "ApertureGuard",
    "Clock",
    "FocusMotorModel",
    "LensFocusMap",
    "PtpAFSink",
    "WallClock",
    "apply_cine_ei",
    "apply_shutter_angle",
    "focus_bracket",
    "move_focus",
    "rack_focus",
]
