import asyncio
import os
import shutil
import sqlite3
import subprocess
import time
from datetime import datetime

from . import storage
from .config import DATABASE_PATH, config
from .events import bus

SEGMENT_SUFFIX = ".mp4"
CAPTURE_SUFFIX = ".jpg"
NAME_FORMAT = "%Y-%m-%d_%H-%M-%S"
SETTLE_SECONDS = 8

SCHEMA = """
CREATE TABLE IF NOT EXISTS segments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    camera_id TEXT NOT NULL,
    path TEXT NOT NULL UNIQUE,
    start_ts REAL NOT NULL,
    duration REAL NOT NULL DEFAULT 0,
    size INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS segments_camera_start ON segments(camera_id, start_ts);
"""


def connect():
    connection = sqlite3.connect(DATABASE_PATH, timeout=15)
    connection.row_factory = sqlite3.Row
    return connection


def init():
    DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with connect() as connection:
        connection.executescript(SCHEMA)


def parse_timestamp(name):
    try:
        return time.mktime(datetime.strptime(name, NAME_FORMAT).timetuple())
    except ValueError:
        return None


def probe_duration(path):
    binary = shutil.which("ffprobe")
    if not binary:
        return 0.0
    try:
        result = subprocess.run(
            [
                binary,
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "default=nw=1:nk=1",
                str(path),
            ],
            capture_output=True,
            text=True,
            timeout=20,
        )
        return round(float(result.stdout.strip()), 2)
    except (OSError, ValueError, subprocess.SubprocessError):
        return 0.0


def _scan():
    base = storage.base_path()
    if not base or not base.exists():
        return 0
    added = 0
    now = time.time()
    with connect() as connection:
        known = {row["path"] for row in connection.execute("SELECT path FROM segments")}
        for camera in config.cameras():
            paths = storage.camera_paths(camera["id"])
            directory = paths["recordings"] if paths else None
            if not directory or not directory.exists():
                continue
            for entry in sorted(directory.glob("*" + SEGMENT_SUFFIX)):
                key = str(entry)
                if key in known:
                    continue
                try:
                    stat = entry.stat()
                except OSError:
                    continue
                if now - stat.st_mtime < SETTLE_SECONDS or stat.st_size == 0:
                    continue
                start_ts = parse_timestamp(entry.stem) or stat.st_mtime
                duration = probe_duration(entry)
                if duration <= 0:
                    try:
                        entry.unlink()
                    except OSError:
                        pass
                    continue
                connection.execute(
                    "INSERT OR IGNORE INTO segments (camera_id, path, start_ts, duration, size) VALUES (?, ?, ?, ?, ?)",
                    (camera["id"], key, start_ts, duration, stat.st_size),
                )
                added += 1
        for row in connection.execute("SELECT id, path FROM segments").fetchall():
            if not os.path.exists(row["path"]):
                connection.execute("DELETE FROM segments WHERE id = ?", (row["id"],))
    return added


async def scan():
    added = await asyncio.to_thread(_scan)
    if added:
        bus.publish({"type": "recordings", "added": added})
    return added


def _query(camera_id, start, end):
    with connect() as connection:
        rows = connection.execute(
            "SELECT * FROM segments WHERE camera_id = ? AND start_ts >= ? AND start_ts < ? ORDER BY start_ts",
            (camera_id, start, end),
        ).fetchall()
    return [dict(row) for row in rows]


async def query(camera_id, start, end):
    return await asyncio.to_thread(_query, camera_id, start, end)


def _days(camera_id):
    with connect() as connection:
        rows = connection.execute(
            "SELECT DISTINCT date(start_ts, 'unixepoch', 'localtime') AS day FROM segments "
            "WHERE camera_id = ? ORDER BY day DESC",
            (camera_id,),
        ).fetchall()
    return [row["day"] for row in rows]


async def days(camera_id):
    return await asyncio.to_thread(_days, camera_id)


def _segment(segment_id):
    with connect() as connection:
        row = connection.execute("SELECT * FROM segments WHERE id = ?", (segment_id,)).fetchone()
    return dict(row) if row else None


async def segment(segment_id):
    return await asyncio.to_thread(_segment, segment_id)


def _delete(segment_id):
    with connect() as connection:
        row = connection.execute("SELECT path FROM segments WHERE id = ?", (segment_id,)).fetchone()
        if not row:
            return False
        try:
            os.remove(row["path"])
        except OSError:
            pass
        connection.execute("DELETE FROM segments WHERE id = ?", (segment_id,))
    return True


async def delete(segment_id):
    return await asyncio.to_thread(_delete, segment_id)


def _delete_camera(camera_id):
    with connect() as connection:
        connection.execute("DELETE FROM segments WHERE camera_id = ?", (camera_id,))


async def delete_camera(camera_id):
    await asyncio.to_thread(_delete_camera, camera_id)


def _stats():
    with connect() as connection:
        row = connection.execute(
            "SELECT COUNT(*) AS count, COALESCE(SUM(size), 0) AS size, "
            "COALESCE(SUM(duration), 0) AS duration, MIN(start_ts) AS oldest, MAX(start_ts) AS newest FROM segments"
        ).fetchone()
    return dict(row)


async def stats():
    return await asyncio.to_thread(_stats)


def _captures(camera_id, limit=200):
    paths = storage.camera_paths(camera_id)
    if not paths or not paths["captures"].exists():
        return []
    entries = []
    for entry in sorted(paths["captures"].glob("*" + CAPTURE_SUFFIX), reverse=True)[:limit]:
        try:
            stat = entry.stat()
        except OSError:
            continue
        entries.append(
            {
                "name": entry.name,
                "size": stat.st_size,
                "timestamp": parse_timestamp(entry.stem) or stat.st_mtime,
            }
        )
    return entries


async def captures(camera_id, limit=200):
    return await asyncio.to_thread(_captures, camera_id, limit)


def capture_path(camera_id, name):
    paths = storage.camera_paths(camera_id)
    if not paths:
        return None
    candidate = (paths["captures"] / name).resolve()
    if candidate.parent != paths["captures"].resolve():
        return None
    return candidate if candidate.exists() else None


def _delete_capture(camera_id, name):
    target = capture_path(camera_id, name)
    if not target:
        return False
    try:
        target.unlink()
    except OSError:
        return False
    return True


async def delete_capture(camera_id, name):
    return await asyncio.to_thread(_delete_capture, camera_id, name)


def _enforce_retention():
    root = storage.root_path()
    if not root or not root.exists():
        return 0
    settings = config.section("storage")
    limit_percent = float(settings.get("retention_percent") or 85)
    min_free = float(settings.get("min_free_gb") or 2) * 1024 ** 3
    removed = 0
    with connect() as connection:
        while True:
            stat = storage.usage(root)
            if stat["total"] == 0:
                return removed
            over_percent = stat["percent"] > limit_percent
            under_free = stat["free"] < min_free
            if not over_percent and not under_free:
                return removed
            row = connection.execute(
                "SELECT id, path FROM segments WHERE start_ts < "
                "(SELECT MAX(start_ts) FROM segments AS newest WHERE newest.camera_id = segments.camera_id) "
                "ORDER BY start_ts LIMIT 1"
            ).fetchone()
            if not row:
                return removed
            try:
                os.remove(row["path"])
            except OSError:
                pass
            connection.execute("DELETE FROM segments WHERE id = ?", (row["id"],))
            connection.commit()
            removed += 1
            if removed > 5000:
                return removed


async def enforce_retention():
    removed = await asyncio.to_thread(_enforce_retention)
    if removed:
        bus.publish({"type": "retention", "removed": removed})
    return removed
