import array
import fcntl
import glob
import os
import re
import shutil
import struct
import subprocess
from pathlib import Path

_IOC_WRITE = 1
_IOC_READ = 2

V4L2_CAP_VIDEO_CAPTURE = 0x00000001
V4L2_CAP_DEVICE_CAPS = 0x80000000
V4L2_BUF_TYPE_VIDEO_CAPTURE = 1
V4L2_FRMSIZE_TYPE_DISCRETE = 1
V4L2_FRMIVAL_TYPE_DISCRETE = 1

EXCLUDED_DRIVERS = {
    "bcm2835-isp",
    "bcm2835-codec",
    "unicam",
    "rpivid",
    "pispbe",
    "rp1-cfe",
    "rpi-hevc-dec",
}

PREFERRED_FORMATS = ["MJPG", "H264", "YUYV", "NV12", "GREY"]
FORMAT_ALIASES = {"MJPG": "mjpeg", "H264": "h264", "YUYV": "yuyv422", "NV12": "nv12", "GREY": "gray"}


def _ioc(direction, code, number, size):
    return (direction << 30) | (size << 16) | (code << 8) | number


VIDIOC_QUERYCAP = _ioc(_IOC_READ, ord("V"), 0, 104)
VIDIOC_ENUM_FMT = _ioc(_IOC_READ | _IOC_WRITE, ord("V"), 2, 64)
VIDIOC_ENUM_FRAMESIZES = _ioc(_IOC_READ | _IOC_WRITE, ord("V"), 74, 44)
VIDIOC_ENUM_FRAMEINTERVALS = _ioc(_IOC_READ | _IOC_WRITE, ord("V"), 75, 52)


def _text(raw):
    return raw.split(b"\x00", 1)[0].decode("utf-8", "replace").strip()


def _fourcc(value):
    return struct.pack("<I", value & 0x7FFFFFFF).decode("ascii", "replace").strip()


def _querycap(fd):
    buffer = array.array("B", bytes(104))
    fcntl.ioctl(fd, VIDIOC_QUERYCAP, buffer, True)
    driver, card, bus_info, _version, caps, device_caps = struct.unpack("16s32s32sIII12x", buffer.tobytes())
    effective = device_caps if caps & V4L2_CAP_DEVICE_CAPS else caps
    return {
        "driver": _text(driver),
        "card": _text(card),
        "bus": _text(bus_info),
        "capabilities": effective,
    }


def _enum_formats(fd):
    formats = []
    for index in range(32):
        payload = struct.pack("III32sI16x", index, V4L2_BUF_TYPE_VIDEO_CAPTURE, 0, b"", 0)
        buffer = array.array("B", payload)
        try:
            fcntl.ioctl(fd, VIDIOC_ENUM_FMT, buffer, True)
        except OSError:
            break
        _index, _type, _flags, description, pixelformat = struct.unpack("III32sI16x", buffer.tobytes())
        formats.append(
            {
                "fourcc": _fourcc(pixelformat),
                "pixelformat": pixelformat,
                "description": _text(description),
            }
        )
    return formats


def _enum_frame_sizes(fd, pixelformat):
    sizes = []
    for index in range(64):
        buffer = array.array("B", struct.pack("III", index, pixelformat, 0) + bytes(32))
        try:
            fcntl.ioctl(fd, VIDIOC_ENUM_FRAMESIZES, buffer, True)
        except OSError:
            break
        raw = buffer.tobytes()
        _index, _pixelformat, size_type = struct.unpack("III", raw[:12])
        if size_type == V4L2_FRMSIZE_TYPE_DISCRETE:
            width, height = struct.unpack("II", raw[12:20])
            sizes.append((width, height))
        else:
            min_w, max_w, step_w, min_h, max_h, step_h = struct.unpack("IIIIII", raw[12:36])
            width, height = min_w, min_h
            while width <= max_w and height <= max_h and len(sizes) < 16:
                sizes.append((width, height))
                if not step_w or not step_h:
                    break
                width += step_w
                height += step_h
            break
    return sizes


def _enum_frame_rates(fd, pixelformat, width, height):
    rates = []
    for index in range(32):
        payload = struct.pack("IIIII", index, pixelformat, width, height, 0) + bytes(32)
        buffer = array.array("B", payload)
        try:
            fcntl.ioctl(fd, VIDIOC_ENUM_FRAMEINTERVALS, buffer, True)
        except OSError:
            break
        raw = buffer.tobytes()
        interval_type = struct.unpack("I", raw[16:20])[0]
        if interval_type != V4L2_FRMIVAL_TYPE_DISCRETE:
            break
        numerator, denominator = struct.unpack("II", raw[20:28])
        if numerator:
            rates.append(round(denominator / numerator))
    return sorted({r for r in rates if r > 0}, reverse=True)


def _stable_path(device):
    for link in glob.glob("/dev/v4l/by-id/*"):
        try:
            if os.path.realpath(link) == os.path.realpath(device):
                return link
        except OSError:
            continue
    return device


def _device_number(path):
    match = re.search(r"(\d+)$", path)
    return int(match.group(1)) if match else 0


