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
SPLASH_PATH = os.path.join(_BASE_DIR, 'splash.html')

# Hostnames that get the PUBLIC splash instead of the app. The zone apex is
# public by definition, so it must never serve the hub: a page that lists
# servers and projects to anyone who types the domain is a map for someone
# else.
#
# Placeholder until FlareVault serves its own. Set HUB_SPLASH_HOSTS to change
# it without touching code.
SPLASH_HOSTS = [h.strip().lower() for h in os.environ.get(
    'HUB_SPLASH_HOSTS', 'flarevault.dev,www.flarevault.dev').split(',') if h.strip()]

# Hostnames that get the LOBBY instead of the app. dashboard.<zone> is a
# different page from app.html: one card per server, and picking one routes you
# into that server. It is chosen on HOST for the same reason the splash is --
# so that lobby.html is unreachable by path on a node hostname, which is
# service-token-only and must never carry a human-shaped page.
#
# Set HUB_DASHBOARD_HOSTS to change it without touching code.
DASHBOARD_HOSTS = [h.strip().lower() for h in os.environ.get(
    'HUB_DASHBOARD_HOSTS', 'flarevault.dev,www.flarevault.dev').split(',') if h.strip()]

# ONE DOMAIN, PAGES BEHIND ONE LOGIN -- not a subdomain per screen.
#
# This was dashboard.flarevault.dev. That name belongs to FlareVault, and a
# hostname per screen means a Cloudflare app, a DNS record and an ingress rule
# every time a page is added. The apex is the public login space; FlareSHub is
# a PATH behind it.
FLARESHUB_PATHS = ('/fleet', '/flareshub')
UI_DIR      = os.path.join(_BASE_DIR, 'ui')

# Only these extensions are ever served from ui/. No wildcard static hosting.
_UI_TYPES = {
    '.js':   'application/javascript; charset=utf-8',
    '.mjs':  'application/javascript; charset=utf-8',
    '.css':  'text/css; charset=utf-8',
    '.json': 'application/json; charset=utf-8',
}


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


# 20204314  _machine_id — stable node key for peer identity
def _machine_id():
    try:
        with open('/etc/machine-id', encoding='utf-8') as f:
            return f.read().strip()
    except Exception:
        return ''

def serve_app(handler, path, params):
    """# 20301701  GET / /mobile /desktop — serve app.html or mobile.html"""
    # The apex is public. Decide on HOST before anything else -- a request that
    # arrived at flarevault.dev must never fall through to the app, whatever
    # its path or user-agent.
    host = (handler.headers.get('Host', '') or '').split(':')[0].lower()
    if host in SPLASH_HOSTS and path in ('/', '/mobile', '/desktop'):
        try:
            with open(SPLASH_PATH, 'rb') as f:
                body = f.read()
            handler.send_response(200)
            handler.send_header('Content-Type', 'text/html; charset=utf-8')
            handler.send_header('Content-Length', str(len(body)))
            # Public page, no session, nothing personal -- but say so, so a
            # proxy never caches it as if it were an authenticated response.
            handler.send_header('Cache-Control', 'public, max-age=300')
            handler.end_headers()
            handler.wfile.write(body)
        except FileNotFoundError:
            handler.send_response(404)
            handler.end_headers()
        return

    # Same decision, one host further in: dashboard.<zone> is the lobby, not
    # the app. A request that arrived there must never fall through to
    # app.html -- the app is one server's control room, and serving it here is
    # exactly the mistake the lobby exists to undo.
    #
    # Lazy import, and the reason is blast radius: this module answers '/' for
    # every hostname this origin has. A lobbyhost that is missing or broken
    # then takes the app down everywhere rather than on the dashboard host
    # alone. Imported here, the failure stays where the feature is.
    # The apex: '/' is the PUBLIC login space and must stay public, so it is
    # handled by the splash block above. FlareSHub sits behind it on a path,
    # and Cloudflare Access is scoped to that path rather than the hostname --
    # which is what lets one domain hold a public door and a private room.
    if host in DASHBOARD_HOSTS and path.split('?')[0] in FLARESHUB_PATHS:
        from handlers.lobbyhost import serve_lobby  # noqa: PLC0415
        serve_lobby(handler, path, params)
        return

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
    """# 20301704  GET /sw.js — served from ui/sw.js, at ROOT scope

    The file lives in ui/ but is served from / because a service worker can
    only control the paths at or below the URL it was served from. At /ui/sw.js
    it would control ui/ and nothing else, which is useless for both the install
    prompt and notifications.

    The previous body was one line -- an empty fetch listener -- and app.html
    never registered it. That is why "Install app" never appeared and why no
    notification could be shown: showNotification() requires a registration.

    The inline fallback keeps a hub with a missing ui/ serving something valid
    rather than a 500, because a broken service worker can wedge a PWA.
    """
    try:
        with open(os.path.join(UI_DIR, 'sw.js'), 'rb') as f:
            sw = f.read()
    except Exception:
        sw = b"self.addEventListener('fetch', () => {});"
    handler.send_response(200)
    handler.send_header('Content-Type', 'application/javascript')
    handler.send_header('Content-Length', str(len(sw)))
    handler.end_headers()
    handler.wfile.write(sw)


