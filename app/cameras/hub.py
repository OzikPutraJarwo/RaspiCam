import asyncio
import contextlib
import time


class FrameHub:
    def __init__(self):
        self._latest = None
        self._latest_at = 0.0
        self._subscribers = set()
        self._frames = 0
        self._window_start = time.monotonic()
        self._rate = 0.0

    def publish(self, frame):
        self._latest = frame
        self._latest_at = time.time()
        self._frames += 1
        elapsed = time.monotonic() - self._window_start
        if elapsed >= 2.0:
            self._rate = round(self._frames / elapsed, 1)
            self._frames = 0
            self._window_start = time.monotonic()
        for queue in list(self._subscribers):
            if queue.full():
                try:
                    queue.get_nowait()
                except asyncio.QueueEmpty:
                    pass
            try:
                queue.put_nowait(frame)
            except asyncio.QueueFull:
                pass

    def reset(self):
        self._latest = None
        self._latest_at = 0.0
        self._rate = 0.0
        self._frames = 0
        self._window_start = time.monotonic()

    @property
    def latest(self):
        return self._latest

    @property
    def latest_at(self):
        return self._latest_at

    @property
    def rate(self):
        return self._rate

    @property
    def viewers(self):
        return len(self._subscribers)

    async def wait_for_frame(self, timeout=10.0):
        deadline = time.monotonic() + timeout
        while self._latest is None:
            if time.monotonic() > deadline:
                return None
            await asyncio.sleep(0.1)
        return self._latest

    @contextlib.contextmanager
    def subscribe(self):
        queue = asyncio.Queue(maxsize=2)
        if self._latest is not None:
            queue.put_nowait(self._latest)
        self._subscribers.add(queue)
        try:
            yield queue
        finally:
            self._subscribers.discard(queue)
