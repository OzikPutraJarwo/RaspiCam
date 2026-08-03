import asyncio
import os
import signal

from fastapi import APIRouter, Body, Depends, HTTPException, WebSocket, WebSocketDisconnect

from .. import storage, system
from ..auth import SESSION_COOKIE, require_session, valid_session
from ..cameras.manager import manager
from ..cameras.source import ffmpeg_binary, preferred_encoder
from ..config import config
from ..events import bus
from ..tunnel import tunnel

router = APIRouter(prefix="/api", tags=["system"])

PURGE_SCRIPT = os.environ.get("RASPICAM_PURGE", "/usr/local/lib/raspicam/purge.sh")


@router.get("/system", dependencies=[Depends(require_session)])
async def overview():
    return {
        "system": system.stats(),
        "storage": storage.summary(),
        "cameras": [
            {"id": camera["id"], "name": camera["name"], "status": manager.status(camera["id"])}
            for camera in config.cameras()
        ],
        "tunnels": tunnel.statuses(),
        "ffmpeg": bool(ffmpeg_binary()),
        "encoder": preferred_encoder(),
        "port": int(config.section("server").get("port") or 8080),
        "removable": os.path.exists(PURGE_SCRIPT),
    }


@router.post("/system/restart", dependencies=[Depends(require_session)])
async def restart():
    async def shutdown():
        await asyncio.sleep(0.5)
        os.kill(os.getpid(), signal.SIGTERM)

    asyncio.create_task(shutdown())
    return {"ok": True}


@router.post("/system/uninstall", dependencies=[Depends(require_session)])
async def uninstall(media: bool = Body(False, embed=True)):
    if not os.path.exists(PURGE_SCRIPT):
        raise HTTPException(
            status_code=409,
            detail="The uninstaller is only available when RaspiCam was set up with install.sh",
        )
    arguments = [PURGE_SCRIPT] + (["--media"] if media else [])
    if os.geteuid() != 0:
        probe = await asyncio.create_subprocess_exec(
            "sudo",
            "-n",
            "-l",
            *arguments,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        if await probe.wait() != 0:
            raise HTTPException(
                status_code=409,
                detail="RaspiCam is not allowed to remove itself. Run: sudo raspicam uninstall",
            )
        arguments = ["sudo", "-n"] + arguments
    await asyncio.create_subprocess_exec(
        *arguments,
        stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL,
        start_new_session=True,
    )
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