def serve_ui_asset(handler, path, params):
    """# 20301709  GET /ui/* — serve UI modules from hub/ui/

    Phase 3 splits app.html into modules. Those files have to be reachable, and
    the hub previously served exactly three: app.html, manifest.json, sw.js.

    This is deliberately NOT general static hosting: the resolved path must stay
    inside ui/, and the extension must be in the allowlist. Anything else 404s.
    """
    rel = path[len('/ui/'):].split('?')[0]
    root = os.path.abspath(UI_DIR)
    full = os.path.abspath(os.path.join(root, rel))

    # Path traversal guard: the resolved path must live under ui/
    if full != root and not full.startswith(root + os.sep):
        handler.send_response(404)
        handler.end_headers()
        return

    ctype = _UI_TYPES.get(os.path.splitext(full)[1].lower())
    if ctype is None or not os.path.isfile(full):
        handler.send_response(404)
        handler.end_headers()
        return

    try:
        with open(full, 'rb') as f:
            content = f.read()
    except OSError:
        handler.send_response(404)
        handler.end_headers()
        return

    handler.send_response(200)
    handler.send_header('Content-Type', ctype)
    handler.send_header('Content-Length', str(len(content)))
    handler.send_header('Cache-Control', 'no-cache')
    handler.end_headers()
    handler.wfile.write(content)


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
    from kernel import collect as _srv  # noqa: PLC0415
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
        # Stable node key. Peers keyed by machine_id survive an address change;
        # peers keyed by URL simply die when the address moves.
        'machine_id':   _machine_id(),
    })


def get_auth_provider(handler, path, params):
    """# 20301710  GET /api/auth/provider

    Who issued the token this node trusts. Starts "self"; flips to
    "flarevault" when the vault provisions server.identity.json. FlareVault
    reads this to know whether a node has been adopted yet. One field, no
    refactor on either side.
    """
    from kernel import identity as _id  # noqa: PLC0415
    handler.send_json({
        'provider':   _id.jwt_issuer(),        # self | flarevault
        'algorithm':  'HS256',                 # stdlib-only; RS256 is not available
        'server_id':  _id.server_id(),
        'machine_id': _id.machine_id(),
        'name':       _id.node_name(),
        'mode':       _id.mode(),              # node | central
        'roles':      list(_id.ROLES),
        'identity_file_present': __import__('os').path.exists(_id.IDENTITY_FILE),
    })


def get_access(handler, path, params):
    """# 20301707  GET /api/access"""
    # get_access_info lives in server.py; lazy import avoids circular load at module time.
    # TODO: move get_access_info to kernel/ in a later phase.
    from kernel import collect as _srv  # noqa: PLC0415
    handler.send_json(_srv.get_access_info())
