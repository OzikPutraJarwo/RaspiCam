import functools
import shutil
import subprocess

from .discovery import libcamera_binary

COPY_FRIENDLY_FORMATS = {"h264", "hevc"}


@functools.lru_cache(maxsize=1)
def ffmpeg_binary():
    return shutil.which("ffmpeg")


@functools.lru_cache(maxsize=1)
def available_encoders():
    binary = ffmpeg_binary()
    if not binary:
        return set()
    try:
        result = subprocess.run([binary, "-hide_banner", "-encoders"], capture_output=True, text=True, timeout=15)
    except (OSError, subprocess.SubprocessError):
        return set()
    encoders = set()
    for line in result.stdout.splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[0].startswith("V"):
            encoders.add(parts[1])
    return encoders


def encoder_works(name):
    binary = ffmpeg_binary()
    if not binary:
        return False
    command = [
        binary,
        "-hide_banner",
        "-loglevel",
        "error",
        "-f",
        "lavfi",
        "-i",
        "testsrc=size=320x240:rate=5",
        "-frames:v",
        "3",
        "-c:v",
        name,
        "-pix_fmt",
        "yuv420p",
        "-f",
        "null",
        "-",
    ]
    try:
        result = subprocess.run(command, capture_output=True, timeout=25)
    except (OSError, subprocess.SubprocessError):
        return False
    return result.returncode == 0


@functools.lru_cache(maxsize=1)
def preferred_encoder():
    encoders = available_encoders()
    for candidate in ("h264_v4l2m2m", "h264_omx", "libx264", "mpeg4"):
        if candidate in encoders and encoder_works(candidate):
            return candidate
    return "libx264"


def even(value):
    value = int(value)
    return value if value % 2 == 0 else value + 1


def preview_size(camera):
    width = min(int(camera.get("preview_width") or 640), int(camera.get("width") or 640))
    source_width = max(1, int(camera.get("width") or width))
    source_height = max(1, int(camera.get("height") or width))
    height = even(round(width * source_height / source_width))
    return even(width), max(2, height)


def rotation_filter(rotation):
    rotation = int(rotation or 0) % 360
    if rotation == 90:
        return "transpose=1"
    if rotation == 180:
        return "transpose=2,transpose=2"
    if rotation == 270:
        return "transpose=2"
    return ""


def input_arguments(camera):
    kind = camera.get("type")
    width = int(camera.get("width") or 1280)
    height = int(camera.get("height") or 720)
    fps = int(camera.get("fps") or 15)
    if kind == "usb":
        return [
            "-f",
            "v4l2",
            "-thread_queue_size",
            "512",
            "-input_format",
            camera.get("input_format") or "mjpeg",
            "-video_size",
            "{}x{}".format(width, height),
            "-framerate",
            str(fps),
            "-i",
            camera.get("device"),
        ]
    if kind == "csi":
        return ["-f", "h264", "-thread_queue_size", "512", "-framerate", str(fps), "-i", "pipe:0"]
    url = camera.get("url") or ""
    arguments = ["-thread_queue_size", "512"]
    if url.startswith("rtsp://"):
        arguments += ["-rtsp_transport", "tcp"]
    arguments += ["-fflags", "nobuffer", "-i", url]
    return arguments


def producer_command(camera):
    if camera.get("type") != "csi":
        return None
    binary = libcamera_binary("vid")
    if not binary:
        return None
    return [
        binary,
        "-t",
        "0",
        "--nopreview",
        "--flush",
        "--inline",
        "--camera",
        str(int(camera.get("index") or 0)),
        "--width",
        str(int(camera.get("width") or 1280)),
        "--height",
        str(int(camera.get("height") or 720)),
        "--framerate",
        str(int(camera.get("fps") or 15)),
        "--codec",
        "h264",
        "--bitrate",
        str(int(camera.get("bitrate") or 2500) * 1000),
        "-o",
        "-",
    ]


def source_is_h264(camera):
    if camera.get("type") == "csi":
        return True
    if camera.get("type") == "usb":
        return (camera.get("input_format") or "").lower() in COPY_FRIENDLY_FORMATS
    return True


def preview_output(camera):
    width, height = preview_size(camera)
    filters = ["fps={}".format(max(1, int(camera.get("preview_fps") or 10)))]
    rotate = rotation_filter(camera.get("rotation"))
    if rotate:
        filters.append(rotate)
    filters.append("scale={}:{}".format(width, height))
    return [
        "-map",
        "0:v:0",
        "-an",
        "-vf",
        ",".join(filters),
        "-c:v",
        "mjpeg",
        "-q:v",
        str(max(2, min(31, int(camera.get("preview_quality") or 7)))),
        "-f",
        "image2pipe",
        "pipe:1",
    ]


def record_output(camera, pattern, segment_seconds):
    fps = int(camera.get("fps") or 15)
    bitrate = int(camera.get("bitrate") or 2500)
    rotate = rotation_filter(camera.get("rotation"))
    arguments = ["-map", "0:v:0", "-an"]
    if source_is_h264(camera) and not rotate:
        arguments += ["-c:v", "copy"]
    else:
        encoder = preferred_encoder()
        if rotate:
            arguments += ["-vf", rotate]
        arguments += [
            "-c:v",
            encoder,
            "-b:v",
            "{}k".format(bitrate),
            "-maxrate",
            "{}k".format(bitrate),
            "-bufsize",
            "{}k".format(bitrate * 2),
            "-g",
            str(max(2, fps * 2)),
            "-pix_fmt",
            "yuv420p",
        ]
        if encoder == "libx264":
            arguments += ["-preset", "veryfast", "-tune", "zerolatency"]
    arguments += [
        "-f",
        "segment",
        "-segment_format",
        "mp4",
        "-segment_time",
        str(int(segment_seconds)),
        "-segment_atclocktime",
        "1",
        "-reset_timestamps",
        "1",
        "-strftime",
        "1",
        pattern,
    ]
    return arguments


def build_command(camera, record_pattern=None, segment_seconds=300):
    binary = ffmpeg_binary()
    if not binary:
        raise RuntimeError("ffmpeg is not installed")
    command = [binary, "-hide_banner", "-loglevel", "warning", "-nostdin"]
    if camera.get("type") != "csi":
        command += ["-use_wallclock_as_timestamps", "1"]
    command += input_arguments(camera)
    command += preview_output(camera)
    if record_pattern:
        command += record_output(camera, record_pattern, segment_seconds)
    return command


def snapshot_command(camera):
    if camera.get("type") == "csi":
        binary = libcamera_binary("still")
        if not binary:
            raise RuntimeError("rpicam-still is not installed")
        return [
            binary,
            "-t",
            "800",
            "-n",
            "--camera",
            str(int(camera.get("index") or 0)),
            "--width",
            str(int(camera.get("width") or 1280)),
            "--height",
            str(int(camera.get("height") or 720)),
            "--rotation",
            str(int(camera.get("rotation") or 0) % 360 if int(camera.get("rotation") or 0) % 360 in (0, 180) else 0),
            "-o",
            "-",
        ]
    binary = ffmpeg_binary()
    if not binary:
        raise RuntimeError("ffmpeg is not installed")
    command = [binary, "-hide_banner", "-loglevel", "error", "-nostdin"]
    command += input_arguments(camera)
    rotate = rotation_filter(camera.get("rotation"))
    if rotate:
        command += ["-vf", rotate]
    command += ["-frames:v", "1", "-q:v", "3", "-f", "image2pipe", "-vcodec", "mjpeg", "pipe:1"]
    return command
