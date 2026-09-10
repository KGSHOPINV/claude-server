#!/usr/bin/env python3
"""
# 20204002  handlers.status -- Docker status, system info, receipt, sync endpoints
Hub handler module: status layer (module 02).
Imports only from kernel/. No direct DB access except via kernel.db.
"""
import json
import os
import subprocess
from datetime import datetime

from kernel.db   import db_conn
from kernel.ssh  import ssh_run
from kernel.auth import check_auth, gate_check
from kernel.log  import log_activity

# ── Module-level constants (re-derived locally to match server.py) ─────────────
PORT = int(os.environ.get('HUB_PORT', 8765))

# One function per route. Each takes (handler, path, params) for GET,
# (handler, path, params, body) for POST.
# Complex helpers still in server.py are lazy-imported via `import server as _srv`.
# TODO: move those helpers to kernel/ or a dedicated service module in Phase 3+.


# ── GET handlers ──────────────────────────────────────────────────────────────

def get_status(handler, path, params):
    """# 20302701  GET /api/status -- aggregated server info (60s cache)"""
    import server as _srv  # noqa: PLC0415
    force = 'force' in handler.path
    handler.send_json(_srv.get_status(force=force))


def get_setup_status(handler, path, params):
    """# 20302702  GET /api/setup/status -- setup step completion status"""
    import server as _srv  # noqa: PLC0415
    handler.send_json(_srv.get_setup_status())


def get_containers(handler, path, params):
    """# 20302703  GET /api/containers -- Docker container list (30s cache)"""
    import server as _srv  # noqa: PLC0415
    force = 'force' in handler.path
    handler.send_json(_srv.get_containers(force=force))


def get_services(handler, path, params):
    """# 20302704  GET /api/services -- known services enriched with live Docker state"""
    import server as _srv  # noqa: PLC0415
    handler.send_json(_srv.build_services())


def get_ports(handler, path, params):
    """# 20302705  GET /api/ports -- active port map + lane classification + events"""
    import server as _srv  # noqa: PLC0415
    force = 'force' in handler.path
    if force:
        try:
            _srv._do_port_snapshot()
        except Exception:
            pass
    with _srv._port_cache_lock:
        ports  = list(_srv._port_cache['ports'])
        events = list(_srv._port_cache['events'])
        ts     = _srv._port_cache['ts']
    # If cache is empty (first startup before thread runs), do a quick scan now
    if not ports:
        try:
            ports, _ = _srv.scan_ports()
            ts = datetime.now().isoformat()
        except Exception:
            pass
    # Enrich with federation schema fields (FV-BI-SH contract)
    fed_ports = []
    for p in ports:
        fed_ports.append({
            **p,
            'protocol':    'tcp',
            'state':       'LISTEN',
            'assigned_by': 'sh',
        })
    handler.send_json({
        'ports':      fed_ports,
        'events':     events,
        'lanes':      _srv.PORT_LANES,
        'scanned_at': ts,
    })


def get_storage(handler, path, params):
    """# 20302706  GET /api/storage -- disk/storage info (df + lsblk + docker df)"""
    import server as _srv  # noqa: PLC0415
    handler.send_json(_srv.api_storage_info())


def get_docker_images(handler, path, params):
    """# 20302707  GET /api/docker/images -- Docker image list"""
    import server as _srv  # noqa: PLC0415
    handler.send_json(_srv.api_docker_images())


def get_docker_volumes(handler, path, params):
    """# 20302708  GET /api/docker/volumes -- Docker volumes with sizes"""
    import server as _srv  # noqa: PLC0415
    handler.send_json(_srv.api_docker_volumes())


def get_docker_stats(handler, path, params):
    """# 20302709  GET /api/docker/stats -- per-container CPU/RAM snapshot"""
    import server as _srv  # noqa: PLC0415
    handler.send_json(_srv.api_docker_stats())


def get_docker_diagnostics(handler, path, params):
    """# 20302710  GET /api/docker/diagnostics -- interpreted diagnostic findings"""
    import server as _srv  # noqa: PLC0415
    handler.send_json(_srv.api_docker_diagnostics())


def get_integrations(handler, path, params):
    """# 20302711  GET /api/integrations -- live health: Redis, SurrealDB, n8n"""
    import server as _srv  # noqa: PLC0415
    handler.send_json(_srv.get_integrations())


def get_manifest(handler, path, params):
    """# 20302712  GET /api/manifest -- service manifest BOM (downloadable JSON)"""
    import server as _srv  # noqa: PLC0415
    data = _srv.get_manifest()
    body = json.dumps(data, default=str, indent=2).encode()
    handler.send_response(200)
    handler.send_header('Content-Type', 'application/json')
    handler.send_header('Content-Length', str(len(body)))
    handler.send_header('Access-Control-Allow-Origin', '*')
    if 'download' in handler.path:
        fname = f'server-manifest-{datetime.now().strftime("%Y%m%d-%H%M")}.json'
        handler.send_header('Content-Disposition', f'attachment; filename="{fname}"')
    handler.end_headers()
    handler.wfile.write(body)


