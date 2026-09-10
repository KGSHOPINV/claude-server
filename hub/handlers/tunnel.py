#!/usr/bin/env python3
"""
# 20204008  handlers.tunnel -- Cloudflare tunnel start/stop endpoints
Hub handler module: tunnel layer (module 08).
"""
import json
import os
import re
import subprocess
import threading
import time

from kernel.db   import db_conn
from kernel.ssh  import ssh_run
from kernel.auth import check_auth, gate_check

PORT = int(os.environ.get('HUB_PORT', 8765))

# ── Tunnel management ─────────────────────────────────────────────────────────

_tunnel_url    = ''
_tunnel_lock_t = threading.Lock()
_tunnel_thread = None


# 20208301  _tunnel_watcher — background thread: poll docker logs for trycloudflare URL
def _tunnel_watcher():
    """Background thread: poll server-hub-tunnel logs to extract the public URL."""
    global _tunnel_url
    while True:
        try:
            r = subprocess.run(
                ['docker', 'logs', '--tail', '80', 'server-hub-tunnel'],
                capture_output=True, text=True, timeout=6
            )
            m = re.search(r'https://[a-z0-9\-]+\.trycloudflare\.com', r.stdout + r.stderr)
            with _tunnel_lock_t:
                _tunnel_url = m.group(0) if m else _tunnel_url
        except Exception:
            pass
        time.sleep(4)


# 20208303  tunnel_start — docker run cloudflared; start watcher thread
def tunnel_start():
    global _tunnel_url, _tunnel_thread
    try:
        subprocess.run(['docker', 'rm', '-f', 'server-hub-tunnel'], capture_output=True, timeout=8)
        r = subprocess.run(
            ['docker', 'run', '-d', '--name', 'server-hub-tunnel', '--network', 'host',
             'cloudflare/cloudflared:latest', 'tunnel', '--url', f'http://localhost:{PORT}'],
            capture_output=True, text=True, timeout=30
        )
        if r.returncode == 0:
            with _tunnel_lock_t:
                _tunnel_url = ''
            if _tunnel_thread is None or not _tunnel_thread.is_alive():
                _tunnel_thread = threading.Thread(target=_tunnel_watcher, daemon=True)
                _tunnel_thread.start()
            return True
        return False
    except Exception:
        return False


# 20208304  tunnel_stop — docker stop + rm server-hub-tunnel
def tunnel_stop():
    global _tunnel_url
    try:
        subprocess.run(['docker', 'stop', 'server-hub-tunnel'], capture_output=True, timeout=15)
        subprocess.run(['docker', 'rm', 'server-hub-tunnel'], capture_output=True, timeout=10)
        with _tunnel_lock_t:
            _tunnel_url = ''
        return True
    except Exception:
        return False


# ── Route handlers ────────────────────────────────────────────────────────────

# 20308701  POST /api/tunnel/start — start Cloudflare tunnel
def post_tunnel_start(handler, body):
    if not gate_check(handler.headers, 2, db_conn):
        handler.send_json({'error': 'gate_required', 'layer': 2,
                           'message': 'Tunnel control requires TOTP verification'}, 403)
        return
    ok = tunnel_start()
    handler.send_json({'ok': ok})


# 20308702  POST /api/tunnel/stop — stop Cloudflare tunnel
def post_tunnel_stop(handler, body):
    if not gate_check(handler.headers, 2, db_conn):
        handler.send_json({'error': 'gate_required', 'layer': 2,
                           'message': 'Tunnel control requires TOTP verification'}, 403)
        return
    ok = tunnel_stop()
    handler.send_json({'ok': ok})
