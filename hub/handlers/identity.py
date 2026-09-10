#!/usr/bin/env python3
"""
# 20204001  handlers.identity — serve app shell, identity, access endpoints
Hub handler module: identity layer (module 01).
Imports only from kernel/. No direct DB access except via kernel.db.
"""
import json
import os

from kernel.db   import db_conn
from kernel.auth import check_auth, gate_check

# ── Module-level constants (re-derived locally to match server.py) ─────────────
PORT        = int(os.environ.get('HUB_PORT', 8765))
_BASE_DIR   = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # hub/
APP_PATH    = os.path.join(_BASE_DIR, 'app.html')
MOBILE_PATH = os.path.join(_BASE_DIR, 'mobile.html')


# ── Local helpers ─────────────────────────────────────────────────────────────

def _config_get_all():
    """Return all hub_config keys as a dict."""
    try:
        conn = db_conn()
        rows = conn.execute("SELECT key,value FROM hub_config").fetchall()
        conn.close()
        return {r['key']: r['value'] for r in rows}
    except Exception:
        return {}


# ── Route handlers ────────────────────────────────────────────────────────────
# One function per route. Each takes (handler, path, params) where:
#   handler = the HTTPRequestHandler instance (has .send_response, .send_header, etc.)
#   path    = the parsed URL path string
#   params  = dict of query params

def serve_app(handler, path, params):
    """# 20301701  GET / /mobile /desktop — serve app.html or mobile.html"""
    ua = handler.headers.get('User-Agent', '')
    is_mobile = any(x in ua for x in ('Mobile', 'Android', 'iPhone', 'iPad', 'iPod', 'BlackBerry', 'Windows Phone'))
    if path == '/' and is_mobile:
        handler.send_response(302)
        handler.send_header('Location', '/mobile')
        handler.end_headers()
        return
    fpath = MOBILE_PATH if (path == '/mobile' or (path == '/' and is_mobile)) else APP_PATH
    try:
        with open(fpath, 'rb') as f:
            content = f.read()
        handler.send_response(200)
        handler.send_header('Content-Type', 'text/html; charset=utf-8')
        handler.send_header('Content-Length', str(len(content)))
        handler.end_headers()
        handler.wfile.write(content)
    except FileNotFoundError:
        handler.send_response(404)
        handler.end_headers()


def serve_manifest(handler, path, params):
    """# 20301703  GET /manifest.json"""
    manifest = {
        "name": "Server Hub",
        "short_name": "Hub",
        "description": "Home server control panel",
        "start_url": "/",
        "display": "standalone",
        "background_color": "#0d1117",
        "theme_color": "#58a6ff",
        "icons": [
            {
                "src": "data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'%3E%3Crect width='100' height='100' rx='18' fill='%230d1117'/%3E%3Ctext y='.9em' font-size='80' x='10'%3E%F0%9F%96%A5%3C/text%3E%3C/svg%3E",
                "sizes": "any",
                "type": "image/svg+xml",
                "purpose": "any maskable",
            }
        ],
    }
    content = json.dumps(manifest).encode()
    handler.send_response(200)
    handler.send_header('Content-Type', 'application/manifest+json')
    handler.send_header('Content-Length', str(len(content)))
    handler.end_headers()
    handler.wfile.write(content)


def serve_sw(handler, path, params):
    """# 20301704  GET /sw.js"""
    sw = b"self.addEventListener('fetch', () => {});"
    handler.send_response(200)
    handler.send_header('Content-Type', 'application/javascript')
    handler.send_header('Content-Length', str(len(sw)))
    handler.end_headers()
    handler.wfile.write(sw)


def get_my_ip(handler, path, params):
    """# 20301705  GET /api/my-ip"""
    # Return the connecting client's IP address (useful for fail2ban unban)
    client_ip = handler.client_address[0]
    # X-Forwarded-For from reverse proxy
    xff = handler.headers.get('X-Forwarded-For', '')
    if xff:
        client_ip = xff.split(',')[0].strip()
    handler.send_json({'ip': client_ip})


def get_identity(handler, path, params):
    """# 20301706  GET /api/identity"""
    # Identity beacon — used by peer mesh registration and discovery
    # get_server_info lives in server.py; lazy import avoids circular load at module time.
    # TODO: move get_server_info to kernel/ssh.py in a later phase.
    import server as _srv  # noqa: PLC0415
    si      = _srv.get_server_info()
    cfg     = _config_get_all()
    ts_ip   = si.get('tailscale_ip', '')
    # hub_url: prefer config override, else build from tailscale IP, else local IP
    hub_url = cfg.get('hub_url', '')
    if not hub_url:
        ip      = ts_ip if ts_ip and ts_ip != 'none' else si.get('local_ip', '')
        hub_url = f'http://{ip}:{PORT}' if ip else ''
    handler.send_json({
        'hostname':     si.get('hostname', ''),
        'name':         cfg.get('server_name', si.get('hostname', '')),
        'hub_url':      hub_url,
        'local_ip':     si.get('local_ip', ''),
        'tailscale_ip': ts_ip,
        'version':      '1.0',
    })


def get_access(handler, path, params):
    """# 20301707  GET /api/access"""
    # get_access_info lives in server.py; lazy import avoids circular load at module time.
    # TODO: move get_access_info to kernel/ in a later phase.
    import server as _srv  # noqa: PLC0415
    handler.send_json(_srv.get_access_info())