def get_receipt(handler, path, params):
    """# 20302713  GET /api/receipt -- full server snapshot / hardware overview"""
    import server as _srv  # noqa: PLC0415
    handler.send_json(_srv.build_receipt())


def get_sync(handler, path, params):
    """# 20302714  GET /api/sync -- quick sync check: expected vs running containers"""
    import server as _srv  # noqa: PLC0415
    receipt = _srv.build_receipt()
    handler.send_json({
        'ok': True,
        'container_count': receipt['container_count'],
        'sync_issues': receipt['sync_issues'],
        'generated': receipt['generated'],
    })


def get_context(handler, path, params):
    """# 20302715  GET /api/context -- hub context payload (HANDOFF_SERVERHUB spec)"""
    import server as _srv  # noqa: PLC0415
    handler.send_json(_srv.build_context())


def get_sitemap(handler, path, params):
    """# 20302716  GET /api/sitemap -- full route registry"""
    routes = {
        'GET': [
            {'path': '/', 'description': 'Hub dashboard (HTML)'},
            {'path': '/api/status', 'description': 'Server status'},
            {'path': '/api/containers', 'description': 'Docker container list'},
            {'path': '/api/services', 'description': 'Known services with running state'},
            {'path': '/api/ports', 'description': 'Live port scan + lane classification'},
            {'path': '/api/storage', 'description': 'Disk usage per mount'},
            {'path': '/api/docker/images', 'description': 'Docker image list'},
            {'path': '/api/docker/volumes', 'description': 'Docker volume list'},
            {'path': '/api/docker/stats', 'description': 'Container CPU/RAM stats'},
            {'path': '/api/docker/diagnostics', 'description': 'Container health diagnostics'},
            {'path': '/api/identity', 'description': 'Peer mesh identity beacon'},
            {'path': '/api/federation', 'description': 'Registered peer hubs'},
            {'path': '/api/config', 'description': 'Hub config key/value store'},
            {'path': '/api/integrations', 'description': 'External integrations'},
            {'path': '/api/vault', 'description': 'Encrypted credential vault'},
            {'path': '/api/issues', 'description': 'Tracked issue list'},
            {'path': '/api/docs', 'description': 'Guide/doc list'},
            {'path': '/api/docs/content', 'description': 'Guide content by filename'},
            {'path': '/api/journal', 'description': 'Activity journal entries'},
            {'path': '/api/receipt', 'description': 'Server receipt / hardware overview'},
            {'path': '/api/manifest', 'description': 'Service manifest (BOM)'},
            {'path': '/api/my-ip', 'description': 'Client IP detection'},
            {'path': '/api/auth/check', 'description': 'Session auth check'},
            {'path': '/api/users', 'description': 'User list'},
            {'path': '/api/access', 'description': 'Access/permission config'},
            {'path': '/api/ai/config', 'description': 'AI/LLM configuration'},
            {'path': '/api/totp/status', 'description': 'TOTP gate status'},
            {'path': '/api/totp/setup', 'description': 'TOTP setup (QR + secret)'},
            {'path': '/api/context', 'description': 'Claude context export'},
            {'path': '/api/sync', 'description': 'Sync status'},
            {'path': '/api/files', 'description': 'File browser'},
            {'path': '/cutsheet', 'description': 'Port cut-sheet (HTML)'},
            {'path': '/api/sitemap', 'description': 'This endpoint -- route registry'},
            {'path': '/proxy/{port}/{path}', 'description': 'Reverse proxy to local service'},
        ],
        'POST': [
            {'path': '/api/run', 'description': 'Run shell command (gate level 3)'},
            {'path': '/api/vault', 'description': 'Save encrypted vault blob'},
            {'path': '/api/refresh', 'description': 'Force status cache refresh'},
            {'path': '/api/auth/login', 'description': 'Authenticate (returns session token)'},
            {'path': '/api/auth/logout', 'description': 'Invalidate session'},
            {'path': '/api/config', 'description': 'Set hub config value'},
            {'path': '/api/federation', 'description': 'Add federation peer URL'},
            {'path': '/api/peer/register', 'description': 'Bidirectional peer mesh registration'},
            {'path': '/api/journal', 'description': 'Append journal entry'},
            {'path': '/api/ai/chat', 'description': 'AI chat message'},
            {'path': '/api/ai/config', 'description': 'Set AI config (key/model)'},
            {'path': '/api/totp/confirm', 'description': 'Confirm TOTP setup'},
            {'path': '/api/totp/verify', 'description': 'Verify TOTP code (elevate gate)'},
            {'path': '/api/totp/disable', 'description': 'Disable TOTP'},
            {'path': '/api/service/install', 'description': 'Deploy a new service'},
            {'path': '/api/tunnel/start', 'description': 'Start Cloudflare tunnel'},
            {'path': '/api/tunnel/stop', 'description': 'Stop Cloudflare tunnel'},
            {'path': '/api/ports/ack', 'description': 'Acknowledge port alert'},
            {'path': '/api/update', 'description': 'git pull + hub restart'},
            {'path': '/api/users', 'description': 'Create user'},
            {'path': '/api/docker/prune', 'description': 'Docker system prune'},
            {'path': '/api/activity', 'description': 'Log activity event'},
            {'path': '/api/setup/generate-claude-md', 'description': 'Generate CLAUDE.md'},
        ],
    }
    handler.send_json({
        'hub_version': '1.0',
        'port': PORT,
        'routes': routes,
        'total_get': len(routes['GET']),
        'total_post': len(routes['POST']),
    })


