import asyncio
from datetime import datetime

from .. import storage
from ..config import config
from ..events import bus
from .discovery import discover
from .pipeline import CameraPipeline
from .source import snapshot_command

SEGMENT_PATTERN = "%Y-%m-%d_%H-%M-%S.mp4"
CAPTURE_PATTERN = "%Y-%m-%d_%H-%M-%S.jpg"


class CameraManager:
    def __init__(self):
        self._pipelines = {}
        self._lock = asyncio.Lock()

    def pipeline(self, camera_id):
        return self._pipelines.get(camera_id)

    def _segment_seconds(self):
        return int(config.section("storage").get("segment_seconds") or 300)

    def _record_pattern(self, camera_id):
        paths = storage.ensure_camera_dirs(camera_id)
        if not paths:
            return None
        return str(paths["recordings"] / SEGMENT_PATTERN)

    def _on_change(self, pipeline):
        bus.publish({"type": "camera", "id": pipeline.camera["id"], "status": pipeline.status()})

    async def sync(self):
        async with self._lock:
            known = {camera["id"]: camera for camera in config.cameras()}
            for camera_id in list(self._pipelines):
                if camera_id not in known:
                    await self._stop(camera_id)
                    self._pipelines.pop(camera_id, None)
            for camera in known.values():
                if camera["enabled"]:
                    await self._start(camera["id"])
                else:
                    await self._stop(camera["id"])

    async def _start(self, camera_id):
        camera = config.camera(camera_id)
        if not camera:
            return None
        pattern = self._record_pattern(camera_id)
        pipeline = self._pipelines.get(camera_id)
        if pipeline is None:
            pipeline = CameraPipeline(camera, pattern, self._segment_seconds(), self._on_change)
            self._pipelines[camera_id] = pipeline
        else:
            pipeline.camera = camera
            pipeline.record_pattern = pattern
            pipeline.segment_seconds = self._segment_seconds()
        if camera["record_mode"] == "continuous":
            pipeline.recording = bool(pattern)
        elif camera["record_mode"] == "off" or not pipeline.running:
            pipeline.recording = False
        await pipeline.start()
        return pipeline

    async def _stop(self, camera_id):
        pipeline = self._pipelines.get(camera_id)
        if pipeline:
            await pipeline.stop()
        return pipeline

    async def start(self, camera_id):
        async with self._lock:
            config.update_camera(camera_id, {"enabled": True})
            return await self._start(camera_id)

    async def stop(self, camera_id):
        async with self._lock:
            config.update_camera(camera_id, {"enabled": False})
            return await self._stop(camera_id)

    async def remove(self, camera_id):
        async with self._lock:
            await self._stop(camera_id)
            self._pipelines.pop(camera_id, None)

    async def apply_settings(self, camera_id):
        async with self._lock:
            camera = config.camera(camera_id)
            pipeline = self._pipelines.get(camera_id)
            if not camera or not pipeline:
                return
            previous_mode = pipeline.camera.get("record_mode")
            pipeline.camera = camera
            pipeline.record_pattern = self._record_pattern(camera_id)
            pipeline.segment_seconds = self._segment_seconds()
            if camera["record_mode"] != previous_mode:
                pipeline.recording = camera["record_mode"] == "continuous" and bool(pipeline.record_pattern)
            if pipeline.running:
                await pipeline.restart()

    async def set_recording(self, camera_id, active):
        pipeline = self._pipelines.get(camera_id)
        if not pipeline:
            raise RuntimeError("Camera is not running")
        if active and not storage.is_available():
            raise RuntimeError("No storage location selected")
        pipeline.record_pattern = self._record_pattern(camera_id)
        if active and not pipeline.record_pattern:
            raise RuntimeError("No storage location selected")
        await pipeline.set_recording(active)
        return pipeline

    async def snapshot(self, camera_id):
        camera = config.camera(camera_id)
        if not camera:
            raise RuntimeError("Unknown camera")
        pipeline = self._pipelines.get(camera_id)
        if pipeline and pipeline.running:
            frame = await pipeline.hub.wait_for_frame(timeout=8)
            if frame:
                return frame
            raise RuntimeError(pipeline.error or "No frames received")
        command = snapshot_command(camera)
        process = await asyncio.create_subprocess_exec(
            *command,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=25)
        except asyncio.TimeoutError:
            process.kill()
            raise RuntimeError("Snapshot timed out")
        if not stdout:
            message = stderr.decode("utf-8", "replace").strip().splitlines()
            raise RuntimeError(message[-1][:200] if message else "Snapshot failed")
        return stdout

    async def capture(self, camera_id):
        frame = await self.snapshot(camera_id)
        paths = storage.ensure_camera_dirs(camera_id)
        if not paths:
            raise RuntimeError("No storage location selected")
        name = datetime.now().strftime(CAPTURE_PATTERN)
        target = paths["captures"] / name
        await asyncio.to_thread(target.write_bytes, frame)
        bus.publish({"type": "capture", "id": camera_id, "name": name})
        return target

    def status(self, camera_id):
        pipeline = self._pipelines.get(camera_id)
        if not pipeline:
            return {"state": "stopped", "recording": False, "error": None, "fps": 0, "viewers": 0, "uptime": 0, "log": []}
        return pipeline.status()

    def describe(self, camera):
        return dict(camera, status=self.status(camera["id"]))

    def listing(self):
        return [self.describe(camera) for camera in config.cameras()]

    async def available_sources(self):
        sources = await asyncio.to_thread(discover)
        used = set()
        for camera in config.cameras():
            if camera["type"] == "usb":
                used.add(camera["device"])
            elif camera["type"] == "csi":
                used.add("csi:{}".format(camera["index"]))
        return [source for source in sources if source["device"] not in used]

    async def shutdown(self):
        for camera_id in list(self._pipelines):
            await self._stop(camera_id)
        self._pipelines.clear()


manager = CameraManager()
