#!/usr/bin/env python3
from __future__ import annotations

import os
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


HOST = os.getenv("VHF_UI_HOST", "0.0.0.0")
PORT = int(os.getenv("VHF_UI_PORT", "8766"))
BACKEND = os.getenv("VHF_UI_BACKEND", "http://127.0.0.1:8000").rstrip("/")
ROOT = Path(__file__).resolve().parent


class PrototypeGateway(SimpleHTTPRequestHandler):
    def __init__(self, *args: object, **kwargs: object) -> None:
        super().__init__(*args, directory=str(ROOT), **kwargs)

    def do_GET(self) -> None:
        if self.path.startswith("/api/"):
            self._proxy()
            return
        super().do_GET()

    def do_POST(self) -> None:
        self._proxy()

    def do_PATCH(self) -> None:
        self._proxy()

    def do_DELETE(self) -> None:
        self._proxy()

    def do_OPTIONS(self) -> None:
        self._proxy()

    def end_headers(self) -> None:
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
        self.send_header("Pragma", "no-cache")
        self.send_header("Expires", "0")
        super().end_headers()

    def _proxy(self) -> None:
        if not self.path.startswith("/api/"):
            self.send_error(404)
            return

        body_length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(body_length) if body_length else None
        headers = {
            key: value
            for key, value in self.headers.items()
            if key.lower() not in {"host", "content-length", "connection", "accept-encoding"}
        }
        request = Request(
            f"{BACKEND}{self.path}",
            data=body,
            headers=headers,
            method=self.command,
        )
        try:
            with urlopen(request, timeout=180) as response:
                payload = response.read()
                self.send_response(response.status)
                self._copy_response_headers(response.headers)
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)
        except HTTPError as exc:
            payload = exc.read()
            self.send_response(exc.code)
            self._copy_response_headers(exc.headers)
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
        except URLError as exc:
            payload = f"Backend unavailable: {exc.reason}".encode("utf-8")
            self.send_response(502)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

    def _copy_response_headers(self, headers: object) -> None:
        for key, value in headers.items():
            if key.lower() not in {"content-length", "connection", "content-encoding"}:
                self.send_header(key, value)


if __name__ == "__main__":
    print(f"Serving prototype gateway on http://{HOST}:{PORT}")
    print(f"Proxying /api/* to {BACKEND}")
    ThreadingHTTPServer((HOST, PORT), PrototypeGateway).serve_forever()
