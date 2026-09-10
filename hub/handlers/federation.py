#!/usr/bin/env python3
"""
# 20204003  handlers.federation -- peer mesh, federation endpoints
Hub handler module: federation layer (module 03).
Imports only from kernel/. No direct DB access except via kernel.db.
"""
import json
import os
import urllib.request
from datetime import datetime

from kernel.db   import db_conn
from kernel.auth import check_auth, gate_check
from kernel.log  import log_activity
from kernel.ssh  import ssh_run, SSH_HOST, SSH_USER, SERVER_IP

_PORT = int(os.environ.get('HUB_PORT', 8765))

# ── Private config helpers (pending move to kernel/config.py) ─────────────────

def _config_get_all():
    """SELECT all hub_config rows as a dict."""
    try:
        conn = db_conn()
        rows = conn.execute("SELECT key,value FROM hub_config").fetchall()
        conn.close()
        return {r['key']: r['value'] for r in rows}
    except Exception:
        return {}


def _config_set(key, value):
    """UPSERT a single hub_config row."""
    try:
        conn = db_conn()
        ts = datetime.now().isoformat()
        conn.execute(
            "INSERT INTO hub_config(key,value,updated) VALUES(?,?,?) "
            "ON CONFLICT(key) DO UPDATE SET value=?,updated=?",
            (key, value, ts, value, ts))
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        return str(e)


_server_info_cache = None  # module-level cache


def _get_server_info():
    """Fetch server identity once and cache for the lifetime of the process."""
    global _server_info_cache
    if _server_info_cache is not None:
        return _server_info_cache
    r = ssh_run(
        'printf "%s\t%s\t%s\t%s\t%s\t%s"'
        ' "$(hostname)"'
        ' "$(lsb_release -ds 2>/dev/null | tr -d \'"\' || uname -r)"'
        ' "$(ip route get 1 2>/dev/null | awk \'{print $7}\' | head -1)"'
        ' "$(tailscale ip -4 2>/dev/null || echo none)"'
        ' "$(nproc)"'
        ' "$(echo $HOME)"'
    )
    if r.get('online') and r.get('output'):
        parts = r['output'].split('\t')
        _server_info_cache = {
            'hostname':     parts[0].strip() if len(parts) > 0 else '',
            'os':           parts[1].strip() if len(parts) > 1 else '',
            'local_ip':     parts[2].strip() if len(parts) > 2 else '',
            'tailscale_ip': parts[3].strip() if len(parts) > 3 else 'none',
            'cpu_cores':    int(parts[4].strip()) if len(parts) > 4 and parts[4].strip().isdigit() else 0,
            'home_dir':     parts[5].strip() if len(parts) > 5 and parts[5].strip() else os.path.expanduser('~'),
            'ssh_user':     SSH_USER or (SSH_HOST.split('@')[0] if '@' in SSH_HOST else ''),
        }
    else:
        _server_info_cache = {
            'hostname': '', 'os': '', 'local_ip': '',
            'tailscale_ip': 'none', 'cpu_cores': 0,
            'home_dir': os.path.expanduser('~'),
            'ssh_user': SSH_USER,
        }
    return _server_info_cache


# ── Route handlers ─────────────────────────────────────────────────────────────
# One function per route. Each takes (handler, path, params).

def get_federation(handler, path, params):
    """# 20303701  GET /api/federation"""
    cfg = _config_get_all()
    # peers stored as JSON string in hub_config
    peers_raw = cfg.get('peers', '[]')
    try:
        peers = json.loads(peers_raw) if peers_raw else []
    except Exception:
        peers = []
    handler.send_json({
        'fv_url':          cfg.get('fv_url', ''),
        'mf_url':          cfg.get('mf_url', ''),
        'peers':           peers,
        'fv_last_contact': cfg.get('fv_last_contact') or None,
        'mf_last_contact': cfg.get('mf_last_contact') or None,
    })


def post_federation(handler, path, params, body):
    """# 20303702  POST /api/federation"""
    # Accept: fv_url, mf_url, peers (JSON string), fv_last_contact, mf_last_contact
    # No gate required — URLs are not secrets; peers list is operational data.
    allowed = {'fv_url', 'mf_url', 'peers', 'fv_last_contact', 'mf_last_contact'}
    saved = 0
    for k, v in body.items():
        if k in allowed:
            _config_set(k, str(v) if v is not None else '')
            saved += 1
    handler.send_json({'ok': True, 'saved': saved})


def post_peer_register(handler, path, params, body):
    """# 20303703  POST /api/peer/register"""
    # Bidirectional peer mesh registration.
    # POST {"hub_url": "http://ip:8765", "echo": true/false}
    # - Adds hub_url to this hub's peers list
    # - If echo=true, also POSTs back to register this hub on the peer
    peer_url = body.get('hub_url', '').rstrip('/')
    if not peer_url:
        handler.send_json({'ok': False, 'error': 'hub_url required'}, 400)
        return
    # Load and update peers list
    cfg = _config_get_all()
    peers_raw = cfg.get('peers', '[]')
    try:
        peers = json.loads(peers_raw) if peers_raw else []
    except Exception:
        peers = []
    if peer_url not in peers:
        peers.append(peer_url)
        _config_set('peers', json.dumps(peers))
        log_activity(db_conn, f'Peer registered: {peer_url}', 'system', 'federation', '', 'info')
    # Echo back — register ourselves on the peer (one level deep, no infinite loop)
    echo = body.get('echo', True)
    if echo:
        si = _get_server_info()
        cfg2 = _config_get_all()
        ts_ip = si.get('tailscale_ip', '')
        my_hub_url = cfg2.get('hub_url', '')
        if not my_hub_url:
            ip = ts_ip if ts_ip and ts_ip != 'none' else si.get('local_ip', '')
            my_hub_url = f'http://{ip}:{_PORT}' if ip else ''
        if my_hub_url:
            try:
                echo_body = json.dumps({'hub_url': my_hub_url, 'echo': False}).encode()
                req = urllib.request.Request(
                    f'{peer_url}/api/peer/register',
                    data=echo_body,
                    headers={'Content-Type': 'application/json'},
                    method='POST'
                )
                urllib.request.urlopen(req, timeout=5)
            except Exception as e:
                pass  # Best-effort; peer may be offline at registration time
    handler.send_json({'ok': True, 'peers': peers})
