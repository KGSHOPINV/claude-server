#!/usr/bin/env python3
"""
# 20200006  kernel.router — dispatch table for all hub routes
Hub kernel: request routing layer.
Auth is enforced here at dispatch time, not per-handler.
Gate levels: 0=public 1=user 2=admin 3=totp
"""

# Route entry shape:
# {
#   "code":    "20302701",        # telescope code
#   "method":  "GET",             # or "POST"
#   "path":    "/api/status",     # exact path, or prefix ending in *
#   "prefix":  False,             # True if path is a prefix match
#   "gate":    1,                 # minimum gate level required (0=public)
#   "handler": "handle_status",   # function name in handlers/ (phase 2)
#   "module":  "status",          # which handler file owns this
# }

ROUTES = [
    # ── Identity ─────────────────────────────────────────────────────────────
    {"code": "20301701", "method": "GET",  "path": "/",                           "prefix": False, "gate": 0, "handler": "serve_app",            "module": "identity"},
    {"code": "20301702", "method": "GET",  "path": "/mobile",                     "prefix": False, "gate": 0, "handler": "serve_app",             "module": "identity"},
    {"code": "20301708", "method": "GET",  "path": "/desktop",                    "prefix": False, "gate": 0, "handler": "serve_app",             "module": "identity"},
    {"code": "20301703", "method": "GET",  "path": "/manifest.json",              "prefix": False, "gate": 0, "handler": "serve_manifest",         "module": "identity"},
    {"code": "20301704", "method": "GET",  "path": "/sw.js",                      "prefix": False, "gate": 0, "handler": "serve_sw",               "module": "identity"},
    {"code": "20301705", "method": "GET",  "path": "/api/my-ip",                  "prefix": False, "gate": 0, "handler": "get_my_ip",              "module": "identity"},
    {"code": "20301706", "method": "GET",  "path": "/api/identity",               "prefix": False, "gate": 0, "handler": "get_identity",           "module": "identity"},
    {"code": "20301707", "method": "GET",  "path": "/api/access",                 "prefix": False, "gate": 1, "handler": "get_access",             "module": "identity"},

    # ── Status / Docker ───────────────────────────────────────────────────────
    {"code": "20302701", "method": "GET",  "path": "/api/status",                 "prefix": False, "gate": 1, "handler": "get_status",             "module": "status"},
    {"code": "20302702", "method": "GET",  "path": "/api/setup/status",           "prefix": False, "gate": 1, "handler": "get_setup_status",       "module": "status"},
    {"code": "20302703", "method": "GET",  "path": "/api/containers",             "prefix": False, "gate": 1, "handler": "get_containers",         "module": "status"},
    {"code": "20302704", "method": "GET",  "path": "/api/services",               "prefix": False, "gate": 1, "handler": "get_services",           "module": "status"},
    {"code": "20302705", "method": "GET",  "path": "/api/ports",                  "prefix": False, "gate": 1, "handler": "get_ports",              "module": "status"},
    {"code": "20302706", "method": "GET",  "path": "/api/storage",                "prefix": False, "gate": 1, "handler": "get_storage",            "module": "status"},
    {"code": "20302707", "method": "GET",  "path": "/api/docker/images",          "prefix": False, "gate": 1, "handler": "get_docker_images",      "module": "status"},
    {"code": "20302708", "method": "GET",  "path": "/api/docker/volumes",         "prefix": False, "gate": 1, "handler": "get_docker_volumes",     "module": "status"},
    {"code": "20302709", "method": "GET",  "path": "/api/docker/stats",           "prefix": False, "gate": 1, "handler": "get_docker_stats",       "module": "status"},
    {"code": "20302710", "method": "GET",  "path": "/api/docker/diagnostics",     "prefix": False, "gate": 1, "handler": "get_docker_diagnostics", "module": "status"},
    {"code": "20302711", "method": "GET",  "path": "/api/integrations",           "prefix": False, "gate": 1, "handler": "get_integrations",       "module": "status"},
    {"code": "20302712", "method": "GET",  "path": "/api/manifest",               "prefix": False, "gate": 1, "handler": "get_manifest",           "module": "status"},
    {"code": "20302713", "method": "GET",  "path": "/api/receipt",                "prefix": False, "gate": 2, "handler": "get_receipt",            "module": "status"},
    {"code": "20302714", "method": "GET",  "path": "/api/sync",                   "prefix": False, "gate": 1, "handler": "get_sync",               "module": "status"},
    {"code": "20302715", "method": "GET",  "path": "/api/context",                "prefix": False, "gate": 1, "handler": "get_context",            "module": "status"},
    {"code": "20302716", "method": "GET",  "path": "/api/sitemap",                "prefix": False, "gate": 0, "handler": "get_sitemap",            "module": "status"},
    {"code": "20302717", "method": "GET",  "path": "/cutsheet",                   "prefix": False, "gate": 0, "handler": "get_cutsheet",           "module": "status"},
    {"code": "20302718", "method": "POST", "path": "/api/refresh",                "prefix": False, "gate": 1, "handler": "post_refresh",           "module": "status"},
    {"code": "20302719", "method": "POST", "path": "/api/docker/prune",           "prefix": False, "gate": 2, "handler": "post_docker_prune",      "module": "status"},
    {"code": "20302720", "method": "POST", "path": "/api/docker/action/",         "prefix": True,  "gate": 2, "handler": "post_docker_action",     "module": "status"},
    {"code": "20302721", "method": "POST", "path": "/api/ports/ack",              "prefix": False, "gate": 1, "handler": "post_ports_ack",         "module": "status"},

    # ── Federation ───────────────────────────────────────────────────────────
    {"code": "20303701", "method": "GET",  "path": "/api/federation",             "prefix": False, "gate": 1, "handler": "get_federation",         "module": "federation"},
    {"code": "20303702", "method": "POST", "path": "/api/federation",             "prefix": False, "gate": 1, "handler": "post_federation",        "module": "federation"},
    {"code": "20303703", "method": "POST", "path": "/api/peer/register",          "prefix": False, "gate": 0, "handler": "post_peer_register",     "module": "federation"},

    # ── Config / Vault / Journal ──────────────────────────────────────────────
    {"code": "20304701", "method": "GET",  "path": "/api/vault",                  "prefix": False, "gate": 2, "handler": "get_vault",              "module": "config"},
    {"code": "20304702", "method": "GET",  "path": "/api/issues",                 "prefix": False, "gate": 1, "handler": "get_issues",             "module": "config"},
    {"code": "20304703", "method": "GET",  "path": "/api/journal",                "prefix": False, "gate": 1, "handler": "get_journal",            "module": "config"},
    {"code": "20304704", "method": "GET",  "path": "/api/config",                 "prefix": False, "gate": 1, "handler": "get_config",             "module": "config"},
    {"code": "20304705", "method": "POST", "path": "/api/vault",                  "prefix": False, "gate": 2, "handler": "post_vault",             "module": "config"},
    {"code": "20304706", "method": "POST", "path": "/api/config",                 "prefix": False, "gate": 2, "handler": "post_config",            "module": "config"},
    {"code": "20304707", "method": "POST", "path": "/api/journal",                "prefix": False, "gate": 1, "handler": "post_journal",           "module": "config"},

    # ── Users / Auth / TOTP ───────────────────────────────────────────────────
    {"code": "20305701", "method": "GET",  "path": "/api/auth/check",             "prefix": False, "gate": 0, "handler": "get_auth_check",         "module": "users"},
    {"code": "20305702", "method": "GET",  "path": "/api/users",                  "prefix": False, "gate": 2, "handler": "get_users",              "module": "users"},
    {"code": "20305703", "method": "GET",  "path": "/api/totp/status",            "prefix": False, "gate": 1, "handler": "get_totp_status",        "module": "users"},
    {"code": "20305704", "method": "GET",  "path": "/api/totp/setup",             "prefix": False, "gate": 2, "handler": "get_totp_setup",         "module": "users"},
    {"code": "20305705", "method": "POST", "path": "/api/auth/login",             "prefix": False, "gate": 0, "handler": "post_auth_login",        "module": "users"},
    {"code": "20305706", "method": "POST", "path": "/api/auth/logout",            "prefix": False, "gate": 0, "handler": "post_auth_logout",       "module": "users"},
    {"code": "20305707", "method": "POST", "path": "/api/users",                  "prefix": False, "gate": 2, "handler": "post_users",             "module": "users"},
    {"code": "20305708", "method": "POST", "path": "/api/totp/confirm",           "prefix": False, "gate": 2, "handler": "post_totp_confirm",      "module": "users"},
    {"code": "20305709", "method": "POST", "path": "/api/totp/verify",            "prefix": False, "gate": 0, "handler": "post_totp_verify",       "module": "users"},
    {"code": "20305710", "method": "POST", "path": "/api/totp/disable",           "prefix": False, "gate": 3, "handler": "post_totp_disable",      "module": "users"},

    # ── Events / Incidents / Activity ─────────────────────────────────────────
    {"code": "20306701", "method": "GET",  "path": "/api/incidents",              "prefix": False, "gate": 1, "handler": "get_incidents",          "module": "events"},
    {"code": "20306702", "method": "GET",  "path": "/api/activity",               "prefix": False, "gate": 1, "handler": "get_activity",           "module": "events"},
    {"code": "20306703", "method": "POST", "path": "/api/incidents",              "prefix": False, "gate": 1, "handler": "post_incidents",         "module": "events"},
    {"code": "20306704", "method": "POST", "path": "/api/activity",               "prefix": False, "gate": 1, "handler": "post_activity",          "module": "events"},

    # ── AI ────────────────────────────────────────────────────────────────────
    {"code": "20307701", "method": "GET",  "path": "/api/ai/config",              "prefix": False, "gate": 1, "handler": "get_ai_config",          "module": "ai"},
    {"code": "20307702", "method": "POST", "path": "/api/ai/chat",                "prefix": False, "gate": 1, "handler": "post_ai_chat",           "module": "ai"},
    {"code": "20307703", "method": "POST", "path": "/api/ai/config",              "prefix": False, "gate": 2, "handler": "post_ai_config",         "module": "ai"},

    # ── Tunnel ────────────────────────────────────────────────────────────────
    {"code": "20308701", "method": "POST", "path": "/api/tunnel/start",           "prefix": False, "gate": 2, "handler": "post_tunnel_start",      "module": "tunnel"},
    {"code": "20308702", "method": "POST", "path": "/api/tunnel/stop",            "prefix": False, "gate": 2, "handler": "post_tunnel_stop",       "module": "tunnel"},

    # ── Proxy / Docs / Files ──────────────────────────────────────────────────
    {"code": "20309701", "method": "GET",  "path": "/proxy/",                     "prefix": True,  "gate": 1, "handler": "get_proxy",              "module": "proxy"},
    {"code": "20309702", "method": "GET",  "path": "/api/docs",                   "prefix": False, "gate": 1, "handler": "get_docs",               "module": "proxy"},
    {"code": "20309703", "method": "GET",  "path": "/api/docs/content",           "prefix": False, "gate": 1, "handler": "get_docs_content",       "module": "proxy"},
    {"code": "20309704", "method": "GET",  "path": "/api/files",                  "prefix": False, "gate": 1, "handler": "get_files",              "module": "proxy"},

    # ── Ops ───────────────────────────────────────────────────────────────────
    {"code": "20310701", "method": "POST", "path": "/api/run",                    "prefix": False, "gate": 3, "handler": "post_run",               "module": "ops"},
    {"code": "20310702", "method": "POST", "path": "/api/update",                 "prefix": False, "gate": 3, "handler": "post_update",            "module": "ops"},
    {"code": "20310703", "method": "POST", "path": "/api/setup/generate-claude-md", "prefix": False, "gate": 3, "handler": "post_setup_generate_claude_md", "module": "ops"},
    {"code": "20310704", "method": "POST", "path": "/api/service/install",        "prefix": False, "gate": 2, "handler": "post_service_install",   "module": "ops"},
]


