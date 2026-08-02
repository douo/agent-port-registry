#!/usr/bin/env python3
"""Minimal LAN-accessible probe: prints process env as JSON on GET /."""

from __future__ import annotations

import json
import os
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: lan_probe_server.py <port>", file=sys.stderr)
        return 2
    port = int(sys.argv[1])

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            payload = {
                "ok": True,
                "port": port,
                "pid": os.getpid(),
                "cwd": os.getcwd(),
                "SHELL": os.environ.get("SHELL"),
                "USER": os.environ.get("USER"),
                "HOME": os.environ.get("HOME"),
                "PATH": os.environ.get("PATH"),
                "keys": sorted(os.environ.keys()),
            }
            body = json.dumps(payload, ensure_ascii=False, indent=2).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args) -> None:  # noqa: A003
            # Keep APR service log clean; banner is enough.
            return

    print(f"listening 0.0.0.0:{port}", flush=True)
    HTTPServer(("0.0.0.0", port), Handler).serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
