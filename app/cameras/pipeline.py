import asyncio
import collections
import contextlib
import os
import signal
import time

from .hub import FrameHub
from .source import build_command, producer_command

RESTART_DELAYS = [2, 4, 8, 15, 30]
SOI = b"\xff\xd8"
EOI = b"\xff\xd9"


class CameraPipeline:
    def __init__(self, camera, record_pattern=None, segment_seconds=300, on_change=None):
        self.camera = camera
        self.record_pattern = record_pattern
        self.segment_seconds = segment_seconds
        self.on_change = on_change
        self.hub = FrameHub()
        self.recording = False
        self.state = "stopped"
        self.error = None
        self.started_at = None
        self.log = collections.deque(maxlen=80)
        self._process = None
        self._producer = None
        self._supervisor = None
        self._tasks = []
        self._stopping = False
        self._reload = False
        self._attempt = 0

    @property
    def running(self):
        return self.state in ("starting", "live")

    def status(self):
        return {
            "state": self.state,
            "recording": bool(self.recording and self.record_pattern),
            "error": self.error,
            "fps": self.hub.rate,
            "viewers": self.hub.viewers,
            "uptime": int(time.time() - self.started_at) if self.started_at else 0,
            "log": list(self.log)[-12:],
        }

    def _notify(self):
        if self.on_change:
            self.on_change(self)

    def _set_state(self, state, error=None):
        self.state = state
        self.error = error
        self._notify()

    async def start(self):
        if self._supervisor and not self._supervisor.done():
            return
        self._stopping = False
        self._attempt = 0
        self._set_state("starting")
        self._supervisor = asyncio.create_task(self._supervise())

    async def stop(self):
        self._stopping = True
        if self._supervisor:
            self._supervisor.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._supervisor
            self._supervisor = None
        await self._terminate()
        self.hub.reset()
        self.started_at = None
        self._set_state("stopped")

    async def restart(self):
        was_running = self.running
        await self.stop()
        if was_running:
            await self.start()

    async def set_recording(self, active):
        active = bool(active) and bool(self.record_pattern)
        if active == self.recording:
            return
        self.recording = active
        if self.running:
            self._reload = True
            await self._terminate()
        else:
            self._notify()

    async def _supervise(self):
        while not self._stopping:
            try:
                await self._spawn()
            except Exception as error:
                self._set_state("error", str(error))
                self.log.append(str(error))
            else:
                code = await self._process.wait()
                await self._drain_tasks()
                if self._stopping:
                    return
                if self._reload:
                    self._reload = False
                    await self._terminate()
                    self.hub.reset()
                    self._set_state("starting", None)
                    continue
                if code == 0:
                    self._set_state("error", "Capture ended unexpectedly")
                else:
                    self._set_state("error", self._last_error() or "Capture failed (code {})".format(code))
            await self._terminate()
            self._attempt = min(self._attempt + 1, len(RESTART_DELAYS) - 1)
            delay = RESTART_DELAYS[self._attempt]
            self.hub.reset()
            await asyncio.sleep(delay)
            self._set_state("starting", self.error)

    def _last_error(self):
        for line in reversed(self.log):
            if line.strip():
                return line.strip()[:200]
        return None

    async def _spawn(self):
        command = build_command(self.camera, self.record_pattern if self.recording else None, self.segment_seconds)
        producer = producer_command(self.camera)
        if self.camera.get("type") == "csi" and not producer:
            raise RuntimeError("rpicam-vid is not installed")
        self.log.append("$ " + " ".join(command))
        if producer:
            read_fd, write_fd = os.pipe()
            self._producer = await asyncio.create_subprocess_exec(
                *producer,
                stdout=write_fd,
                stderr=asyncio.subprocess.PIPE,
                start_new_session=True,
            )
            os.close(write_fd)
            self._process = await asyncio.create_subprocess_exec(
                *command,
                stdin=read_fd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                start_new_session=True,
            )
            os.close(read_fd)
            self._tasks.append(asyncio.create_task(self._read_log(self._producer.stderr)))
        else:
            self._process = await asyncio.create_subprocess_exec(
                *command,
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                start_new_session=True,
            )
        self.started_at = time.time()
        self._tasks.append(asyncio.create_task(self._read_frames(self._process.stdout)))
        self._tasks.append(asyncio.create_task(self._read_log(self._process.stderr)))

    async def _read_frames(self, stream):
        buffer = bytearray()
        first = True
        while True:
            chunk = await stream.read(65536)
            if not chunk:
                break
            buffer += chunk
            while True:
                start = buffer.find(SOI)
                if start < 0:
                    buffer.clear()
                    break
                end = buffer.find(EOI, start + 2)
                if end < 0:
                    if start:
                        del buffer[:start]
                    break
                frame = bytes(buffer[start : end + 2])
                del buffer[: end + 2]
                if first:
                    first = False
                    self._attempt = 0
                    self._set_state("live", None)
                self.hub.publish(frame)

    async def _read_log(self, stream):
        while True:
            line = await stream.readline()
            if not line:
                break
            text = line.decode("utf-8", "replace").rstrip()
            if text:
                self.log.append(text)

    async def _drain_tasks(self):
        for task in self._tasks:
            task.cancel()
        for task in self._tasks:
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await task
        self._tasks = []

    async def _terminate(self):
        await self._drain_tasks()
        for process in (self._process, self._producer):
            if not process or process.returncode is not None:
                continue
            with contextlib.suppress(ProcessLookupError, OSError):
                os.killpg(os.getpgid(process.pid), signal.SIGTERM)
            try:
                await asyncio.wait_for(process.wait(), timeout=5)
            except asyncio.TimeoutError:
                with contextlib.suppress(ProcessLookupError, OSError):
                    os.killpg(os.getpgid(process.pid), signal.SIGKILL)
                with contextlib.suppress(Exception):
                    await process.wait()
        self._process = None
        self._producer = None
