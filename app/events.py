import asyncio
import contextlib


class EventBus:
    def __init__(self):
        self._subscribers = set()

    def publish(self, event):
        for queue in list(self._subscribers):
            if queue.full():
                try:
                    queue.get_nowait()
                except asyncio.QueueEmpty:
                    pass
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                pass

    @contextlib.contextmanager
    def subscribe(self):
        queue = asyncio.Queue(maxsize=32)
        self._subscribers.add(queue)
        try:
            yield queue
        finally:
            self._subscribers.discard(queue)


bus = EventBus()
