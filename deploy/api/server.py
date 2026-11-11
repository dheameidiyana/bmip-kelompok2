"""Placeholder API for W1-A.

The real FastAPI application is delivered by W1-D. This service exists so the
compose stack has a stable health target behind Traefik from day one.
"""

from __future__ import annotations

import json
import logging
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

LOG = logging.getLogger("bmip.api")


class Handler(BaseHTTPRequestHandler):
    server_version = "bmip-api/0.1"

    def _send(self, status: int, payload: dict[str, Any]) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802 - http.server API
        if self.path in ("/health/live", "/health/ready"):
            self._send(
                200,
                {
                    "status": "ok",
                    "service": "api",
                    "mode": "placeholder",
                    "env": os.getenv("BMIP_ENV", "dev"),
                },
            )
            return
        if self.path in ("/api", "/api/"):
            self._send(
                200,
                {
                    "service": "bmip-api",
                    "status": "placeholder",
                    "message": "API content is owned by W1-D",
                    "health": ["/health/live", "/health/ready"],
                },
            )
            return
        self._send(404, {"status": "not_found", "path": self.path})

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
        LOG.info("%s - %s", self.address_string(), format % args)


def main() -> None:
    logging.basicConfig(
        level=os.getenv("BMIP_LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    host = os.getenv("API_HOST", "0.0.0.0")
    port = int(os.getenv("API_PORT", "8000"))
    server = ThreadingHTTPServer((host, port), Handler)
    LOG.info("placeholder api listening on %s:%s", host, port)
    server.serve_forever()


if __name__ == "__main__":
    main()
