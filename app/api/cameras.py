import asyncio

from fastapi import APIRouter, Body, Depends, HTTPException, Request, Response
from fastapi.responses import StreamingResponse

from .. import recordings, storage
from ..auth import require_session
from ..cameras.discovery import default_settings, list_csi_cameras, list_v4l2_devices, probe_network_source
from ..cameras.manager import manager
from ..config import config
from ..events import bus

router = APIRouter(prefix="/api/cameras", tags=["cameras"], dependencies=[Depends(require_session)])

BOUNDARY = "raspicamframe"
EDITABLE = {
    "name",
    "width",
    "height",
    "fps",
    "input_format",
    "bitrate",
    "rotation",
    "preview_width",
    "preview_fps",
    "preview_quality",
    "record_mode",
    "url",
}


def _require_camera(camera_id):
    camera = config.camera(camera_id)
    if not camera:
        raise HTTPException(status_code=404, detail="Camera not found")
    return camera


@router.get("")
async def listing():
    return {"cameras": manager.listing(), "storage": storage.is_available()}


@router.get("/discover")
async def discover():
    return {"sources": await manager.available_sources()}


@router.post("/probe")
async def probe(url: str = Body(..., embed=True)):
    result = await asyncio.to_thread(probe_network_source, url)
    if not result["ok"]:
        raise HTTPException(status_code=400, detail=result["error"])
    return result


@router.post("")
async def create(payload: dict = Body(...)):
    kind = payload.get("type")
    if kind not in ("usb", "csi", "network"):
        raise HTTPException(status_code=400, detail="Unsupported camera type")
    values = {"type": kind, "name": (payload.get("name") or "Camera").strip()[:48]}
    if kind == "network":
        url = (payload.get("url") or "").strip()
        if not url:
            raise HTTPException(status_code=400, detail="Stream URL is required")
        probed = await asyncio.to_thread(probe_network_source, url)
        if not probed["ok"]:
            raise HTTPException(status_code=400, detail=probed["error"])
        values.update(
            {
                "url": url,
                "width": probed["width"],
                "height": probed["height"],
                "fps": probed["fps"],
                "input_format": probed["codec"] or "h264",
            }
        )
    else:
        source = payload.get("source") or {}
        values.update(default_settings(source))
        if kind == "usb":
            device = source.get("device") or payload.get("device")
            if not device:
                raise HTTPException(status_code=400, detail="Device path is required")
            values["device"] = device
        else:
            values["index"] = int(source.get("index") or payload.get("index") or 0)
            values["device"] = "csi:{}".format(values["index"])
    camera = config.add_camera(values)
    storage.ensure_camera_dirs(camera["id"])
    bus.publish({"type": "cameras"})
    return manager.describe(camera)


@router.get("/{camera_id}")
async def detail(camera_id: str):
    return manager.describe(_require_camera(camera_id))


@router.get("/{camera_id}/modes")
async def modes(camera_id: str):
    camera = _require_camera(camera_id)
    if camera["type"] == "usb":
        for source in await asyncio.to_thread(list_v4l2_devices):
            if camera["device"] in (source["device"], source["node"]):
                return {"modes": source["modes"], "formats": source["formats"]}
    elif camera["type"] == "csi":
        for source in await asyncio.to_thread(list_csi_cameras):
            if source["index"] == camera["index"]:
                return {"modes": source["modes"], "formats": source["formats"]}
    return {"modes": [], "formats": []}


@router.patch("/{camera_id}")
async def update(camera_id: str, payload: dict = Body(...)):
    _require_camera(camera_id)
    values = {key: payload[key] for key in payload if key in EDITABLE}
    if not values:
        raise HTTPException(status_code=400, detail="Nothing to update")
    for key in ("width", "height", "fps", "bitrate", "rotation", "preview_width", "preview_fps", "preview_quality"):
        if key in values:
            try:
                values[key] = int(values[key])
            except (TypeError, ValueError):
                raise HTTPException(status_code=400, detail="Invalid value for {}".format(key))
    if values.get("record_mode") not in (None, "off", "manual", "continuous"):
        raise HTTPException(status_code=400, detail="Invalid record mode")
    camera = config.update_camera(camera_id, values)
    await manager.apply_settings(camera_id)
    bus.publish({"type": "cameras"})
    return manager.describe(camera)


@router.delete("/{camera_id}")
async def remove(camera_id: str, purge: bool = False):
    _require_camera(camera_id)
    await manager.remove(camera_id)
    config.remove_camera(camera_id)
    await recordings.delete_camera(camera_id)
    if purge:
        storage.remove_camera_dirs(camera_id)
    bus.publish({"type": "cameras"})
    return {"ok": True}


@router.post("/{camera_id}/start")
async def start(camera_id: str):
    _require_camera(camera_id)
    await manager.start(camera_id)
    return {"status": manager.status(camera_id)}


@router.post("/{camera_id}/stop")
async def stop(camera_id: str):
    _require_camera(camera_id)
    await manager.stop(camera_id)
    return {"status": manager.status(camera_id)}


@router.post("/{camera_id}/record")
async def record(camera_id: str, active: bool = Body(..., embed=True)):
    _require_camera(camera_id)
    try:
        await manager.set_recording(camera_id, active)
    except RuntimeError as error:
        raise HTTPException(status_code=409, detail=str(error))
    return {"status": manager.status(camera_id)}


@router.post("/{camera_id}/capture")
async def capture(camera_id: str):
    _require_camera(camera_id)
    try:
        target = await manager.capture(camera_id)
    except RuntimeError as error:
        raise HTTPException(status_code=409, detail=str(error))
    return {"name": target.name}


@router.get("/{camera_id}/snapshot.jpg")
async def snapshot(camera_id: str):
    _require_camera(camera_id)
    try:
        frame = await manager.snapshot(camera_id)
    except RuntimeError as error:
        raise HTTPException(status_code=409, detail=str(error))
    return Response(content=frame, media_type="image/jpeg", headers={"Cache-Control": "no-store"})


@router.get("/{camera_id}/stream")
async def stream(camera_id: str, request: Request):
    _require_camera(camera_id)
    pipeline = manager.pipeline(camera_id)
    if not pipeline or not pipeline.running:
        raise HTTPException(status_code=409, detail="Camera is not running")

    async def frames():
        with pipeline.hub.subscribe() as queue:
            while True:
                if await request.is_disconnected():
                    return
                try:
                    frame = await asyncio.wait_for(queue.get(), timeout=20)
                except asyncio.TimeoutError:
                    return
                yield b"--%s\r\nContent-Type: image/jpeg\r\nContent-Length: %d\r\n\r\n" % (
                    BOUNDARY.encode(),
                    len(frame),
                )
                yield frame
                yield b"\r\n"

    return StreamingResponse(
        frames(),
        media_type="multipart/x-mixed-replace; boundary={}".format(BOUNDARY),
        headers={"Cache-Control": "no-store", "Connection": "close"},
    )
