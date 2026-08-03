import asyncio

from fastapi import APIRouter, Body, Depends, HTTPException

from .. import recordings, storage
from ..auth import require_session
from ..cameras.manager import manager
from ..config import config
from ..events import bus

router = APIRouter(prefix="/api/storage", tags=["storage"], dependencies=[Depends(require_session)])

LIMITS = {
    "segment_seconds": (30, 3600),
    "retention_percent": (10, 99),
    "min_free_gb": (0.2, 512.0),
}


@router.get("")
async def overview():
    mounts = await asyncio.to_thread(storage.list_mounts)
    return {
        "mounts": mounts,
        "summary": storage.summary(),
        "recordings": await recordings.stats(),
    }


@router.post("/select")
async def select(path: str = Body(..., embed=True)):
    try:
        root = await asyncio.to_thread(storage.select_root, path)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error))
    for camera in config.cameras():
        storage.ensure_camera_dirs(camera["id"])
    await manager.sync()
    await recordings.scan()
    bus.publish({"type": "storage"})
    return {"root": root, "summary": storage.summary()}


@router.patch("/settings")
async def settings(payload: dict = Body(...)):
    values = {}
    for key, (minimum, maximum) in LIMITS.items():
        if key not in payload:
            continue
        try:
            value = float(payload[key])
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail="Invalid value for {}".format(key))
        if not minimum <= value <= maximum:
            raise HTTPException(status_code=400, detail="{} must be between {} and {}".format(key, minimum, maximum))
        values[key] = int(value) if key == "segment_seconds" or key == "retention_percent" else round(value, 2)
    if not values:
        raise HTTPException(status_code=400, detail="Nothing to update")
    updated = config.update_section("storage", values)
    if "segment_seconds" in values:
        for camera in config.cameras():
            await manager.apply_settings(camera["id"])
    bus.publish({"type": "storage"})
    return updated


@router.post("/scan")
async def scan():
    added = await recordings.scan()
    removed = await recordings.enforce_retention()
    return {"added": added, "removed": removed, "recordings": await recordings.stats()}
