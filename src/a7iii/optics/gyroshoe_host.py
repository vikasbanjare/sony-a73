"""Host side of the A7III-GyroShoe serial protocol (see firmware/gyroshoe/gyroshoe.ino).

    link = GyroShoeLink(serial.Serial("/dev/ttyACM0", 115200, timeout=1))
    link.start("A001C003", unix_ms)   # when the desk starts recording
    link.mark(unix_ms)
    link.stop()

``SimulatedGyroShoe`` implements the same protocol in Python on top of the
IMU simulator, writing real ``.gcsv`` files, so the desk and tests run the
whole sync path without hardware.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

from .gyro import GcsvLog, bmi270_scales, write_gcsv


class GyroShoeError(RuntimeError):
    pass


class GyroShoeLink:
    def __init__(self, port):
        self.port = port  # pyserial Serial or anything with write(bytes) / readline() -> bytes

    def _cmd(self, line: str) -> str:
        self.port.write((line + "\n").encode())
        reply = self.port.readline().decode(errors="replace").strip()
        if not reply.startswith("OK"):
            raise GyroShoeError(f"{line!r} -> {reply or 'no reply'}")
        return reply

    def start(self, name: str, unix_ms: int) -> None:
        if not name or any(c in name for c in " /\\\n"):
            raise ValueError("take name must be a single path-safe token")
        self._cmd(f"START {name} {unix_ms}")

    def stop(self) -> tuple[int, int]:
        parts = self._cmd("STOP").split()
        return int(parts[2]), int(parts[3])

    def mark(self, unix_ms: int) -> None:
        self._cmd(f"MARK {unix_ms}")

    def status(self) -> dict:
        _, logging, samples, dropped = self._cmd("STATUS").split()
        return {"logging": logging == "1", "samples": int(samples), "dropped": int(dropped)}


class SimulatedGyroShoe:
    """Serial-port stand-in running the firmware's protocol against simulated motion."""

    def __init__(self, sd_dir: str | Path, motion, imu, clock):
        self.sd = Path(sd_dir)
        self.sd.mkdir(parents=True, exist_ok=True)
        self.motion, self.imu, self.clock = motion, imu, clock  # clock() -> camera-time seconds
        self._replies: list[bytes] = []
        self._take: tuple[str, float] | None = None
        self._marks: list[tuple[str, int, float]] = []

    def write(self, data: bytes) -> int:
        for line in data.decode().splitlines():
            self._replies.append((self._handle(line.strip()) + "\n").encode())
        return len(data)

    def readline(self) -> bytes:
        return self._replies.pop(0) if self._replies else b""

    def _handle(self, cmd: str) -> str:
        now = self.clock()
        if cmd.startswith("START "):
            if self._take:
                return "ERR already logging"
            name = cmd.split()[1]
            self._take = (name, now)
            self._marks = []
            return f"OK START {name}"
        if cmd == "STOP":
            if not self._take:
                return "ERR not logging"
            name, t0 = self._take
            self._take = None
            t_imu, gyro = self.imu.sample(self.motion, t0, now)
            gscale, ascale = bmi270_scales()
            # Firmware stores counts; quantise exactly as it would.
            gyro = np.round(gyro / gscale) * gscale
            accel = np.tile([0.0, -1.0, 0.0], (len(t_imu), 1))
            write_gcsv(self.sd / f"{name}.gcsv",
                       GcsvLog(t_imu, gyro, accel, orientation="YxZ", header={"note": f"take={name}"}))
            with open(self.sd / f"{name}.marks.csv", "w") as f:
                f.write("kind,unix_ms,t_us\n")
                for kind, ms, t in self._marks:
                    f.write(f"{kind},{ms},{int((t - t0) * 1e6)}\n")
            return f"OK STOP {len(t_imu)} 0"
        if cmd.startswith("MARK "):
            if self._take:
                self._marks.append(("mark", int(cmd.split()[1]), now))
            return "OK MARK"
        if cmd == "STATUS":
            return f"OK {1 if self._take else 0} 0 0"
        return "ERR unknown command"
