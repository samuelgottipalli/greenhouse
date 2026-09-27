"""
Background service that serves controller code for over-the-air updates.

Run from the ``server/`` folder with ``python -m services.firmware_server``.
It answers plain HTTP on ``FIRMWARE_PORT`` (default 8081) on the LAN:

* ``GET /manifest.json``: the current manifest (``core/firmware.py``).
* ``GET /files/<path>``: one file listed in the manifest. Nothing else is
  served, so the folder's settings files and anything outside it stay private.

Files are read fresh for every request, so a newer checkout is offered at
once. Controllers check each file's SHA-256 against the manifest they got
over MQTT, so a tampered download is refused rather than installed.
"""
import logging
import threading
from functools import partial
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from time import sleep

from core import firmware, settings
from core.health import Heartbeat

log = logging.getLogger(__name__)

WATCH_SECONDS = 10


class FirmwareHandler(BaseHTTPRequestHandler):
    """Serves the manifest and the files it lists; everything else is 404."""

    def __init__(self, *args, device_dir: Path | None = None, **kwargs):
        self.device_dir = device_dir or firmware.DEVICE_DIR
        super().__init__(*args, **kwargs)

    def do_GET(self) -> None:  # noqa: N802 (http.server naming)
        """Answer one GET request."""
        path = self.path.split("?", 1)[0]
        if path == "/manifest.json":
            import json

            body = json.dumps(firmware.manifest(self.device_dir)).encode("utf-8")
            self._send(200, body, "application/json")
            return
        if path.startswith("/files/"):
            relative = path[len("/files/"):]
            if relative in firmware.updatable_files(self.device_dir):
                self._send(200, firmware.file_bytes(self.device_dir, relative), "text/x-python")
                return
        self._send(404, b"not found\n", "text/plain")

    def _send(self, status: int, body: bytes, content_type: str) -> None:
        """Write a complete response."""
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt: str, *args) -> None:
        """Send request logs to the logging module instead of stderr."""
        log.info("%s %s", self.address_string(), fmt % args)


def make_server(port: int = settings.FIRMWARE_PORT, host: str = "0.0.0.0",
                device_dir: Path | None = None) -> ThreadingHTTPServer:
    """
    Build the HTTP server (not yet serving).

    Args:
        port (int): TCP port (0 picks a free one, for tests).
        host (str): Address to listen on.
        device_dir (Path | None): Controller code folder.

    Returns:
        ThreadingHTTPServer: Ready for ``serve_forever``.
    """
    return ThreadingHTTPServer((host, port), partial(FirmwareHandler, device_dir=device_dir))


def main() -> None:
    """Serve forever, beating the heartbeat while the server thread is alive."""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    server = make_server()
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    log.info("Serving controller code on port %s", settings.FIRMWARE_PORT)
    heartbeat = Heartbeat("firmware")
    while thread.is_alive():
        heartbeat.beat(True, f"version {firmware.available_version()}")
        sleep(WATCH_SECONDS)
    log.error("Firmware server thread stopped")


if __name__ == "__main__":
    main()
