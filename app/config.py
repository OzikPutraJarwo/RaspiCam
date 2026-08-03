import copy
import json
import os
import secrets
import threading
import uuid
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
WEB_DIR = BASE_DIR / "web"
DATA_DIR = Path(os.environ.get("RASPICAM_DATA", BASE_DIR / "data"))
CONFIG_PATH = DATA_DIR / "config.json"
DATABASE_PATH = DATA_DIR / "raspicam.db"

DEFAULT_CONFIG = {
    "auth": {"password": None, "secret": None},
    "server": {"port": 8080},
    "storage": {
        "root": None,
        "segment_seconds": 300,
        "retention_percent": 85,
        "min_free_gb": 2.0,
    },
    "tunnel": {"provider": "cloudflared", "autostart": False},
    "cameras": [],
}

DEFAULT_CAMERA = {
    "id": "",
    "name": "Camera",
    "type": "usb",
    "device": "",
    "index": 0,
    "url": "",
    "enabled": False,
    "width": 1280,
    "height": 720,
    "fps": 15,
    "input_format": "mjpeg",
    "bitrate": 2500,
    "rotation": 0,
    "preview_width": 640,
    "preview_fps": 10,
    "preview_quality": 7,
    "record_mode": "off",
}


class ConfigStore:
    def __init__(self, path=CONFIG_PATH):
        self.path = Path(path)
        self._lock = threading.RLock()
        self._data = {}
        self.load()

    def load(self):
        with self._lock:
            data = copy.deepcopy(DEFAULT_CONFIG)
            if self.path.exists():
                try:
                    stored = json.loads(self.path.read_text())
                except (ValueError, OSError):
                    stored = {}
                for key, value in stored.items():
                    if isinstance(value, dict) and isinstance(data.get(key), dict):
                        data[key].update(value)
                    else:
                        data[key] = value
            changed = False
            if not data["auth"].get("secret"):
                data["auth"]["secret"] = secrets.token_hex(32)
                changed = True
            data["cameras"] = [self._normalize_camera(c) for c in data.get("cameras", [])]
            self._data = data
            if changed:
                self._write()
            return self._data

    def _normalize_camera(self, camera):
        merged = copy.deepcopy(DEFAULT_CAMERA)
        merged.update({k: v for k, v in camera.items() if k in DEFAULT_CAMERA})
        if not merged["id"]:
            merged["id"] = new_camera_id()
        return merged

    def _write(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp = self.path.with_suffix(".tmp")
        temp.write_text(json.dumps(self._data, indent=2))
        os.chmod(temp, 0o600)
        os.replace(temp, self.path)

    def save(self):
        with self._lock:
            self._write()

    def all(self):
        with self._lock:
            return copy.deepcopy(self._data)

    def section(self, name):
        with self._lock:
            return copy.deepcopy(self._data.get(name, {}))

    def update_section(self, name, values):
        with self._lock:
            section = self._data.setdefault(name, {})
            section.update(values)
            self._write()
            return copy.deepcopy(section)

    def cameras(self):
        with self._lock:
            return copy.deepcopy(self._data["cameras"])

    def camera(self, camera_id):
        with self._lock:
            for camera in self._data["cameras"]:
                if camera["id"] == camera_id:
                    return copy.deepcopy(camera)
            return None

    def add_camera(self, values):
        with self._lock:
            camera = self._normalize_camera(values)
            camera["id"] = values.get("id") or new_camera_id()
            self._data["cameras"].append(camera)
            self._write()
            return copy.deepcopy(camera)

    def update_camera(self, camera_id, values):
        with self._lock:
            for camera in self._data["cameras"]:
                if camera["id"] == camera_id:
                    for key, value in values.items():
                        if key in DEFAULT_CAMERA and key != "id":
                            camera[key] = value
                    self._write()
                    return copy.deepcopy(camera)
            return None

    def remove_camera(self, camera_id):
        with self._lock:
            before = len(self._data["cameras"])
            self._data["cameras"] = [c for c in self._data["cameras"] if c["id"] != camera_id]
            removed = len(self._data["cameras"]) != before
            if removed:
                self._write()
            return removed


def new_camera_id():
    return "cam_" + uuid.uuid4().hex[:8]


DATA_DIR.mkdir(parents=True, exist_ok=True)
config = ConfigStore()
