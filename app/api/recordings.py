import os
import time
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request

from .. import recordings
from ..auth import require_session
from ..config import config
from .files import ranged_response

router = APIRouter(prefix="/api/recordings", tags=["recordings"], dependencies=[Depends(require_session)])


def _day_bounds(value):
    if not value:
        start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    else:
        try:
            start = datetime.strptime(value, "%Y-%m-%d")
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid date")
    end = start + timedelta(days=1)
    return start.timestamp(), end.timestamp()


def _require_camera(camera_id):
    camera = config.camera(camera_id)
    if not camera:
        raise HTTPException(status_code=404, detail="Camera not found")
    return camera


@router.get("")
async def listing(camera: str, date: str = None):
    _require_camera(camera)
    start, end = _day_bounds(date)
    segments = await recordings.query(camera, start, end)
    return {
        "camera": camera,
        "date": date or datetime.fromtimestamp(start).strftime("%Y-%m-%d"),
        "start": start,
        "end": end,
        "segments": segments,
        "days": await recordings.days(camera),
    }


@router.get("/captures")
async def capture_list(camera: str):
    _require_camera(camera)
    return {"captures": await recordings.captures(camera)}


@router.get("/captures/{camera_id}/{name}")
async def capture_file(camera_id: str, name: str, request: Request, download: bool = False):
    _require_camera(camera_id)
    path = recordings.capture_path(camera_id, name)
    if not path:
        raise HTTPException(status_code=404, detail="Capture not found")
    return ranged_response(path, request, "image/jpeg", name, download)


@router.delete("/captures/{camera_id}/{name}")
async def delete_capture(camera_id: str, name: str):
    _require_camera(camera_id)
    if not await recordings.delete_capture(camera_id, name):
        raise HTTPException(status_code=404, detail="Capture not found")
    return {"ok": True}


@router.get("/{segment_id}/file")
async def segment_file(segment_id: int, request: Request, download: bool = False):
    entry = await recordings.segment(segment_id)
    if not entry or not os.path.exists(entry["path"]):
        raise HTTPException(status_code=404, detail="Recording not found")
    name = time.strftime("%Y-%m-%d_%H-%M-%S", time.localtime(entry["start_ts"])) + ".mp4"
    return ranged_response(entry["path"], request, "video/mp4", name, download)


@router.delete("/{segment_id}")
async def delete_segment(segment_id: int):
    if not await recordings.delete(segment_id):
        raise HTTPException(status_code=404, detail="Recording not found")
    return {"ok": True}
