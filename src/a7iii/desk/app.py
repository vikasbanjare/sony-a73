"""A7III Control Desk web app (roadmap packages/06-cinema-control-desk).

    a7iii desk --sim            # virtual camera, open http://localhost:8000
    a7iii desk --uvc 0 --ptp    # HDMI capture card + USB PTP control

The browser gets the untouched camera signal as JPEG over a WebSocket and
does false colour / Cine EI / de-squeeze in a WebGL shader; the same views
are also available server-rendered at /api/view/{view}.jpg.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
from pathlib import Path

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel

from ..cloud.api import make_router
from ..color.lut import build_lut, write_cube
from .rig import VIEWS, Rig
from .sources import encode_jpeg

STATIC = Path(__file__).with_name("static")


class SettingsIn(BaseModel):
    fps: float | None = None
    angle: float | None = None
    mains_hz: float | None = None
    gamma: str | None = None
    ei_base: str | None = None
    ei: float | None = None
    squeeze: float | None = None
    guides: bool | None = None
    ai_af: bool | None = None
    preroll_s: float | None = None
    take_codec: str | None = None


class AFPoint(BaseModel):
    u: float
    v: float


class RackIn(BaseModel):
    steps: int
    duration_s: float = 2.0


def create_app(rig: Rig, autorun: bool = True, loop_fps: float = 12.0) -> FastAPI:
    clients: set[WebSocket] = set()
    lock = asyncio.Lock()

    async def capture_loop():
        while True:
            try:
                async with lock:
                    telemetry = await asyncio.to_thread(rig.tick)
                jpeg = rig.last_jpeg
                for ws in list(clients):
                    try:
                        await ws.send_bytes(jpeg)
                        await ws.send_text(json.dumps({"telemetry": telemetry}))
                    except Exception:
                        clients.discard(ws)
            except Exception as e:  # keep the desk alive; surface the error to clients
                rig.messages.append(f"capture error: {e}")
            await asyncio.sleep(1.0 / loop_fps)

    @contextlib.asynccontextmanager
    async def lifespan(app: FastAPI):
        # opening the desk must not change a real camera's exposure; only an edit in the desk pushes
        rig.apply_settings(push=rig.sim is not None)
        task = asyncio.create_task(capture_loop()) if autorun else None
        yield
        if task:
            task.cancel()

    app = FastAPI(title="A7III Control Desk", lifespan=lifespan)
    app.include_router(make_router(rig.store, token=""), prefix="/cloud/v1")

    @app.get("/")
    def index():
        return FileResponse(STATIC / "index.html")

    @app.get("/static/{name}")  # manifest + icon for "Add to Home Screen"
    def static_file(name: str):
        path = STATIC / name
        if not path.is_file() or path.name != name:
            raise HTTPException(404)
        return FileResponse(path)

    @app.get("/api/state")
    def state():
        return rig.state()

    @app.post("/api/settings")
    async def settings(body: SettingsIn):
        changes = {k: v for k, v in body.model_dump().items() if v is not None}
        if "mains_hz" in changes and changes["mains_hz"] == 0:
            changes["mains_hz"] = None
        async with lock:
            try:
                return await asyncio.to_thread(rig.apply_settings, **changes)
            except ValueError as e:
                raise HTTPException(400, str(e))

    @app.post("/api/tick")
    async def tick():
        """Advance one frame (useful when autorun is off, e.g. tests)."""
        async with lock:
            return await asyncio.to_thread(rig.tick)

    @app.post("/api/record/start")
    async def record_start(preroll: bool = False):
        async with lock:
            try:
                return {"uid": rig.start_take(include_preroll=preroll)}
            except RuntimeError as e:
                raise HTTPException(409, str(e))

    @app.post("/api/record/stop")
    async def record_stop():
        async with lock:
            try:
                return await asyncio.to_thread(rig.stop_take)
            except RuntimeError as e:
                raise HTTPException(409, str(e))

    @app.get("/api/takes")
    def takes():
        return rig.store.takes()

    @app.get("/api/events")
    def events():
        return rig.store.events()

    @app.post("/api/af/point")
    async def af_point(p: AFPoint):
        if rig.driver is None:
            raise HTTPException(409, "no camera connected")
        async with lock:
            rig.driver.set_af_point(p.u, p.v)
        return {"ok": True}

    @app.post("/api/focus/rack")
    async def rack(body: RackIn):
        if rig.driver is None:
            raise HTTPException(409, "no camera connected")
        from ..ptp.automation import WallClock, rack_focus

        clock = WallClock()
        if rig.sim is not None:
            from ..sim import SimClock

            clock = SimClock(rig.sim, record=False)
        async with lock:
            sched = await asyncio.to_thread(rack_focus, rig.driver, clock, body.steps, body.duration_s)
        return {"ticks": len(sched)}

    @app.get("/api/frame.jpg")
    def frame():
        if rig.last_jpeg is None:
            raise HTTPException(404, "no frame yet")
        return Response(rig.last_jpeg, media_type="image/jpeg")

    @app.get("/api/view/{view}.jpg")
    def view(view: str):
        if view not in VIEWS:
            raise HTTPException(404, f"views: {VIEWS}")
        try:
            return Response(encode_jpeg(rig.render_view(view)), media_type="image/jpeg")
        except (ValueError, RuntimeError) as e:
            raise HTTPException(409, str(e))

    @app.get("/api/scope/{kind}.png")
    def scope(kind: str):
        try:
            return Response(rig.scope_png(kind), media_type="image/png")
        except ValueError as e:
            raise HTTPException(404, str(e))
        except RuntimeError as e:
            raise HTTPException(409, str(e))

    @app.get("/api/lut/monitor.cube")
    def monitor_lut(ei: float | None = None, size: int = 33):
        import tempfile

        from ..cinema.cine_ei import monitor_transform
        from .rig import curve_for_gamma

        offset = rig.cine_ei().monitor_offset_ev(ei) if ei else 0.0
        table = build_lut(monitor_transform(curve_for_gamma(rig.settings.gamma), offset), size)
        with tempfile.NamedTemporaryFile(suffix=".cube") as tmp:
            write_cube(tmp.name, table, title=f"a7iii_monitor_EI{ei or 'base'}")
            return Response(Path(tmp.name).read_text(), media_type="text/plain")

    @app.websocket("/ws")
    async def ws(socket: WebSocket):
        await socket.accept()
        clients.add(socket)
        try:
            while True:
                await socket.receive_text()  # keepalive / ignored
        except WebSocketDisconnect:
            clients.discard(socket)

    return app


def build_sim_rig(scene: str = "walking", media_dir: str = "takes", db: str = ":memory:") -> Rig:
    """A Rig wired to the virtual a7 III through the real PTP driver."""
    from ..cloud.store import Store
    from ..sim import GroundTruthDetector, approaching_subject_scene, chart_scene, connect_simulated, walking_subject_scene
    from ..sim.scene import Scene
    from .sources import SimSource

    scenes = {
        "walking": lambda: walking_subject_scene(speed_mps=0.25, start_x=-0.5, depth=2.2, ev100=8.6, flicker_hz=50),
        "approaching": lambda: approaching_subject_scene(ev100=8.6),
        "chart": chart_scene,
        "wall": lambda: Scene(ev100=8.6, flicker_hz=50),
    }
    drv, cam = connect_simulated(scenes[scene](), width=384, height=216)
    drv.set_prop("f_number", 280)
    rig = Rig(SimSource(cam), driver=drv, store=Store(db), detector=GroundTruthDetector(), sim_camera=cam,
              media_dir=media_dir)
    return rig
