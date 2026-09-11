#!/usr/bin/env python3
"""
Hub local API server.
Run: python hub/server.py
Then open: http://localhost:7000
"""

import base64
import hashlib
import hmac
import http.server
import re
import socketserver
import json
import os
import secrets
import shutil
import sqlite3
import ssl
import struct
import subprocess
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime

# ── Kernel imports ────────────────────────────────────────────────────────────
from kernel.db   import db_conn, db_ensure_tables, DB_PATH
from kernel.ssh  import ssh_run, LOCAL_MODE, SSH_HOST, SSH_USER, SERVER_IP
from kernel.log  import log_activity, activity_recent, _ntfy_send, _docker_event_loop
from kernel import router
from kernel.auth import (
    check_auth, gate_check, gate_create,
    _totp_hotp, totp_verify, totp_new_secret, totp_verify_secret, totp_uri,
    _sessions, _users_lock, _gate_sessions, _gate_lock,
)

from kernel.collect import PORT, _port_scan_loop

# ── HTTP handler ───────────────────────────────────────────────────────────────

# 20200008  _route — bridge from the HTTP server into kernel.router.
# HUB_ROUTER=legacy falls back to the original if/elif chain below.
ROUTER_MODE = os.environ.get('HUB_ROUTER', 'dispatch').lower()


def _route(handler, method, path, body=None):
    """Try the kernel dispatch table. Returns False to fall through to legacy."""
    if ROUTER_MODE == 'legacy':
        return False
    params = {}
    if '?' in handler.path:
        qs = handler.path.split('?', 1)[1]
        params = {k: v[0] for k, v in urllib.parse.parse_qs(qs).items()}
    return router.dispatch(handler, method, path, params, body, db_conn)


class Handler(http.server.BaseHTTPRequestHandler):
    # 20200309  Handler.log_message — suppress default access logging
    def log_message(self, fmt, *args):
        pass

    # 20200310  Handler.send_json — serialize + write JSON response with CORS
    def send_json(self, data, status=200):
        body = json.dumps(data, default=str).encode()
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()
        self.wfile.write(body)

    # 20200311  Handler.do_OPTIONS — CORS preflight
    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type, X-Hub-Token')
        self.end_headers()

    # 20200312  Handler.get_body — parse JSON request body
    def get_body(self):
        n = int(self.headers.get('Content-Length', 0))
        return json.loads(self.rfile.read(n)) if n else {}

    def do_GET(self):
        p = self.path.split('?')[0]
        if _route(self, 'GET', p):
            return
        self.send_response(404)
        self.end_headers()

    def do_POST(self):
        p = self.path.split('?')[0]
        body = self.get_body()
        if _route(self, 'POST', p, body):
            return
        self.send_response(404)
        self.end_headers()


if __name__ == '__main__':
    db_ensure_tables()
    # Start background port scanner
    _scan_thread = threading.Thread(target=_port_scan_loop, daemon=True)
    _scan_thread.start()
    # Start Docker event watcher
    _docker_thread = threading.Thread(target=_docker_event_loop, args=(db_conn, ssh_run, _ntfy_send), daemon=True)
    _docker_thread.start()
    # Log startup
    log_activity(db_conn, 'Hub started', 'hub', 'startup', f'port={PORT}', 'info')
    print(f'\n  Server Hub API  —  http://localhost:{PORT}')
    print(f'  SSH: {SSH_HOST}  |  DB: {DB_PATH}\n')
    class ThreadedServer(socketserver.ThreadingMixIn, http.server.HTTPServer):
        daemon_threads = True
    server = ThreadedServer(('0.0.0.0', PORT), Handler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print('\n  Hub stopped.')
