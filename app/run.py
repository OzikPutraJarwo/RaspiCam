import os

import uvicorn

from .config import config


def main():
    settings = config.section("server")
    port = int(os.environ.get("RASPICAM_PORT") or settings.get("port") or 8080)
    if port != settings.get("port"):
        config.update_section("server", {"port": port})
    uvicorn.run(
        "app.main:app",
        host=os.environ.get("RASPICAM_HOST", "0.0.0.0"),
        port=port,
        log_level=os.environ.get("RASPICAM_LOG", "warning"),
        access_log=False,
        ws_ping_interval=25,
        ws_ping_timeout=25,
    )


if __name__ == "__main__":
    main()
