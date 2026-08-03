import asyncio
import contextlib

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from . import recordings, storage, system
from .api import auth as auth_api
from .api import cameras as cameras_api
from .api import recordings as recordings_api
from .api import storage as storage_api
from .api import system as system_api
from .api import tunnel as tunnel_api
from .auth import authenticated, is_configured
from .cameras.manager import manager
from .cameras.source import preferred_encoder
from .config import WEB_DIR, config
from .events import bus
from .tunnel import tunnel

INDEX_INTERVAL = 30
HEARTBEAT_INTERVAL = 5


async def _indexer():
    while True:
        await asyncio.sleep(INDEX_INTERVAL)
        with contextlib.suppress(Exception):
            await recordings.scan()
            await recordings.enforce_retention()


async def _heartbeat():
    while True:
        await asyncio.sleep(HEARTBEAT_INTERVAL)
        with contextlib.suppress(Exception):
            bus.publish(
                {
                    "type": "stats",
                    "system": system.stats(),
                    "storage": storage.summary(),
                    "encoder": preferred_encoder(),
                    "port": int(config.section("server").get("port") or 8080),
                    "cameras": {camera["id"]: manager.status(camera["id"]) for camera in config.cameras()},
                }
            )


@contextlib.asynccontextmanager
async def lifespan(_app):
    recordings.init()
    for camera in config.cameras():
        storage.ensure_camera_dirs(camera["id"])
    await manager.sync()
    await tunnel.autostart()
    tasks = [asyncio.create_task(_indexer()), asyncio.create_task(_heartbeat())]
    try:
        yield
    finally:
        for task in tasks:
            task.cancel()
        for task in tasks:
            with contextlib.suppress(asyncio.CancelledError):
                await task
        await manager.shutdown()
        await tunnel.stop()


app = FastAPI(title="RaspiCam", docs_url=None, redoc_url=None, lifespan=lifespan)

app.include_router(auth_api.router)
app.include_router(cameras_api.router)
app.include_router(storage_api.router)
app.include_router(recordings_api.router)
app.include_router(tunnel_api.router)
app.include_router(system_api.router)
app.mount("/static", StaticFiles(directory=WEB_DIR), name="static")


def _page(name):
    return HTMLResponse(
        (WEB_DIR / name).read_text(encoding="utf-8"),
        headers={"Cache-Control": "no-store"},
    )


@app.get("/", response_class=HTMLResponse)
async def root(request: Request):
    if not is_configured():
        return RedirectResponse("/setup")
    if not authenticated(request):
        return RedirectResponse("/login")
    return _page("index.html")


@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    if not is_configured():
        return RedirectResponse("/setup")
    if authenticated(request):
        return RedirectResponse("/")
    return _page("login.html")


@app.get("/setup", response_class=HTMLResponse)
async def setup_page():
    if is_configured():
        return RedirectResponse("/login")
    return _page("setup.html")
