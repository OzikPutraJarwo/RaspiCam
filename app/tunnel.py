import asyncio
import collections
import contextlib
import os
import re
import shutil
import signal

from .config import config
from .events import bus

MAX_STARTUP_FAILURES = 3

SSH_OPTIONS = [
    "-o",
    "ConnectTimeout=15",
    "-o",
    "StrictHostKeyChecking=no",
    "-o",
    "UserKnownHostsFile=/dev/null",
    "-o",
    "ServerAliveInterval=30",
    "-o",
    "ExitOnForwardFailure=yes",
    "-T",
    "-n",
]

PROVIDERS = {
    "cloudflared": {
        "label": "Cloudflare",
        "binaries": ["cloudflared"],
        "pattern": r"https://[-a-z0-9]+\.trycloudflare\.com",
    },
    "localtunnel": {
        "label": "LocalTunnel",
        "binaries": ["lt", "npx"],
        "pattern": r"https://[-a-z0-9.]+\.loca\.lt",
    },
    "bore": {
        "label": "bore.pub",
        "binaries": ["bore"],
        "pattern": r"bore\.pub:(\d+)",
        "template": "http://bore.pub:{}",
    },
    "serveo": {
        "label": "Serveo",
        "binaries": ["ssh"],
        "pattern": r"https://[-a-z0-9.]+\.serveo\.net",
    },
}


def binary_for(provider):
    for candidate in PROVIDERS[provider]["binaries"]:
        path = shutil.which(candidate)
        if path:
            return candidate, path
    return None, None


def command_for(provider, port):
    name, path = binary_for(provider)
    if not path:
        return None
    if provider == "cloudflared":
        return [path, "tunnel", "--no-autoupdate", "--url", "http://localhost:{}".format(port)]
    if provider == "serveo":
        return [path] + SSH_OPTIONS + ["-R", "80:localhost:{}".format(port), "serveo.net"]
    if provider == "localtunnel":
        if name == "lt":
            return [path, "--port", str(port)]
        return [path, "--yes", "localtunnel", "--port", str(port)]
    if provider == "bore":
        return [path, "local", str(port), "--to", "bore.pub"]
    return None


class TunnelSession:
    def __init__(self, provider, port, on_change):
        self.provider = provider
        self.port = port
        self.on_change = on_change
        self.url = None
        self.state = "starting"
        self.error = None
        self.log = collections.deque(maxlen=60)
        self.failures = 0
        self.established = False
        self._process = None
        self._supervisor = None
        self._stopping = False

    def status(self):
        return {
            "provider": self.provider,
            "url": self.url,
            "state": self.state,
            "error": self.error,
            "log": list(self.log)[-15:],
        }

    def _set(self, state, error=None):
        self.state = state
        self.error = error
        self.on_change()

    async def start(self):
        self._stopping = False
        self._set("starting")
        self._supervisor = asyncio.create_task(self._supervise())

    async def stop(self):
        self._stopping = True
        if self._supervisor:
            self._supervisor.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._supervisor
            self._supervisor = None
        await self._terminate()
        self.url = None
        self.state = "stopped"

    async def _supervise(self):
        delay = 3
        while not self._stopping:
            command = command_for(self.provider, self.port)
            if not command:
                self._set("error", "{} is not installed".format(PROVIDERS[self.provider]["binaries"][0]))
                return
            self.log.append("$ " + " ".join(command))
            self._process = await asyncio.create_subprocess_exec(
                *command,
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                start_new_session=True,
            )
            reader = asyncio.create_task(self._read_output(self._process.stdout))
            await self._process.wait()
            reader.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await reader
            if self._stopping:
                return
            self.url = None
            self.failures += 1
            message = self._last_error() or "The tunnel client stopped unexpectedly"
            if not self.established and self.failures >= MAX_STARTUP_FAILURES:
                self._set("error", message)
                await self._terminate()
                return
            self._set("reconnecting", message)
            await asyncio.sleep(delay)
            delay = min(delay * 2, 60)

    def _last_error(self):
        for line in reversed(self.log):
            text = line.strip()
            if text and not text.startswith("$"):
                return text[:180]
        return None

    async def _read_output(self, stream):
        meta = PROVIDERS[self.provider]
        pattern = re.compile(meta["pattern"], re.IGNORECASE)
        while True:
            line = await stream.readline()
            if not line:
                break
            text = line.decode("utf-8", "replace").rstrip()
            if not text:
                continue
            self.log.append(text)
            match = pattern.search(text)
            if match and not self.url:
                template = meta.get("template")
                self.url = template.format(match.group(1)) if template else match.group(0)
                self.failures = 0
                self.established = True
                self._set("online")

    async def _terminate(self):
        process = self._process
        self._process = None
        if not process or process.returncode is not None:
            return
        with contextlib.suppress(ProcessLookupError, OSError):
            os.killpg(os.getpgid(process.pid), signal.SIGTERM)
        try:
            await asyncio.wait_for(process.wait(), timeout=5)
        except asyncio.TimeoutError:
            with contextlib.suppress(ProcessLookupError, OSError):
                os.killpg(os.getpgid(process.pid), signal.SIGKILL)
            with contextlib.suppress(Exception):
                await process.wait()


class TunnelManager:
    def __init__(self):
        self._sessions = {}

    def _publish(self):
        bus.publish({"type": "tunnel", "sessions": self.statuses()})

    def statuses(self):
        return {provider: session.status() for provider, session in self._sessions.items()}

    def active_urls(self):
        return [session.url for session in self._sessions.values() if session.url]

    def providers(self):
        entries = []
        for key, meta in PROVIDERS.items():
            _name, path = binary_for(key)
            session = self._sessions.get(key)
            entries.append(
                {
                    "id": key,
                    "label": meta["label"],
                    "available": bool(path),
                    "requires": meta["binaries"][0],
                    "status": session.status() if session else None,
                }
            )
        return entries

    async def start(self, provider, port):
        if provider not in PROVIDERS:
            raise ValueError("Unknown tunnel provider")
        if not command_for(provider, port):
            raise ValueError("{} is not installed".format(PROVIDERS[provider]["binaries"][0]))
        await self.stop(provider)
        session = TunnelSession(provider, port, self._publish)
        self._sessions[provider] = session
        await session.start()
        self._publish()
        return session

    async def stop(self, provider):
        session = self._sessions.pop(provider, None)
        if session:
            await session.stop()
            self._publish()
        return session

    async def stop_all(self):
        for provider in list(self._sessions):
            await self.stop(provider)

    async def autostart(self):
        wanted = config.section("tunnel").get("autostart") or []
        port = int(config.section("server").get("port") or 8080)
        for provider in wanted:
            if provider in PROVIDERS and command_for(provider, port):
                with contextlib.suppress(ValueError):
                    await self.start(provider, port)


tunnel = TunnelManager()
