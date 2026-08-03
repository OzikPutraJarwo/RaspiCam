import os
import re

from fastapi.responses import Response, StreamingResponse

CHUNK_SIZE = 512 * 1024
RANGE_PATTERN = re.compile(r"bytes=(\d*)-(\d*)")


def _reader(path, start, length):
    async def generator():
        remaining = length
        with open(path, "rb") as handle:
            handle.seek(start)
            while remaining > 0:
                chunk = handle.read(min(CHUNK_SIZE, remaining))
                if not chunk:
                    break
                remaining -= len(chunk)
                yield chunk

    return generator()


def ranged_response(path, request, media_type, filename=None, download=False):
    size = os.path.getsize(path)
    disposition = "attachment" if download else "inline"
    headers = {
        "Accept-Ranges": "bytes",
        "Content-Disposition": '{}; filename="{}"'.format(disposition, filename or os.path.basename(path)),
        "Cache-Control": "private, max-age=300",
    }
    range_header = request.headers.get("range")
    match = RANGE_PATTERN.fullmatch(range_header.strip()) if range_header else None
    if not match:
        headers["Content-Length"] = str(size)
        return StreamingResponse(_reader(path, 0, size), media_type=media_type, headers=headers)
    start_raw, end_raw = match.groups()
    if start_raw:
        start = int(start_raw)
        end = int(end_raw) if end_raw else size - 1
    else:
        length = int(end_raw or 0)
        start = max(0, size - length)
        end = size - 1
    if start >= size or start > end:
        return Response(status_code=416, headers={"Content-Range": "bytes */{}".format(size)})
    end = min(end, size - 1)
    length = end - start + 1
    headers["Content-Range"] = "bytes {}-{}/{}".format(start, end, size)
    headers["Content-Length"] = str(length)
    return StreamingResponse(_reader(path, start, length), status_code=206, media_type=media_type, headers=headers)
