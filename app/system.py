import platform
import socket
import time
from pathlib import Path

import psutil

from . import __version__

BOOT_TIME = psutil.boot_time()
THERMAL_PATHS = [
    Path("/sys/class/thermal/thermal_zone0/temp"),
    Path("/sys/devices/virtual/thermal/thermal_zone0/temp"),
]


def cpu_temperature():
    for path in THERMAL_PATHS:
        try:
            value = float(path.read_text().strip())
        except (OSError, ValueError):
            continue
        return round(value / 1000.0, 1) if value > 1000 else round(value, 1)
    return None


def lan_address():
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect(("10.255.255.255", 1))
        return sock.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        sock.close()


def model_name():
    try:
        return Path("/proc/device-tree/model").read_text().strip("\x00").strip()
    except OSError:
        return platform.platform()


def stats():
    memory = psutil.virtual_memory()
    return {
        "version": __version__,
        "hostname": socket.gethostname(),
        "model": model_name(),
        "address": lan_address(),
        "cpu_percent": psutil.cpu_percent(interval=None),
        "cpu_temp": cpu_temperature(),
        "memory_used": memory.used,
        "memory_total": memory.total,
        "memory_percent": memory.percent,
        "uptime": int(time.time() - BOOT_TIME),
        "load": [round(v, 2) for v in psutil.getloadavg()],
    }