def get_cutsheet(handler, path, params):
    """# 20302717  GET /cutsheet -- self-contained port cut-sheet HTML (no auth)"""
    import server as _srv  # noqa: PLC0415
    with _srv._port_cache_lock:
        ports = list(_srv._port_cache['ports'])
        ts    = _srv._port_cache['ts']
    if not ports:
        try:
            ports, _ = _srv.scan_ports()
        except Exception:
            ports = []
    try:
        si   = _srv.get_server_info()
        svcs = _srv.build_services(si)
    except Exception:
        svcs = []
        si   = _srv.get_server_info()
    html = _srv.build_cutsheet_html(ports, svcs, si)
    enc  = html.encode('utf-8')
    handler.send_response(200)
    handler.send_header('Content-Type', 'text/html; charset=utf-8')
    handler.send_header('Content-Length', str(len(enc)))
    handler.send_header('Cache-Control', 'no-cache')
    handler.end_headers()
    handler.wfile.write(enc)


# ── POST handlers ─────────────────────────────────────────────────────────────

def post_refresh(handler, path, params, body):
    """# 20302718  POST /api/refresh -- force status + container cache refresh"""
    import server as _srv  # noqa: PLC0415
    _srv.get_status(force=True)
    _srv.get_containers(force=True)
    handler.send_json({'ok': True})


def post_docker_prune(handler, path, params, body):
    """# 20302719  POST /api/docker/prune -- prune Docker images/volumes/system"""
    kind = body.get('type', 'images')
    try:
        if kind == 'images':
            out = subprocess.check_output(['docker', 'image', 'prune', '-af'], text=True, stderr=subprocess.STDOUT)
        elif kind == 'volumes':
            out = subprocess.check_output(['docker', 'volume', 'prune', '-f'], text=True, stderr=subprocess.STDOUT)
        elif kind == 'system':
            out = subprocess.check_output(['docker', 'system', 'prune', '-af', '--volumes'], text=True, stderr=subprocess.STDOUT)
        else:
            out = 'unknown prune type'
        handler.send_json({'ok': True, 'output': out})
    except subprocess.CalledProcessError as e:
        handler.send_json({'ok': False, 'output': e.output})


def post_docker_action(handler, path, params, body):
    """# 20302720  POST /api/docker/action/{cname} -- start/stop/restart container"""
    cname  = path.split('/')[-1]
    action = body.get('action', '')
    if action not in ('start', 'stop', 'restart'):
        handler.send_json({'ok': False, 'error': 'invalid action'})
    else:
        try:
            subprocess.check_output(['docker', action, cname], stderr=subprocess.STDOUT)
            handler.send_json({'ok': True, 'container': cname, 'action': action})
        except subprocess.CalledProcessError as e:
            handler.send_json({'ok': False, 'error': e.output})


def post_ports_ack(handler, path, params, body):
    """# 20302721  POST /api/ports/ack -- acknowledge port alert events"""
    import server as _srv  # noqa: PLC0415
    event_ids = body.get('ids', [])
    ack_all   = body.get('all', False)
    conn = db_conn()
    if ack_all:
        conn.execute("UPDATE port_events SET acknowledged=1")
    elif event_ids:
        placeholders = ','.join('?' * len(event_ids))
        conn.execute(f"UPDATE port_events SET acknowledged=1 WHERE id IN ({placeholders})", event_ids)
    conn.commit()
    conn.close()
    # Refresh events cache
    conn = db_conn()
    rows = conn.execute(
        "SELECT * FROM port_events WHERE acknowledged=0 ORDER BY id DESC LIMIT 50"
    ).fetchall()
    conn.close()
    with _srv._port_cache_lock:
        _srv._port_cache['events'] = [dict(r) for r in rows]
    handler.send_json({'ok': True})
