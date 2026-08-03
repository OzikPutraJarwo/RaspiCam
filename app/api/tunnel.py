import base64
import io

import segno
from fastapi import APIRouter, Body, Depends, HTTPException

from ..auth import require_session
from ..config import config
from ..tunnel import PROVIDERS, tunnel

router = APIRouter(prefix="/api/tunnel", tags=["tunnel"], dependencies=[Depends(require_session)])


def qr_data_uri(url):
    if not url:
        return None
    buffer = io.BytesIO()
    segno.make(url, error="m").save(buffer, kind="png", scale=5, border=2)
    return "data:image/png;base64," + base64.b64encode(buffer.getvalue()).decode()


def _port():
    return int(config.section("server").get("port") or 8080)


@router.get("")
async def overview():
    providers = tunnel.providers()
    for provider in providers:
        status = provider.get("status")
        provider["qr"] = qr_data_uri(status.get("url")) if status else None
    return {"providers": providers, "settings": config.section("tunnel"), "port": _port()}


@router.post("/start")
async def start(provider: str = Body(..., embed=True)):
    try:
        await tunnel.start(provider, _port())
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error))
    return {"sessions": tunnel.statuses()}


@router.post("/stop")
async def stop(provider: str = Body(None, embed=True)):
    if provider:
        await tunnel.stop(provider)
    else:
        await tunnel.stop_all()
    return {"sessions": tunnel.statuses()}


@router.patch("/settings")
async def settings(autostart: list = Body(..., embed=True)):
    wanted = [item for item in autostart if item in PROVIDERS]
    return config.update_section("tunnel", {"autostart": wanted})