def list_v4l2_devices():
    devices = []
    for path in sorted(glob.glob("/dev/video*"), key=_device_number):
        try:
            fd = os.open(path, os.O_RDWR | os.O_NONBLOCK)
        except OSError:
            continue
        try:
            capability = _querycap(fd)
            if not capability["capabilities"] & V4L2_CAP_VIDEO_CAPTURE:
                continue
            if capability["driver"] in EXCLUDED_DRIVERS:
                continue
            formats = _enum_formats(fd)
            if not formats:
                continue
            modes = []
            for entry in formats:
                sizes = _enum_frame_sizes(fd, entry["pixelformat"])
                for width, height in sizes:
                    modes.append(
                        {
                            "format": entry["fourcc"],
                            "width": width,
                            "height": height,
                            "rates": _enum_frame_rates(fd, entry["pixelformat"], width, height),
                        }
                    )
            if not modes:
                continue
            devices.append(
                {
                    "type": "usb",
                    "device": _stable_path(path),
                    "node": path,
                    "name": capability["card"] or Path(path).name,
                    "driver": capability["driver"],
                    "bus": capability["bus"],
                    "formats": [entry["fourcc"] for entry in formats],
                    "modes": modes,
                }
            )
        except OSError:
            continue
        finally:
            os.close(fd)
    return devices


def libcamera_binary(name):
    return shutil.which("rpicam-" + name) or shutil.which("libcamera-" + name)


def list_csi_cameras():
    binary = libcamera_binary("hello")
    if not binary:
        return []
    try:
        result = subprocess.run(
            [binary, "--list-cameras"],
            capture_output=True,
            text=True,
            timeout=15,
        )
    except (OSError, subprocess.SubprocessError):
        return []
    output = result.stdout + result.stderr
    cameras = []
    current = None
    for line in output.splitlines():
        header = re.match(r"^\s*(\d+)\s*:\s*(\S+)\s*\[(\d+)x(\d+)", line)
        if header:
            current = {
                "type": "csi",
                "index": int(header.group(1)),
                "name": header.group(2),
                "device": "csi:" + header.group(1),
                "driver": "libcamera",
                "bus": "",
                "formats": ["H264"],
                "modes": [
                    {
                        "format": "H264",
                        "width": int(header.group(3)),
                        "height": int(header.group(4)),
                        "rates": [30, 15, 10],
                    }
                ],
            }
            cameras.append(current)
            continue
        mode = re.search(r"(\d+)x(\d+)\s*\[([\d.]+)\s*fps", line)
        if mode and current:
            width, height = int(mode.group(1)), int(mode.group(2))
            rate = int(float(mode.group(3)))
            existing = [m for m in current["modes"] if m["width"] == width and m["height"] == height]
            if existing:
                if rate not in existing[0]["rates"]:
                    existing[0]["rates"] = sorted(set(existing[0]["rates"] + [rate]), reverse=True)
            else:
                current["modes"].append(
                    {"format": "H264", "width": width, "height": height, "rates": [rate, 30, 15, 10]}
                )
    for camera in cameras:
        camera["modes"] = sorted(camera["modes"], key=lambda m: m["width"] * m["height"], reverse=True)[:8]
    return cameras


def discover():
    return list_v4l2_devices() + list_csi_cameras()


def default_settings(source):
    modes = source.get("modes") or []
    preferred = None
    for fourcc in PREFERRED_FORMATS:
        candidates = [m for m in modes if m["format"] == fourcc and m["width"] <= 1920]
        if candidates:
            preferred = sorted(candidates, key=lambda m: abs(m["width"] - 1280))[0]
            break
    if not preferred and modes:
        preferred = modes[0]
    if not preferred:
        return {"width": 1280, "height": 720, "fps": 15, "input_format": "mjpeg"}
    rates = preferred.get("rates") or [30]
    fps = min([r for r in rates if r <= 30] or [rates[-1]], key=lambda r: abs(r - 15))
    return {
        "width": preferred["width"],
        "height": preferred["height"],
        "fps": fps,
        "input_format": FORMAT_ALIASES.get(preferred["format"], "mjpeg"),
    }


def probe_network_source(url, timeout=12):
    binary = shutil.which("ffprobe")
    if not binary:
        return {"ok": False, "error": "ffprobe is not installed"}
    command = [
        binary,
        "-v",
        "error",
        "-rtsp_transport",
        "tcp",
        "-select_streams",
        "v:0",
        "-show_entries",
        "stream=width,height,codec_name,avg_frame_rate",
        "-of",
        "default=nw=1:nk=0",
        url,
    ]
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "Timed out while connecting"}
    except OSError as error:
        return {"ok": False, "error": str(error)}
    if result.returncode != 0:
        return {"ok": False, "error": (result.stderr or "Unable to open stream").strip().splitlines()[-1]}
    info = {}
    for line in result.stdout.splitlines():
        if "=" in line:
            key, value = line.split("=", 1)
            info[key.strip()] = value.strip()
    fps = 15
    if "/" in info.get("avg_frame_rate", ""):
        numerator, denominator = info["avg_frame_rate"].split("/", 1)
        try:
            if float(denominator):
                fps = max(1, round(float(numerator) / float(denominator)))
        except ValueError:
            fps = 15
    return {
        "ok": True,
        "width": int(info.get("width") or 1280),
        "height": int(info.get("height") or 720),
        "fps": fps,
        "codec": info.get("codec_name", ""),
    }
