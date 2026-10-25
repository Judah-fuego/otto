"""Local copilot: mint a Grok Voice token, run tools, serve the headset page."""

from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from app.alerts import alert_source
from app.tools import dispatch_tool
from app.voice import api_key, mint_ephemeral_token

STATIC = Path(__file__).resolve().parent / "static"
HOST = "127.0.0.1"
PORT = 8765


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt: str, *args) -> None:
        print(f"[otto] {self.address_string()} {fmt % args}")

    def _json(self, code: int, payload: dict) -> None:
        raw = json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def _bytes(self, code: int, body: bytes, content_type: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self) -> dict:
        length = int(self.headers.get("Content-Length", "0") or 0)
        if length <= 0:
            return {}
        return json.loads(self.rfile.read(length).decode())

    def do_GET(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        if path in {"/", "/index.html"}:
            self._bytes(200, (STATIC / "index.html").read_bytes(), "text/html; charset=utf-8")
            return
        if path == "/health":
            self._json(200, {"ok": True})
            return
        if path == "/alerts":
            alerts, source, live = alert_source()
            self._json(
                200,
                {
                    "live": live,
                    "source": source,
                    "alerts": [alert.to_dict() for alert in alerts],
                },
            )
            return
        self._json(404, {"error": "not found"})

    def do_POST(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        try:
            if path == "/session":
                self._json(200, mint_ephemeral_token())
                return
            if path == "/tool":
                body = self._read_json()
                result = dispatch_tool(str(body.get("name", "")), body.get("arguments") or {})
                self._json(200, result)
                return
        except Exception as exc:  # noqa: BLE001
            self._json(500, {"error": str(exc)})
            return
        self._json(404, {"error": "not found"})


def serve(host: str = HOST, port: int = PORT) -> None:
    try:
        api_key()
    except RuntimeError as exc:
        print(f"Warning: {exc}")
    httpd = ThreadingHTTPServer((host, port), Handler)
    print(f"Otto voice copilot: http://{host}:{port}")
    print("Say: I want to go to Mars.")
    httpd.serve_forever()
