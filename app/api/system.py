import asyncio
import os
import signal

from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect

from .. import storage, system
from ..auth import require_session, valid_session, SESSION_COOKIE
from ..cameras.manager import manager
from ..cameras.source import ffmpeg_binary, preferred_encoder
from ..config import config
from ..events import bus
from ..tunnel import tunnel

router = APIRouter(prefix="/api", tags=["system"])


@router.get("/system", dependencies=[Depends(require_session)])
async def overview():
    return {
        "system": system.stats(),
        "storage": storage.summary(),
        "cameras": [
            {"id": camera["id"], "name": camera["name"], "status": manager.status(camera["id"])}
            for camera in config.cameras()
        ],
        "tunnel": tunnel.status(),
        "ffmpeg": bool(ffmpeg_binary()),
        "encoder": preferred_encoder(),
        "port": int(config.section("server").get("port") or 8080),
    }


@router.post("/system/restart", dependencies=[Depends(require_session)])
async def restart():
    async def shutdown():
        await asyncio.sleep(0.5)
        os.kill(os.getpid(), signal.SIGTERM)

    asyncio.create_task(shutdown())
    return {"ok": True}


@router.websocket("/events")
async def events(websocket: WebSocket):
    if not valid_session(websocket.cookies.get(SESSION_COOKIE)):
        await websocket.close(code=1008)
        return
    await websocket.accept()
    with bus.subscribe() as queue:
        try:
            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=15)
                except asyncio.TimeoutError:
                    await websocket.send_json({"type": "ping"})
                    continue
                await websocket.send_json(event)
        except (WebSocketDisconnect, RuntimeError):
            return
