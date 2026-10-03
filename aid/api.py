"""Local incident board. It reads the same rows the engine wrote."""

import json
import logging
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

from aid.config import API_PORT, ROOT
from aid.store import make_store

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger("aid.api")

STORE = make_store()
PAGE = (ROOT / "web" / "index.html").read_bytes()


class Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path == "/":
            self._bytes(200, PAGE, "text/html; charset=utf-8")
            return
        try:
            if path == "/api/incidents":
                self._json(200, STORE.list_incidents())
                return
            if path == "/api/stats":
                stats = STORE.stats()
                stats["note"] = "log_samples counts evidence rows, not the Kafka topic"
                self._json(200, stats)
                return
        except Exception as exc:
            log.exception("read failed")
            self._json(503, {"error": str(exc)})
            return
        self._json(404, {"error": "not found"})

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        parts = [part for part in path.split("/") if part]
        if len(parts) == 4 and parts[:2] == ["api", "incidents"] and parts[3] == "status":
            try:
                length = int(self.headers.get("content-length", "0"))
                body = json.loads(self.rfile.read(length) or b"{}")
                updated = STORE.set_status(parts[2], body["status"])
            except (KeyError, ValueError, json.JSONDecodeError) as exc:
                self._json(400, {"error": str(exc)})
                return
            if updated is None:
                self._json(404, {"error": "incident not found"})
                return
            self._json(200, updated)
            return
        self._json(404, {"error": "not found"})

    def log_message(self, fmt: str, *args) -> None:
        log.info("%s %s", self.address_string(), fmt % args)

    def _json(self, status: int, payload) -> None:
        self._bytes(status, json.dumps(payload).encode(), "application/json")

    def _bytes(self, status: int, payload: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("content-type", content_type)
        self.send_header("content-length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)


def main() -> None:
    try:
        STORE.ping()
    except Exception as exc:
        log.warning("database not ready yet: %s", exc)
    server = ThreadingHTTPServer(("0.0.0.0", API_PORT), Handler)
    log.info("incident board on http://localhost:%s", API_PORT)
    server.serve_forever()


if __name__ == "__main__":
    main()
