import json
import os
import shutil
import subprocess
from pathlib import Path

import psutil

from .config import config

APP_FOLDER = "RaspiCam"
IGNORED_FILESYSTEMS = {
    "squashfs",
    "tmpfs",
    "devtmpfs",
    "overlay",
    "proc",
    "sysfs",
    "autofs",
    "efivarfs",
    "ramfs",
    "cgroup2",
    "debugfs",
    "tracefs",
    "securityfs",
    "pstore",
    "bpf",
    "configfs",
    "fusectl",
    "mqueue",
    "hugetlbfs",
    "binfmt_misc",
    "nsfs",
}
IGNORED_PREFIXES = ("/snap", "/var/snap", "/proc", "/sys", "/run", "/dev")


def _kind(name, transport, removable):
    if name.startswith("mmcblk"):
        return "sdcard"
    if transport == "usb" or removable:
        return "usb"
    if name.startswith("nvme"):
        return "nvme"
    return "internal"


def _walk(node, transport, removable, results):
    transport = node.get("tran") or transport
    removable = bool(node.get("rm")) or removable
    mountpoint = node.get("mountpoint")
    if mountpoint and node.get("fstype") not in IGNORED_FILESYSTEMS:
        results.append(
            {
                "name": node.get("name") or "",
                "path": mountpoint,
                "fstype": node.get("fstype") or "",
                "label": node.get("label") or "",
                "model": (node.get("model") or "").strip(),
                "transport": transport or "",
                "kind": _kind(node.get("name") or "", transport, removable),
            }
        )
    for child in node.get("children") or []:
        _walk(child, transport, removable, results)


def _lsblk_mounts():
    if not shutil.which("lsblk"):
        return []
    try:
        result = subprocess.run(
            ["lsblk", "-J", "-b", "-o", "NAME,FSTYPE,MOUNTPOINT,TRAN,RM,MODEL,LABEL"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        payload = json.loads(result.stdout)
    except (OSError, ValueError, subprocess.SubprocessError):
        return []
    results = []
    for node in payload.get("blockdevices", []):
        _walk(node, None, False, results)
    return results


def _psutil_mounts():
    results = []
    for partition in psutil.disk_partitions(all=False):
        if partition.fstype in IGNORED_FILESYSTEMS:
            continue
        results.append(
            {
                "name": Path(partition.device).name,
                "path": partition.mountpoint,
                "fstype": partition.fstype,
                "label": "",
                "model": "",
                "transport": "",
                "kind": _kind(Path(partition.device).name, None, False),
            }
        )
    return results


def usage(path):
    try:
        stat = psutil.disk_usage(str(path))
    except OSError:
        return {"total": 0, "used": 0, "free": 0, "percent": 0.0}
    return {"total": stat.total, "used": stat.used, "free": stat.free, "percent": stat.percent}


def _owning_mount(root, paths):
    if not root:
        return None
    root = os.path.abspath(root)
    best = None
    for path in paths:
        candidate = os.path.abspath(path)
        if root == candidate or root.startswith(candidate.rstrip("/") + "/"):
            if best is None or len(candidate) > len(best):
                best = candidate
    return best


def list_mounts():
    entries = _lsblk_mounts() or _psutil_mounts()
    selected = config.section("storage").get("root")
    mounts = []
    seen = set()
    for entry in entries:
        path = entry["path"]
        if path in seen:
            continue
        if path != "/" and path.startswith(IGNORED_PREFIXES):
            continue
        seen.add(path)
        entry.update(usage(path))
        entry["writable"] = os.access(path, os.W_OK)
        entry["has_data"] = (Path(path) / APP_FOLDER).exists()
        mounts.append(entry)
    owner = _owning_mount(selected, [entry["path"] for entry in mounts])
    for entry in mounts:
        entry["selected"] = owner is not None and os.path.abspath(entry["path"]) == owner
    mounts.sort(key=lambda item: (item["kind"] != "usb", item["path"]))
    return mounts


def root_path():
    root = config.section("storage").get("root")
    return Path(root) if root else None


def base_path():
    root = root_path()
    return root / APP_FOLDER if root else None


def is_available():
    base = base_path()
    return bool(base and base.parent.exists() and os.access(base.parent, os.W_OK))


def select_root(path):
    target = Path(path).expanduser().resolve()
    if not target.is_dir():
        raise ValueError("Path does not exist")
    if not os.access(target, os.W_OK):
        raise ValueError("Path is not writable")
    base = target / APP_FOLDER
    base.mkdir(parents=True, exist_ok=True)
    probe = base / ".raspicam_write_test"
    try:
        probe.write_text("ok")
        probe.unlink()
    except OSError as error:
        raise ValueError("Unable to write to this location: {}".format(error))
    config.update_section("storage", {"root": str(target)})
    return str(target)


def camera_paths(camera_id):
    base = base_path()
    if not base:
        return None
    return {
        "recordings": base / camera_id / "recordings",
        "captures": base / camera_id / "captures",
    }


def ensure_camera_dirs(camera_id):
    paths = camera_paths(camera_id)
    if not paths:
        return None
    for path in paths.values():
        path.mkdir(parents=True, exist_ok=True)
    return paths


def remove_camera_dirs(camera_id):
    base = base_path()
    if not base:
        return
    target = base / camera_id
    if target.exists():
        shutil.rmtree(target, ignore_errors=True)


def summary():
    root = root_path()
    settings = config.section("storage")
    if not root or not root.exists():
        return {
            "configured": bool(root),
            "available": False,
            "root": str(root) if root else None,
            "settings": settings,
        }
    stats = usage(root)
    stats.update(
        {
            "configured": True,
            "available": True,
            "root": str(root),
            "settings": settings,
        }
    )
    return stats
