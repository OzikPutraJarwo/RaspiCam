import asyncio
import collections
import contextlib
import os
import re
import shutil
import signal

from .config import config
from .events import bus

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
        "label": "Cloudflare Quick Tunnel",
        "binaries": ["cloudflared"],
        "pattern": r"https://[-a-z0-9]+\.trycloudflare\.com",
        "hint": "Fast HTTPS links with no account. Install with the RaspiCam installer or from cloudflare.com.",
    },
    "serveo": {
        "label": "Serveo",
        "binaries": ["ssh"],
        "pattern": r"https://[-a-z0-9.]+\.serveo\.net",
        "hint": "Uses plain SSH, nothing extra to install.",
    },
    "pinggy": {
        "label": "Pinggy",
        "binaries": ["ssh"],
        "pattern": r"https://[-a-z0-9.]+\.pinggy\.(?:link|online|io)",
        "hint": "Uses plain SSH. Free sessions end after 60 minutes and reconnect with a new address.",
    },
    "localtunnel": {
        "label": "LocalTunnel",
        "binaries": ["lt", "npx"],
        "pattern": r"https://[-a-z0-9.]+\.loca\.lt",
        "hint": "Needs Node.js. Visitors must first enter the Pi public IP on the LocalTunnel warning page.",
    },
    "bore": {
        "label": "bore.pub",
        "binaries": ["bore"],
        "pattern": r"bore\.pub:(\d+)",
        "template": "http://bore.pub:{}",
        "hint": "Plain HTTP on a random port. Install the bore client from github.com/ekzhang/bore.",
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
    if provider == "pinggy":
        return [path, "-p", "443"] + SSH_OPTIONS + ["-R0:localhost:{}".format(port), "a.pinggy.io"]
    if provider == "localtunnel":
        if name == "lt":
            return [path, "--port", str(port)]
        return [path, "--yes", "localtunnel", "--port", str(port)]
    if provider == "bore":
        return [path, "local", str(port), "--to", "bore.pub"]
    return None


def providers(port):
    entries = []
    for key, meta in PROVIDERS.items():
        _name, path = binary_for(key)
        entries.append(
            {
                "id": key,
                "label": meta["label"],
                "hint": meta["hint"],
                "available": bool(path),
                "requires": meta["binaries"][0],
            }
        )
    return entries


class TunnelManager:
    def __init__(self):
        self.provider = None
        self.url = None
        self.state = "stopped"
        self.error = None
        self.port = 8080
        self.log = collections.deque(maxlen=120)
        self._process = None
        self._supervisor = None
        self._stopping = False

    def status(self):
        return {
            "provider": self.provider,
            "url": self.url,
            "state": self.state,
            "error": self.error,
            "log": list(self.log)[-20:],
        }

    def _publish(self):
        bus.publish({"type": "tunnel", "status": self.status()})

    async def start(self, provider, port):
        if provider not in PROVIDERS:
            raise ValueError("Unknown tunnel provider")
        if not command_for(provider, port):
            raise ValueError("{} is not installed".format(PROVIDERS[provider]["binaries"][0]))
        await self.stop()
        self.provider = provider
        self.port = port
        self.url = None
        self.error = None
        self.state = "starting"
        self._stopping = False
        self.log.clear()
        self._publish()
        self._supervisor = asyncio.create_task(self._supervise())

    async def stop(self):
        self._stopping = True
        if self._supervisor:
            self._supervisor.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._supervisor
            self._supervisor = None
        await self._terminate()
        self.state = "stopped"
        self.url = None
        self._publish()

    async def _supervise(self):
        delay = 3
        while not self._stopping:
            command = command_for(self.provider, self.port)
            if not command:
                self.state = "error"
                self.error = "Tunnel client is not installed"
                self._publish()
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
            code = await self._process.wait()
            reader.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await reader
            if self._stopping:
                return
            self.url = None
            self.state = "reconnecting"
            self.error = "Tunnel client exited (code {})".format(code)
            self._publish()
            await asyncio.sleep(delay)
            delay = min(delay * 2, 60)

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
                self.state = "online"
                self.error = None
                self._publish()

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

    async def autostart(self):
        settings = config.section("tunnel")
        if not settings.get("autostart"):
            return
        provider = settings.get("provider")
        port = int(config.section("server").get("port") or 8080)
        if provider and command_for(provider, port):
            with contextlib.suppress(ValueError):
                await self.start(provider, port)


tunnel = TunnelManager()