def dispatch(method: str, path: str) -> dict | None:
    """Find the matching route entry for a method + path.

    Returns the route dict or None if no match.
    Prefix routes match if path.startswith(route['path']).
    Exact routes require path == route['path'].
    """
    for route in ROUTES:
        if route["method"] != method:
            continue
        if route["prefix"]:
            if path.startswith(route["path"]):
                return route
        else:
            if path == route["path"]:
                return route
    return None


def routes_by_module() -> dict:
    """Return ROUTES grouped by module name. Useful for /api/registry."""
    result = {}
    for r in ROUTES:
        result.setdefault(r["module"], []).append(r)
    return result


# ── Dispatch ──────────────────────────────────────────────────────────────────
# 20200007  kernel.router.dispatch — resolve a request to a handler and call it.
#
# Handler contract:
#   GET   fn(handler, path, params)
#   POST  fn(handler, path, params, body)
# Handlers write the response themselves via handler.send_json / handler.wfile.

import importlib
import os
import threading

# Gate enforcement is OFF by default. The route table declares the target
# posture (52 of 65 routes gated) but the current UI only sends a token on a
# handful of calls, so enforcing here would lock out the app. Shadow mode
# records what WOULD have been denied; flip HUB_ENFORCE_GATES=1 once the UI
# sends X-Hub-Token / X-Gate-Token on every gated call.
ENFORCE_GATES = os.environ.get('HUB_ENFORCE_GATES', '0').lower() not in ('0', 'false', '')

