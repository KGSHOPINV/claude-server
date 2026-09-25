#!/usr/bin/env python3
"""
Hub local API server.
Run: python hub/server.py
Then open: http://localhost:7000
"""

import http.server
import socketserver
import json
import os
import threading
import urllib.parse

# Removed: base64, hashlib, hmac, re, secrets, shutil, sqlite3, ssl, struct,
# subprocess, time, urllib.error, urllib.request, datetime.datetime. Leftovers
# from the pre-Phase-2 monolith; every user of them moved to kernel/ or
# handlers/ and none is referenced in this file any more.

# ── Kernel imports ────────────────────────────────────────────────────────────
from kernel.db   import db_conn, db_ensure_tables, DB_PATH
from kernel.ssh  import ssh_run, SSH_HOST          # LOCAL_MODE/SSH_USER/SERVER_IP: unused here
from kernel.log  import log_activity, _ntfy_send, _docker_event_loop
from kernel import router
# Removed: the `from kernel.auth import (...)` block. All twelve names were
# unused here after the handler split -- kernel.auth is imported by
# kernel.router._gate_allows and by the handler modules that actually need it.

from kernel.collect import PORT, _port_scan_loop

# ── HTTP handler ───────────────────────────────────────────────────────────────

# 20200008  _route — bridge from the HTTP server into kernel.router.
# NOT A FALLBACK. The if/elif chain this used to fall back to was deleted in the
# Phase 2 handler split; there is nothing below to fall through to. Setting
# HUB_ROUTER=legacy today makes _route return False for every request, so the
# hub answers 404 to everything. Kept only because removing the switch would
# change behaviour for anyone who has it set. Nothing in this repo sets it.
ROUTER_MODE = os.environ.get('HUB_ROUTER', 'dispatch').lower()

# HUB_LOG_REQUESTS=1 logs every request with its source address and any
# Cloudflare Access identity headers. Off by default -- the hub has never logged
# requests, which is why 'is Cloudflare even reaching the origin' was unanswerable.
LOG_REQUESTS = os.environ.get('HUB_LOG_REQUESTS', '0').lower() not in ('0', 'false', '')


def _route(handler, method, path, body=None):
    """Try the kernel dispatch table. Returns False -> caller answers 404."""
    if ROUTER_MODE == 'legacy':
        return False  # see ROUTER_MODE above: this 404s everything, by accident
    params = {}
    if '?' in handler.path:
        qs = handler.path.split('?', 1)[1]
        params = {k: v[0] for k, v in urllib.parse.parse_qs(qs).items()}
    return router.dispatch(handler, method, path, params, body, db_conn)


class Handler(http.server.BaseHTTPRequestHandler):
    # 20200309  Handler.log_message — access logging, off unless HUB_LOG_REQUESTS=1
    def log_message(self, fmt, *args):
        if not LOG_REQUESTS:
            return
        try:
            src = self.client_address[0]
        except Exception:
            src = '?'
        email = jwt = '-'
        try:
            if self.headers:
                email = self.headers.get('Cf-Access-Authenticated-User-Email', '-') or '-'
                jwt = 'yes' if self.headers.get('Cf-Access-Jwt-Assertion') else '-'
        except Exception:
            pass
        try:
            msg = fmt % args
        except Exception:
            msg = str(fmt)
        print('REQ src=%s cf_email=%s cf_jwt=%s :: %s' % (src, email, jwt, msg), flush=True)

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
    # Identity + mesh. NODE mode emits heartbeats to central; CENTRAL receives
    # them. Same codebase — server.identity.json decides which.
    from kernel import identity as _identity
    from kernel import heartbeat as _heartbeat
    from handlers.node import node_payload
    _identity.ensure_file()
    print(f'  identity: {_identity.server_id()} ({_identity.node_name()}) mode={_identity.mode()}')
    if not _identity.is_central():
        _heartbeat.start(
            node_payload,
            lambda m: log_activity(db_conn, m, 'mesh', 'heartbeat', '', 'info'))
        print('  heartbeat: emitting to central every %ds' % _heartbeat.INTERVAL)
    else:
        print('  mode: CENTRAL — receiving heartbeats')

    # Outbound delivery. Started EXPLICITLY, never on import -- a worker that
    # spins up merely because a module was imported also runs inside every
    # tool, test and one-off script that touches it, and then two processes
    # are pushing the same queue.
    #
    # Until this line runs the push leg is inert, and outbox.worker_state()
    # says NOT STARTED in words rather than showing a zero count that looks
    # like 'nothing to send'.
    from kernel import outbox as _outbox
    _outbox.start(lambda m: log_activity(db_conn, m, 'outbox', 'delivery', '', 'warn'))
    print('  outbox: delivery worker started')

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
