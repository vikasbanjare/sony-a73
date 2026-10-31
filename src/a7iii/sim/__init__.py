"""Virtual Sony a7 III for testing every tool without hardware.

- ``scene``: procedural 3D scenes (subject, chart, macro plane, flicker)
- ``camera``: ``VirtualA7III`` - optics, IMX410-like sensor with dual gain, AF
- ``ptp_device``: ``SimTransport`` - speaks Sony PTP to the real driver
- ``imu``: handheld motion + BMI270-like gyro with clock offset
- ``detector``: ground-truth stand-in for YOLO-pose
- ``scenarios``: end-to-end checks of every roadmap feature (``a7iii sim``)
"""

from .camera import Frame, Lens, VirtualA7III
from .detector import GroundTruthDetector
from .imu import HandheldMotion, SimulatedIMU
from .ptp_device import SimTransport
from .scene import Scene, approaching_subject_scene, chart_scene, macro_scene, walking_subject_scene


class SimClock:
    """Clock for ``ptp.automation`` that advances the simulated camera."""

    def __init__(self, camera: VirtualA7III, record: bool = True):
        self.camera = camera
        self.record = record

    def now(self) -> float:
        return self.camera.t

    def sleep(self, seconds: float) -> None:
        self.camera.advance(seconds, record=self.record)


def connect_simulated(scene: Scene | None = None, **camera_kwargs):
    """Return (SonyCamera driver, VirtualA7III) wired together over SimTransport."""
    from ..ptp.session import SonyCamera

    cam = VirtualA7III(scene or walking_subject_scene(), **camera_kwargs)
    drv = SonyCamera(SimTransport(cam))
    drv.connect()
    return drv, cam


__all__ = [
    "Frame",
    "GroundTruthDetector",
    "HandheldMotion",
    "Lens",
    "Scene",
    "SimClock",
    "SimTransport",
    "SimulatedIMU",
    "VirtualA7III",
    "approaching_subject_scene",
    "chart_scene",
    "connect_simulated",
    "macro_scene",
    "walking_subject_scene",
]