_SHADOW_MAX = 500
_shadow_denials = []
_shadow_lock = threading.Lock()

_handler_cache = {}
_cache_lock = threading.Lock()

_EXACT = {}
_PREFIX = []


def _build_index():
    """Split ROUTES into an exact-match dict and a longest-first prefix list."""
    _EXACT.clear()
    del _PREFIX[:]
    for r in ROUTES:
        if r.get('prefix'):
            _PREFIX.append(r)
        else:
            _EXACT[(r['method'], r['path'])] = r
    _PREFIX.sort(key=lambda r: len(r['path']), reverse=True)


_build_index()


def resolve(method, path):
    """Return the route entry for method+path, or None."""
    r = _EXACT.get((method, path))
    if r is not None:
        return r
    for r in _PREFIX:
        if path.startswith(r['path']):
            return r
    return None


def _load(module):
    """Import handlers.<module> once and cache it."""
    with _cache_lock:
        mod = _handler_cache.get(module)
        if mod is None:
            mod = importlib.import_module('handlers.' + module)
            _handler_cache[module] = mod
        return mod


def _gate_allows(handler, route, db_conn_fn):
    """Evaluate the route's declared gate. Returns (allowed, reason)."""
    level = route.get('gate', 0)
    if level <= 0:
        return True, ''
    from kernel.auth import check_auth, gate_check
    if level >= 1 and check_auth(handler) is None:
        return False, 'no_session'
    if level >= 2 and not gate_check(handler.headers, level, db_conn_fn):
        return False, 'gate_required'
    return True, ''


def shadow_report():
    """What gate enforcement would have blocked. Diagnostic for the flip."""
    with _shadow_lock:
        return list(_shadow_denials)


def dispatch(handler, method, path, params=None, body=None, db_conn_fn=None):
    """Route one request. Returns True if handled, False to fall through."""
    route = resolve(method, path)
    if route is None:
        return False
    try:
        fn = getattr(_load(route['module']), route['handler'], None)
    except Exception as e:
        handler.send_json({'ok': False, 'error': 'handler_import_failed',
                           'module': route['module'], 'detail': str(e)}, 500)
        return True
    if fn is None:
        return False

    allowed, reason = _gate_allows(handler, route, db_conn_fn)
    if not allowed:
        if ENFORCE_GATES:
            handler.send_json({'error': reason, 'layer': route.get('gate', 0),
                               'code': route['code']}, 403)
            return True
        with _shadow_lock:
            if len(_shadow_denials) < _SHADOW_MAX:
                _shadow_denials.append({'code': route['code'], 'method': method,
                                        'path': path, 'reason': reason})

    if params is None:
        params = {}
    if method == 'POST':
        fn(handler, path, params, body or {})
    else:
        fn(handler, path, params)
    return True
