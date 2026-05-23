#!/usr/bin/env python3
"""LAN static server for the llmchar-viz web app.

Bound to all interfaces (so other devices on the LAN can reach it) and sends
`Cache-Control: no-cache` on every response, so browsers always revalidate
against the server instead of silently serving a stale cached module or DB.
Unchanged files come back as fast 304s; anything I rebuild/edit is picked up on
the next reload. Serves the repo root so /web/ and /llmchar.db keep the same
relative paths as a GitHub Pages deploy.

Usage: python3 scripts/serve.py [port]   (default 8000)
"""
from __future__ import annotations

import http.server
import socketserver
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8000


class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *a, **k):
        super().__init__(*a, directory=str(ROOT), **k)

    def end_headers(self):
        # force revalidation so devices never get a stale app/DB
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Access-Control-Allow-Origin", "*")
        super().end_headers()


class Server(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


if __name__ == "__main__":
    with Server(("0.0.0.0", PORT), Handler) as httpd:
        print(f"serving {ROOT}")
        print(f"  http://localhost:{PORT}/web/   (this machine)")
        print(f"  http://<LAN-IP>:{PORT}/web/    (other devices; Cache-Control: no-cache)")
        httpd.serve_forever()
