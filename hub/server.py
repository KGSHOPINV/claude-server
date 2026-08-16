#!/usr/bin/env python3
"""
Hub local API server.
Run: python hub/server.py
Then open: http://localhost:8765
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
import urllib.request
from datetime import datetime

PORT      = int(os.environ.get('HUB_PORT', 8765))
BASE_DIR  = os.path.dirname(os.path.abspath(__file__))
DB_PATH   = os.environ.get('HUB_DB',     os.path.join(BASE_DIR, '..', 'db', 'server.db'))
APP_PATH    = os.path.join(BASE_DIR, 'app.html')
MOBILE_PATH = os.path.join(BASE_DIR, 'mobile.html')
GUIDES_DIR= os.environ.get('HUB_GUIDES', os.path.join(BASE_DIR, '..', 'guides'))

# LOCAL_MODE=1 → run commands directly (no SSH); used when hub runs ON the server
LOCAL_MODE = os.environ.get('HUB_LOCAL', '0') == '1'

HTTPS_PORTS = {9443, 9090}

_ssl_ctx = ssl.create_default_context()
_ssl_ctx.check_hostname = False
_ssl_ctx.verify_mode = ssl.CERT_NONE
SSH_HOST   = os.environ.get('HUB_SSH_HOST', 'localhost')
SSH_USER   = os.environ.get('HUB_SSH_USER', '')   # optional; overrides user parsed from SSH_HOST
SERVER_IP  = os.environ.get('HUB_SERVER_IP', '')  # leave blank — hub reads actual IP from server

# ── Proxy cache ───────────────────────────────────────────────────────────────
# HTML pages: 5s TTL (they change). JS/CSS/images: 60s TTL (static assets).

_proxy_cache = {}
_pcache_lock = threading.Lock()

def _pcache_get(key):
    with _pcache_lock:
        hit = _proxy_cache.get(key)
    if not hit:
        return None
    content, ct, status, ts = hit
    ttl = 5 if 'text/html' in ct else 60
    return (content, ct, status) if time.time() - ts < ttl else None

def _pcache_put(key, content, ct, status):
    with _pcache_lock:
        if len(_proxy_cache) > 400:
            oldest = min(_proxy_cache, key=lambda k: _proxy_cache[k][3])
            del _proxy_cache[oldest]
        _proxy_cache[key] = (content, ct, status, time.time())

def _rewrite_proxy_html(html, port):
    """Rewrite absolute src/href/action attrs through proxy, then inject <base>."""
    # Rewrite first so the injected <base> tag itself doesn't get double-processed
    def _sub(m):
        attr, q, path = m.group(1), m.group(2), m.group(3)
        skip = ('http://', 'https://', '//', '#', 'data:', 'javascript:', 'mailto:')
        return m.group(0) if any(path.startswith(s) for s in skip) else f'{attr}={q}/proxy/{port}{path}'
    html = re.sub(r'((?:src|href|action|data-src))=(["\'])(/[^"\']*)', _sub, html)
    # Now inject <base> so any remaining relative URLs (in JS etc.) also resolve through proxy
    base_tag = f'<base href="/proxy/{port}/">'
    if '<head>' in html:
        html = html.replace('<head>', f'<head>\n  {base_tag}', 1)
    elif '<head ' in html.lower():
        idx = html.lower().index('<head')
        end = html.index('>', idx)
        html = html[:end+1] + f'\n  {base_tag}' + html[end+1:]
    else:
        html = f'<head>{base_tag}</head>' + html
    return html

def _rewrite_proxy_css(css, port):
    """Rewrite url(/path) references in CSS through proxy."""
    def _sub(m):
        path = m.group(1)
        skip = ('http://', 'https://', '//', 'data:', '#')
        return m.group(0) if any(path.startswith(s) for s in skip) else f'url("/proxy/{port}{path}")'
    return re.sub(r'url\(["\']?(/[^"\')\s]+)["\']?\)', _sub, css)

# ── Proxy ─────────────────────────────────────────────────────────────────────

def proxy_fetch(port, subpath, query=''):
    """Proxy a request to a local service, stripping X-Frame-Options."""
    cache_key = (port, subpath, query)
    cached = _pcache_get(cache_key)
    if cached:
        return cached

    scheme = 'https' if port in HTTPS_PORTS else 'http'
    target = 'localhost' if LOCAL_MODE else SERVER_IP
    url = f'{scheme}://{target}:{port}/{subpath}'
    if query:
        url += '?' + query
    try:
        req = urllib.request.Request(url)
        req.add_header('User-Agent', 'Mozilla/5.0 ServerHub/1.0')
        with urllib.request.urlopen(req, timeout=12, context=_ssl_ctx) as resp:
            content = resp.read()
            ct = resp.headers.get('Content-Type', 'text/html; charset=utf-8')
            status = resp.status
    except urllib.error.HTTPError as e:
        content = e.read() or b'<h2>HTTP Error</h2>'
        ct = e.headers.get('Content-Type', 'text/html')
        status = e.code
    except Exception as e:
        content = f'<html><body style="background:#0d1117;color:#e6edf3;font-family:monospace;padding:40px"><h2>Proxy Error</h2><p>{e}</p><p>Service at port {port} may be down or unreachable.</p></body></html>'.encode()
        ct = 'text/html; charset=utf-8'
        status = 502

    if status < 400:
        if 'text/html' in ct:
            try:
                html = _rewrite_proxy_html(content.decode('utf-8', errors='replace'), port)
                content = html.encode('utf-8')
            except Exception:
                pass
        elif 'text/css' in ct:
            try:
                css = _rewrite_proxy_css(content.decode('utf-8', errors='replace'), port)
                content = css.encode('utf-8')
            except Exception:
                pass

    _pcache_put(cache_key, content, ct, status)
    return content, ct, status


# ── SSH ────────────────────────────────────────────────────────────────────────

def ssh_run(cmd, timeout=15):
    try:
        args = ['bash', '-c', cmd] if LOCAL_MODE else ['ssh', SSH_HOST, cmd]
        r = subprocess.run(
            args,
            capture_output=True, text=True, timeout=timeout
        )
        return {
            'output': r.stdout.strip(),
            'error': r.stderr.strip(),
            'exitcode': r.returncode,
            'online': r.returncode == 0 or r.stdout.strip() != ''
        }
    except subprocess.TimeoutExpired:
        return {'output': '', 'error': 'Connection timed out', 'exitcode': -1, 'online': False}
    except FileNotFoundError:
        return {'output': '', 'error': 'ssh not found in PATH', 'exitcode': -1, 'online': False}
    except Exception as e:
        return {'output': '', 'error': str(e), 'exitcode': -1, 'online': False}

# ── Status cache ───────────────────────────────────────────────────────────────

_cache = {'status': None, 'ts': 0, 'containers': None, 'containers_ts': 0}
_lock = threading.Lock()
_sessions = {}  # token -> {user, created}
_users_lock = threading.Lock()
_server_info_cache = None   # cached once per process restart

def get_server_info():
    """Fetch server identity once and cache for the lifetime of the process."""
    global _server_info_cache
    if _server_info_cache is not None:
        return _server_info_cache
    r = ssh_run(
        'printf "%s\t%s\t%s\t%s\t%s\t%s"'
        ' "$(hostname)"'
        ' "$(lsb_release -rs 2>/dev/null || uname -r)"'
        ' "$(ip route get 1 2>/dev/null | awk \'{print $7}\' | head -1)"'
        ' "$(tailscale ip -4 2>/dev/null || echo none)"'
        ' "$(nproc)"'
        ' "$(echo $HOME)"'
    )
    if r.get('online') and r.get('output'):
        parts = r['output'].split('\t')
        _server_info_cache = {
            'hostname':    parts[0].strip() if len(parts) > 0 else '',
            'os':          f"Ubuntu {parts[1].strip()}" if len(parts) > 1 else '',
            'local_ip':    parts[2].strip() if len(parts) > 2 else '',
            'tailscale_ip': parts[3].strip() if len(parts) > 3 else 'none',
            'cpu_cores':   int(parts[4].strip()) if len(parts) > 4 and parts[4].strip().isdigit() else 0,
            'home_dir':    parts[5].strip() if len(parts) > 5 and parts[5].strip() else '/root',
            'ssh_user':    SSH_USER or (SSH_HOST.split('@')[0] if '@' in SSH_HOST else ''),
        }
    else:
        # Offline / local mode fallback
        import pwd
        _server_info_cache = {
            'hostname': '',
            'os': '',
            'local_ip': '',
            'tailscale_ip': 'none',
            'cpu_cores': 0,
            'home_dir': os.path.expanduser('~'),
            'ssh_user': SSH_USER,
        }
    return _server_info_cache

def get_status(force=False):
    with _lock:
        age = time.time() - _cache['ts']
        if not force and _cache['status'] and age < 60:
            return _cache['status']

    r = ssh_run(
        'printf "%s---" "$(uptime -p)" '
        '"$(free -m | awk \'/^Mem/{print $3,$2}\')" '
        '"$(df -h / | awk \'NR==2{print $3,$2,$5}\')" '
        '"$(docker ps -q 2>/dev/null | wc -l)" '
        '"$(cat /proc/loadavg | awk \'{print $1,$2,$3}\')" '
        # All real mounted volumes (exclude tmpfs, loop/snap, devtmpfs)
        '"$(df -h -x tmpfs -x devtmpfs 2>/dev/null | awk \'NR>1 && !/loop/{printf "%s|%s|%s|%s|%s;", $1,$2,$3,$5,$6}\')" '
        # Unattached raw disks (no mount point) — shows drives not yet partitioned/mounted
        '"$(lsblk -dn -o NAME,SIZE,TYPE,MOUNTPOINTS 2>/dev/null | awk \'$3=="disk" && $4=="" {printf "%s|%s;", $1,$2}\')"'
    )

    if not r['online']:
        data = {'online': False, 'error': r['error']}
    else:
        try:
            parts = r['output'].split('---')
            ram = parts[1].strip().split()
            disk = parts[2].strip().split()

            # Parse all mounted real volumes
            disks = []
            for entry in (parts[5].strip().split(';') if len(parts) > 5 else []):
                p = entry.strip().split('|')
                if len(p) >= 5:
                    disks.append({
                        'device': p[0], 'total': p[1], 'used': p[2],
                        'pct': int(p[3].rstrip('%')) if p[3].rstrip('%').isdigit() else 0,
                        'mount': p[4],
                    })

            # Detect unattached drives (no filesystem, no mount — typically raw/unused)
            unattached = []
            for entry in (parts[6].strip().split(';') if len(parts) > 6 else []):
                p = entry.strip().split('|')
                if len(p) >= 2 and p[0]:
                    unattached.append({'name': p[0], 'size': p[1]})

            data = {
                'online': True,
                'uptime': parts[0].strip(),
                'ram_used_mb': int(ram[0]),
                'ram_total_mb': int(ram[1]),
                # Root FS values kept for backward compat with header stat
                'disk_used': disk[0],
                'disk_total': disk[1],
                'disk_pct': disk[2],
                'containers': int(parts[3].strip()),
                'load': parts[4].strip(),
                'fetched_at': datetime.now().strftime('%H:%M:%S'),
                'disks': disks,
                'unattached_drives': unattached,
            }
        except Exception as e:
            data = {'online': True, 'parse_error': str(e), 'raw': r['output']}

    if data.get('online'):
        si = get_server_info()
        # Build server_info copy with ram_total_gb — don't mutate the process-level cache
        if data.get('ram_total_mb'):
            si = dict(si)
            si['ram_total_gb'] = round(data['ram_total_mb'] / 1024, 1)
        data['server_info'] = si
        if si.get('cpu_cores'):
            data['cpu_cores'] = si['cpu_cores']
    with _lock:
        _cache['status'] = data
        _cache['ts'] = time.time()
    return data

def get_containers(force=False):
    with _lock:
        age = time.time() - _cache['containers_ts']
        if not force and _cache['containers'] and age < 30:
            return _cache['containers']

    r = ssh_run(
        'docker ps -a --format "{{.Names}}|{{.Status}}|{{.Ports}}|{{.Image}}"'
    )
    containers = []
    if r['online'] and r['output']:
        for line in r['output'].splitlines():
            parts = line.split('|')
            if len(parts) >= 3:
                containers.append({
                    'name': parts[0],
                    'status': parts[1],
                    'ports': parts[2],
                    'image': parts[3] if len(parts) > 3 else '',
                    'running': parts[1].lower().startswith('up'),
                })

    with _lock:
        _cache['containers'] = containers
        _cache['containers_ts'] = time.time()
    return containers

# ── Known services ─────────────────────────────────────────────────────────────

SERVICES = [
    {'name': 'NPM',         'port': 81,    'group': 'Infrastructure', 'description': 'Nginx Proxy Manager',  'installed': True},
    {'name': 'Portainer',   'port': 9443,  'group': 'Infrastructure', 'description': 'Container manager',     'installed': True,  'https': True},
    {'name': 'Cockpit',     'port': 9090,  'group': 'Infrastructure', 'description': 'Linux admin panel',     'installed': True,  'https': True},
    {'name': 'Homepage',    'port': 3000,  'group': 'Monitoring',     'description': 'Dashboard',             'installed': True},
    {'name': 'Uptime Kuma', 'port': 3001,  'group': 'Monitoring',     'description': 'Uptime monitoring',     'installed': True},
    {'name': 'Netdata',     'port': 19999, 'group': 'Monitoring',     'description': 'Real-time metrics',     'installed': True},
    {'name': 'Dozzle',      'port': 8090,  'group': 'Monitoring',     'description': 'Container log viewer',  'installed': True},
    {'name': 'ntfy',        'port': 8085,  'group': 'Notifications',  'description': 'Push notifications',    'installed': True},
    {'name': 'n8n',         'port': 5678,  'group': 'Tools',          'description': 'Workflow automation',   'installed': True},
    {'name': 'Supabase',    'port': 8000,  'group': 'Tools',          'description': 'Database platform',     'installed': False},
    {'name': 'Redis',       'port': 6379,  'group': 'Tools',          'description': 'Cache / key-value',     'installed': True,  'no_ui': True},
    {'name': 'SurrealDB',   'port': 8001,  'group': 'Tools',          'description': 'Multi-model / graph DB','installed': True},
    {'name': 'MinIO',       'port': 9001,  'group': 'Tools',          'description': 'Object storage (S3)',   'installed': False},
    {'name': 'Adminer',     'port': 8082,  'group': 'Tools',          'description': 'Database browser',      'installed': True},
    {'name': 'Mailpit',     'port': 8025,  'group': 'Tools',          'description': 'Dev email catcher',     'installed': True},
    {'name': 'Wiki.js',     'port': 3002,  'group': 'Tools',          'description': 'Knowledge base',        'installed': True},
    {'name': 'Ollama',      'port': 11434, 'group': 'AI',             'description': 'AI model engine',       'installed': True,  'no_ui': True},
    {'name': 'Open WebUI',  'port': 3004,  'group': 'AI',             'description': 'AI chat interface',     'installed': True},
]

def build_services(containers):
    running_names = {c['name'].lower() for c in containers if c['running']}
    result = []
    for s in SERVICES:
        svc = dict(s)
        scheme = 'https' if s.get('https') else 'http'
        svc['url'] = f"{scheme}://{SERVER_IP}:{s['port']}" if not s.get('no_ui') else None
        # Match container name heuristically
        n = s['name'].lower().replace(' ', '-').replace('.', '')
        svc['running'] = n in running_names or s['name'].lower() in running_names
        result.append(svc)
    return result

# ── SQLite helpers ─────────────────────────────────────────────────────────────

def db_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def get_setup_status():
    """Check which parts of server-kit have been installed."""
    home = os.path.expanduser('~')
    kit  = os.path.join(home, 'server-kit')

    def cmd_ok(c):
        try:
            return subprocess.run(c, shell=True, capture_output=True, timeout=3).returncode == 0
        except Exception:
            return False

    def svc_running(name):
        return cmd_ok(f"systemctl is-active {name} --quiet 2>/dev/null || systemctl --user is-active {name} --quiet 2>/dev/null")

    steps = [
        {'id': '01', 'label': 'System packages',   'done': cmd_ok('command -v git && command -v curl && command -v ufw')},
        {'id': '02', 'label': 'Docker',             'done': cmd_ok('docker info >/dev/null 2>&1')},
        {'id': '03', 'label': 'Nginx Proxy Mgr',   'done': cmd_ok('docker ps --filter name=npm --format "{{.Names}}" | grep -q npm')},
        {'id': '04', 'label': 'Cloudflare Tunnel',  'done': cmd_ok('docker ps --filter name=cloudflared --format "{{.Names}}" | grep -q cloudflared')},
        {'id': '05', 'label': 'Portainer',          'done': cmd_ok('docker ps --filter name=portainer --format "{{.Names}}" | grep -q portainer')},
        {'id': '06', 'label': 'Monitoring',         'done': cmd_ok('docker ps --filter name=uptime-kuma --format "{{.Names}}" | grep -q uptime-kuma')},
        {'id': '07', 'label': 'Claude CLI',         'done': cmd_ok('command -v claude')},
        {'id': '08', 'label': 'Optional services',  'done': os.path.isfile(os.path.join(home, '.server-kit-extras-done'))},
        {'id': '09', 'label': 'Backup',             'done': cmd_ok('command -v server-backup')},
        {'id': '10', 'label': 'CLI helpers',        'done': cmd_ok('command -v health-check')},
        {'id': '11', 'label': 'Hardware monitor',   'done': cmd_ok('command -v hw-monitor')},
        {'id': '12', 'label': 'Security tools',     'done': cmd_ok('command -v rkhunter')},
        {'id': '13', 'label': 'GitHub deploy',      'done': cmd_ok('command -v gh')},
        {'id': '14', 'label': 'Terminal setup',     'done': os.path.isfile(os.path.join(home, '.tmux.conf'))},
        {'id': '15', 'label': 'Alerts + ntfy',      'done': cmd_ok('docker ps --filter name=ntfy --format "{{.Names}}" | grep -q ntfy')},
        {'id': '16', 'label': 'AI stack',           'done': cmd_ok('docker ps --filter name=ollama --format "{{.Names}}" | grep -q ollama')},
    ]

    done_count = sum(1 for s in steps if s['done'])
    kit_present = os.path.isdir(kit)
    bootstrapped = done_count >= 2  # at least packages + docker

    return {
        'steps': steps,
        'done_count': done_count,
        'total': len(steps),
        'complete': done_count == len(steps),
        'bootstrapped': bootstrapped,
        'kit_present': kit_present,
        'kit_path': kit if kit_present else None,
    }

def vault_get():
    try:
        conn = db_conn()
        row = conn.execute("SELECT value FROM notes WHERE key='vault_blob' LIMIT 1").fetchone()
        conn.close()
        return row['value'] if row else None
    except Exception:
        return None

def vault_put(blob):
    try:
        conn = db_conn()
        ts = datetime.now().isoformat()
        row = conn.execute("SELECT id FROM notes WHERE key='vault_blob' LIMIT 1").fetchone()
        if row:
            conn.execute("UPDATE notes SET value=?, updated=? WHERE key='vault_blob'", (blob, ts))
        else:
            conn.execute("INSERT INTO notes (category, key, value, updated) VALUES ('vault','vault_blob',?,?)", (blob, ts))
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        return str(e)

def issues_get():
    try:
        conn = db_conn()
        rows = conn.execute("SELECT * FROM issues ORDER BY id DESC").fetchall()
        conn.close()
        return [dict(r) for r in rows]
    except Exception:
        return []

def db_ensure_tables():
    try:
        conn = db_conn()
        conn.execute("""CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY,
            username TEXT UNIQUE NOT NULL,
            display TEXT,
            password_hash TEXT NOT NULL,
            role TEXT DEFAULT 'admin',
            created TEXT
        )""")
        conn.execute("""CREATE TABLE IF NOT EXISTS hub_config (
            key TEXT PRIMARY KEY,
            value TEXT,
            updated TEXT
        )""")
        conn.execute("""CREATE TABLE IF NOT EXISTS journal (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts TEXT NOT NULL,
            type TEXT NOT NULL,
            body TEXT NOT NULL,
            user TEXT DEFAULT ''
        )""")
        # Seed default admin if no users exist
        row = conn.execute("SELECT COUNT(*) as c FROM users").fetchone()
        if row['c'] == 0:
            h = hashlib.sha256(b'admin').hexdigest()
            conn.execute("INSERT INTO users (username,display,password_hash,role,created) VALUES (?,?,?,?,?)",
                ('admin','Administrator',h,'admin',datetime.now().isoformat()))
        conn.commit()
        conn.close()
    except Exception as e:
        print(f'  DB init error: {e}')

def config_get(key, default=None):
    try:
        conn = db_conn()
        row = conn.execute("SELECT value FROM hub_config WHERE key=?", (key,)).fetchone()
        conn.close()
        return row['value'] if row else default
    except Exception:
        return default

def config_set(key, value):
    try:
        conn = db_conn()
        ts = datetime.now().isoformat()
        conn.execute("INSERT INTO hub_config(key,value,updated) VALUES(?,?,?) ON CONFLICT(key) DO UPDATE SET value=?,updated=?",
            (key, value, ts, value, ts))
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        return str(e)

def users_list():
    try:
        conn = db_conn()
        rows = conn.execute("SELECT id,username,display,role,created FROM users ORDER BY id").fetchall()
        conn.close()
        return [dict(r) for r in rows]
    except Exception:
        return []

def user_auth(username, password):
    try:
        h = hashlib.sha256(password.encode()).hexdigest()
        conn = db_conn()
        row = conn.execute("SELECT * FROM users WHERE username=? AND password_hash=?", (username, h)).fetchone()
        conn.close()
        return dict(row) if row else None
    except Exception:
        return None

def journal_add(type_, body, user=''):
    try:
        conn = db_conn()
        conn.execute("INSERT INTO journal(ts,type,body,user) VALUES(?,?,?,?)",
            (datetime.now().isoformat(), type_, body, user))
        conn.commit()
        conn.close()
    except Exception:
        pass

def journal_get(limit=100):
    try:
        conn = db_conn()
        rows = conn.execute("SELECT * FROM journal ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        conn.close()
        return [dict(r) for r in rows]
    except Exception:
        return []

def get_storage_info():
    results = {}
    # Disk usage
    r = ssh_run("df -h / /srv 2>/dev/null | tail -n +2")
    results['disk'] = r.get('output','') if r.get('online') else ''
    # Docker volumes
    r2 = ssh_run("docker system df 2>/dev/null")
    results['docker_df'] = r2.get('output','') if r2.get('online') else ''
    # Key directory sizes
    r3 = ssh_run("du -sh /srv/docker /srv/backups $HOME 2>/dev/null")
    results['dirs'] = r3.get('output','') if r3.get('online') else ''
    # Docker volumes list
    r4 = ssh_run("docker volume ls --format '{{.Name}}' 2>/dev/null | head -30")
    results['volumes'] = r4.get('output','') if r4.get('online') else ''
    return results

def get_files(path):
    safe = path.replace('..','').replace('~','').strip()
    if not safe.startswith('/'):
        safe = get_server_info().get('home_dir', '/root')
    r = ssh_run(f"ls -lah --time-style=short-iso '{safe}' 2>&1 | head -60")
    return {'path': safe, 'listing': r.get('output',''), 'error': r.get('error','') if not r.get('online') else ''}

def get_manifest():
    """Full system snapshot — server info, all services, containers, health."""
    now = datetime.now().isoformat()

    # One SSH call for server identity
    info_r = ssh_run(
        'printf "%s\t%s\t%s\t%s\t%s\t%s" '
        '"$(hostname)" '
        '"$(lsb_release -rs 2>/dev/null)" '
        '"$(uname -r)" '
        '"$(ip route get 1 2>/dev/null | awk \'{print $7}\' | head -1)" '
        '"$(tailscale ip -4 2>/dev/null || echo none)" '
        '"$(nproc)"'
    )
    server = {}
    if info_r.get('online') and info_r.get('output'):
        parts = info_r['output'].split('\t')
        server = {
            'hostname': parts[0] if len(parts) > 0 else '',
            'os': f'Ubuntu {parts[1]}' if len(parts) > 1 else '',
            'kernel': parts[2] if len(parts) > 2 else '',
            'local_ip': parts[3] if len(parts) > 3 else '',
            'tailscale_ip': parts[4] if len(parts) > 4 else 'none',
            'cpu_cores': int(parts[5]) if len(parts) > 5 and parts[5].strip().isdigit() else 0,
        }

    status = get_status()
    if status.get('ram_total_mb'):
        server['ram_total_gb'] = round(status['ram_total_mb'] / 1024, 1)

    containers = get_containers()
    services = build_services(containers)

    # Hub git ref (if running from a git checkout)
    git_r = ssh_run('cd ~/hub && git log -1 --format="%h %s" 2>/dev/null || echo unknown')
    hub_ref = git_r.get('output', 'unknown').strip() if git_r.get('online') else 'unknown'

    # Docker disk usage
    docker_r = ssh_run("docker system df --format '{{.Type}}\t{{.Active}}\t{{.Size}}' 2>/dev/null")

    return {
        'generated_at': now,
        'hub_ref': hub_ref,
        'server': server,
        'uptime': status.get('uptime', ''),
        'load': status.get('load', ''),
        'disk': {'used': status.get('disk_used', ''), 'total': status.get('disk_total', ''), 'pct': status.get('disk_pct', '')},
        'containers': {
            'total': len(containers),
            'running': sum(1 for c in containers if c['running']),
            'stopped': sum(1 for c in containers if not c['running']),
            'list': containers,
        },
        'services': [
            {'name': s['name'], 'group': s['group'], 'port': s['port'],
             'description': s['description'], 'installed': s['installed'],
             'running': s.get('running', False), 'url': s.get('url')}
            for s in services
        ],
        'docker_df': docker_r.get('output', '') if docker_r.get('online') else '',
        'ssh_host': SSH_HOST,
        'server_ip': SERVER_IP,
    }


def _substitute_guide_tokens(text):
    """Replace {{server.*}} and {{hub.*}} template tokens with live values."""
    si = get_server_info()
    replacements = {
        '{{server.hostname}}':    si.get('hostname', ''),
        '{{server.local_ip}}':    si.get('local_ip', ''),
        '{{server.tailscale_ip}}':si.get('tailscale_ip', 'none'),
        '{{server.os}}':          si.get('os', ''),
        '{{server.home_dir}}':    si.get('home_dir', '/root'),
        '{{server.ssh_user}}':    si.get('ssh_user', ''),
        '{{server.cpu_cores}}':   str(si.get('cpu_cores', '')),
        '{{hub.port}}':           str(PORT),
        '{{hub.host}}':           SSH_HOST,
    }
    for token, val in replacements.items():
        text = text.replace(token, val)
    return text

def _build_this_server_doc():
    """Generate a live 'About this server' doc from current server state."""
    si = get_server_info()
    st = _cache.get('status') or {}
    containers = _cache.get('containers') or []
    running = [c['name'] for c in containers if c.get('running')]
    stopped = [c['name'] for c in containers if not c.get('running')]

    ram_gb = ''
    if st.get('ram_total_mb'):
        ram_gb = f"{round(st['ram_total_mb'] / 1024, 1)} GB"

    disk_lines = ''
    for d in st.get('disks', []):
        disk_lines += f"- `{d['mount']}` — {d['used']} used of {d['total']} ({d['pct']}%)\n"
    if not disk_lines:
        disk_lines = f"- `/` — {st.get('disk_used','?')} used of {st.get('disk_total','?')} ({st.get('disk_pct','?')})\n"

    unattached = st.get('unattached_drives', [])
    unattached_lines = ''
    for u in unattached:
        unattached_lines += f"- `/dev/{u['name']}` — {u['size']} (unmounted, raw)\n"

    ts_line = si.get('tailscale_ip', 'none')
    ts_section = (
        f"- Tailscale: `{ts_line}`\n"
        if ts_line and ts_line != 'none' else
        "- Tailscale: not connected\n"
    )

    now = datetime.now().strftime('%Y-%m-%d %H:%M')

    doc = f"""# This Server

> Auto-generated snapshot · {now}

---

## Identity

| Field | Value |
|-------|-------|
| Hostname | `{si.get('hostname','—')}` |
| OS | {si.get('os','—')} |
| SSH User | `{si.get('ssh_user','—')}` |
| Home Dir | `{si.get('home_dir','—')}` |
| CPU Cores | {si.get('cpu_cores','—')} |
| RAM | {ram_gb or '—'} |

---

## Network

- Local IP: `{si.get('local_ip','—')}`
{ts_section}
---

## Disk

### Mounted Volumes

{disk_lines or '(no data — run a status refresh)'}
"""

    if unattached_lines:
        doc += f"""
### Unmounted Drives

{unattached_lines}
> These drives have no filesystem. Run `lsblk` to inspect. See `storage.md` for how to partition and mount them.
"""

    doc += f"""
---

## Docker

| Metric | Count |
|--------|-------|
| Running containers | {len(running)} |
| Stopped containers | {len(stopped)} |

"""
    if running:
        doc += "**Running:** " + ", ".join(f"`{c}`" for c in running[:20]) + "\n\n"
    if stopped:
        doc += "**Stopped:** " + ", ".join(f"`{c}`" for c in stopped[:20]) + "\n\n"

    doc += f"""---

## Hub

- Port: `{PORT}`
- SSH target: `{SSH_HOST}`
- Mode: {'local (hub on this machine)' if LOCAL_MODE else 'remote SSH'}

---

## Access Paths

| Method | Address |
|--------|---------|
| Local | `http://{si.get('local_ip','?')}:{PORT}` |
"""
    ts_ip = si.get('tailscale_ip', 'none')
    if ts_ip and ts_ip != 'none':
        doc += f"| Tailscale | `http://{ts_ip}:{PORT}` |\n"

    doc += "\nSee `remote-access.md` for full access topology.\n"
    return doc

def ai_system_prompt():
    """Build a concise server-aware system prompt from live state."""
    status = _cache.get('status') or {}
    containers = _cache.get('containers') or []
    running = [c['name'] for c in containers if c.get('running')]
    lines = [
        'You are an AI assistant with full context about this Linux server.',
        f'Hostname: {SSH_HOST}  |  OS: Ubuntu  |  Mode: {"local" if LOCAL_MODE else "remote"}',
        f'RAM: {status.get("ram_used_mb","?")}MB / {status.get("ram_total_mb","?")}MB  '
        f'|  Disk: {status.get("disk_used","?")} / {status.get("disk_total","?")} ({status.get("disk_pct","?")})',
        f'Load: {status.get("load","?")}  |  Uptime: {status.get("uptime","?")}',
        f'Running containers ({len(running)}): {", ".join(running[:12]) or "none"}',
        '',
        'Answer concisely. For server tasks suggest shell commands. '
        'If shown a photo, describe what you see and relate it to server/infrastructure context if relevant.',
    ]
    return '\n'.join(lines)

def ai_chat(message, image_b64=None, image_type='image/jpeg'):
    """Call Claude or OpenAI depending on which key is configured."""
    provider = config_get('ai_provider', 'claude')
    api_key  = config_get('ai_api_key', os.environ.get('HUB_AI_KEY', ''))
    if not api_key:
        return {'error': 'No AI API key configured. Add one in Hub Settings → AI.'}

    system = ai_system_prompt()

    try:
        if provider in ('claude', 'anthropic'):
            content = []
            if image_b64:
                content.append({'type': 'image', 'source': {
                    'type': 'base64', 'media_type': image_type, 'data': image_b64}})
            content.append({'type': 'text', 'text': message})
            payload = json.dumps({
                'model': 'claude-opus-5-20251101',
                'max_tokens': 1024,
                'system': system,
                'messages': [{'role': 'user', 'content': content}],
            }).encode()
            req = urllib.request.Request(
                'https://api.anthropic.com/v1/messages',
                data=payload,
                headers={
                    'x-api-key': api_key,
                    'anthropic-version': '2023-06-01',
                    'content-type': 'application/json',
                }, method='POST')
            with urllib.request.urlopen(req, timeout=30) as r:
                data = json.loads(r.read())
            return {'reply': data['content'][0]['text'], 'provider': 'claude'}

        elif provider in ('openai', 'gpt'):
            content = []
            if image_b64:
                content.append({'type': 'image_url', 'image_url': {
                    'url': f'data:{image_type};base64,{image_b64}'}})
            content.append({'type': 'text', 'text': message})
            payload = json.dumps({
                'model': 'gpt-4o',
                'max_tokens': 1024,
                'messages': [
                    {'role': 'system', 'content': system},
                    {'role': 'user', 'content': content if image_b64 else message},
                ],
            }).encode()
            req = urllib.request.Request(
                'https://api.openai.com/v1/chat/completions',
                data=payload,
                headers={
                    'Authorization': f'Bearer {api_key}',
                    'content-type': 'application/json',
                }, method='POST')
            with urllib.request.urlopen(req, timeout=30) as r:
                data = json.loads(r.read())
            return {'reply': data['choices'][0]['message']['content'], 'provider': 'openai'}

        elif provider == 'gemini':
            parts = []
            if image_b64:
                parts.append({'inline_data': {'mime_type': image_type, 'data': image_b64}})
            parts.append({'text': message})
            payload = json.dumps({
                'system_instruction': {'parts': [{'text': system}]},
                'contents': [{'parts': parts}],
                'generationConfig': {'maxOutputTokens': 1024},
            }).encode()
            url = f'https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={api_key}'
            req = urllib.request.Request(url, data=payload,
                headers={'content-type': 'application/json'}, method='POST')
            with urllib.request.urlopen(req, timeout=30) as r:
                data = json.loads(r.read())
            return {'reply': data['candidates'][0]['content']['parts'][0]['text'], 'provider': 'gemini'}

        else:
            return {'error': f'Unknown provider: {provider}'}

    except urllib.error.HTTPError as e:
        body = e.read().decode('utf-8', errors='replace')[:300]
        return {'error': f'API error {e.code}: {body}'}
    except Exception as e:
        return {'error': str(e)}


def get_integrations():
    """Live health check for Redis, SurrealDB, n8n."""
    results = {}

    # Redis — PING via docker exec
    r = ssh_run("docker exec redis redis-cli ping 2>/dev/null")
    results['redis'] = {
        'running': r.get('output','').strip() == 'PONG',
        'info': r.get('output','').strip() or r.get('error',''),
    }
    # Redis keyspace stats
    r2 = ssh_run("docker exec redis redis-cli info keyspace 2>/dev/null")
    results['redis']['keyspace'] = r2.get('output','').strip()

    # SurrealDB — HTTP 200 with empty body means healthy
    r3 = ssh_run("curl -s -o /dev/null -w '%{http_code}' http://localhost:8001/health 2>/dev/null")
    surreal_code = r3.get('output','').strip()
    results['surrealdb'] = {
        'running': surreal_code == '200',
        'info': f'HTTP {surreal_code}' if surreal_code else r3.get('error',''),
        'url': f'http://{SERVER_IP}:8001',
        'user': 'root',
    }

    # n8n — check its health endpoint
    r4 = ssh_run("curl -s -o /dev/null -w '%{http_code}' http://localhost:5678/healthz 2>/dev/null")
    code = r4.get('output','').strip()
    results['n8n'] = {
        'running': code == '200',
        'info': f'HTTP {code}' if code else r4.get('error',''),
        'webhook_base': f'http://{SERVER_IP}:5678/webhook/',
        'ui': f'http://{SERVER_IP}:5678',
    }

    return results

def check_auth(handler):
    token = handler.headers.get('X-Hub-Token','')
    if not token:
        # Also accept from query string
        qs = handler.path.split('?',1)[1] if '?' in handler.path else ''
        for part in qs.split('&'):
            if part.startswith('token='):
                token = part[6:]
    with _users_lock:
        return _sessions.get(token)

# ── TOTP ──────────────────────────────────────────────────────────────────────

def _totp_hotp(secret, counter):
    try:
        key = base64.b32decode(secret.upper().replace(' ', ''))
        msg = struct.pack('>Q', counter)
        h = hmac.new(key, msg, hashlib.sha1).digest()
        offset = h[-1] & 0x0f
        code = struct.unpack('>I', bytes(h[offset:offset+4]))[0] & 0x7fffffff
        return str(code % 1_000_000).zfill(6)
    except Exception:
        return ''

def totp_verify(code):
    secret = config_get('totp_secret', '')
    if not secret:
        return False
    t = int(time.time()) // 30
    code = str(code).strip().zfill(6)
    return any(_totp_hotp(secret, t + d) == code for d in (-1, 0, 1))

def totp_new_secret():
    # Generate only — does NOT save to DB.
    # Caller must call /api/totp/confirm with a valid code to activate.
    return base64.b32encode(os.urandom(20)).decode()

def totp_verify_secret(secret, code):
    """Verify a code against any given secret (not necessarily the saved one)."""
    if not secret:
        return False
    t = int(time.time()) // 30
    code = str(code).strip().zfill(6)
    return any(_totp_hotp(secret, t + d) == code for d in (-1, 0, 1))

def totp_uri(secret, account='admin'):
    import urllib.parse as _up
    params = _up.urlencode({'secret': secret, 'issuer': 'ServerHub',
                            'algorithm': 'SHA1', 'digits': '6', 'period': '30'})
    return f'otpauth://totp/ServerHub%3A{account}?{params}'

# ── Gate sessions ─────────────────────────────────────────────────────────────

_gate_sessions = {}
_gate_lock     = threading.Lock()

def gate_create(level, user, duration_s=1800):
    token   = secrets.token_hex(24)
    expires = time.time() + duration_s
    with _gate_lock:
        now = time.time()
        stale = [k for k, v in _gate_sessions.items() if v['expires'] < now]
        for k in stale:
            del _gate_sessions[k]
        _gate_sessions[token] = {'level': level, 'user': user, 'expires': expires}
    return token, expires

def gate_check(headers, required_level=3):
    """Return True if TOTP not configured OR valid gate token found at required_level+."""
    if not config_get('totp_secret', ''):
        return True
    token = headers.get('X-Gate-Token', '')
    if not token:
        return False
    with _gate_lock:
        g = _gate_sessions.get(token)
    if not g:
        return False
    if g['level'] < required_level:
        return False
    if time.time() > g['expires']:
        with _gate_lock:
            _gate_sessions.pop(token, None)
        return False
    return True

# ── Tunnel management ─────────────────────────────────────────────────────────
_tunnel_url    = ''
_tunnel_lock_t = threading.Lock()
_tunnel_thread = None

def _tunnel_watcher():
    """Background thread: poll cloudflared logs to extract the public URL."""
    global _tunnel_url
    while True:
        try:
            r = subprocess.run(
                ['docker', 'logs', '--tail', '80', 'cloudflared'],
                capture_output=True, text=True, timeout=6
            )
            m = re.search(r'https://[a-z0-9\-]+\.trycloudflare\.com', r.stdout + r.stderr)
            with _tunnel_lock_t:
                _tunnel_url = m.group(0) if m else _tunnel_url
        except Exception:
            pass
        time.sleep(4)

def tunnel_status():
    try:
        r = subprocess.run(
            ['docker', 'inspect', '--format', '{{.State.Status}}', 'cloudflared'],
            capture_output=True, text=True, timeout=5
        )
        running = r.stdout.strip() == 'running'
    except Exception:
        running = False
    with _tunnel_lock_t:
        url = _tunnel_url if running else ''
    return {'running': running, 'url': url}

def tunnel_start():
    global _tunnel_url, _tunnel_thread
    try:
        subprocess.run(['docker', 'rm', '-f', 'cloudflared'], capture_output=True, timeout=8)
        r = subprocess.run(
            ['docker', 'run', '-d', '--name', 'cloudflared', '--network', 'host',
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

def tunnel_stop():
    global _tunnel_url
    try:
        subprocess.run(['docker', 'stop', 'cloudflared'], capture_output=True, timeout=15)
        subprocess.run(['docker', 'rm', 'cloudflared'], capture_output=True, timeout=10)
        with _tunnel_lock_t:
            _tunnel_url = ''
        return True
    except Exception:
        return False

def get_access_info():
    """Return all accessible URLs for this hub."""
    local_ip = SERVER_IP
    try:
        r = subprocess.run(
            "ip route get 1 2>/dev/null | awk '{print $7}' | head -1",
            shell=True, capture_output=True, text=True, timeout=5
        )
        ip = r.stdout.strip()
        if ip:
            local_ip = ip
    except Exception:
        pass
    ts_ip = None
    try:
        r = subprocess.run(['tailscale', 'ip', '-4'], capture_output=True, text=True, timeout=5)
        ts = r.stdout.strip()
        if ts and ts != 'none':
            ts_ip = ts
    except Exception:
        pass
    return {
        'local_ip':       local_ip,
        'local_url':      f'http://{local_ip}:{PORT}',
        'tailscale_ip':   ts_ip,
        'tailscale_url':  f'http://{ts_ip}:{PORT}' if ts_ip else None,
        'port':           PORT,
        'tunnel':         tunnel_status(),
    }

# ── HTTP handler ───────────────────────────────────────────────────────────────

class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass

    def send_json(self, data, status=200):
        body = json.dumps(data, default=str).encode()
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type, X-Hub-Token')
        self.end_headers()

    def get_body(self):
        n = int(self.headers.get('Content-Length', 0))
        return json.loads(self.rfile.read(n)) if n else {}

    def do_GET(self):
        p = self.path.split('?')[0]
        force = 'force' in self.path

        if p in ('/', '/mobile', '/desktop'):
            ua = self.headers.get('User-Agent', '')
            is_mobile = any(x in ua for x in ('Mobile','Android','iPhone','iPad','iPod','BlackBerry','Windows Phone'))
            if p == '/' and is_mobile:
                self.send_response(302)
                self.send_header('Location', '/mobile')
                self.end_headers()
                return
            path = MOBILE_PATH if (p == '/mobile' or (p == '/' and is_mobile)) else APP_PATH
            try:
                with open(path, 'rb') as f:
                    content = f.read()
                self.send_response(200)
                self.send_header('Content-Type', 'text/html; charset=utf-8')
                self.send_header('Content-Length', str(len(content)))
                self.end_headers()
                self.wfile.write(content)
            except FileNotFoundError:
                self.send_response(404)
                self.end_headers()

        elif p == '/manifest.json':
            manifest = {
                "name": "Server Hub",
                "short_name": "Hub",
                "description": "Home server control panel",
                "start_url": "/",
                "display": "standalone",
                "background_color": "#0d1117",
                "theme_color": "#58a6ff",
                "icons": [
                    {"src": "data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'%3E%3Crect width='100' height='100' rx='18' fill='%230d1117'/%3E%3Ctext y='.9em' font-size='80' x='10'%3E%F0%9F%96%A5%3C/text%3E%3C/svg%3E", "sizes": "any", "type": "image/svg+xml", "purpose": "any maskable"}
                ]
            }
            content = json.dumps(manifest).encode()
            self.send_response(200)
            self.send_header('Content-Type', 'application/manifest+json')
            self.send_header('Content-Length', str(len(content)))
            self.end_headers()
            self.wfile.write(content)

        elif p == '/sw.js':
            sw = b"self.addEventListener('fetch', () => {});"
            self.send_response(200)
            self.send_header('Content-Type', 'application/javascript')
            self.send_header('Content-Length', str(len(sw)))
            self.end_headers()
            self.wfile.write(sw)

        elif p == '/api/status':
            self.send_json(get_status(force=force))

        elif p == '/api/setup/status':
            self.send_json(get_setup_status())

        elif p == '/api/containers':
            self.send_json(get_containers(force=force))

        elif p == '/api/services':
            containers = get_containers()
            self.send_json(build_services(containers))

        elif p == '/api/vault':
            blob = vault_get()
            self.send_json({'blob': blob})

        elif p == '/api/issues':
            self.send_json(issues_get())

        elif p == '/api/docs':
            try:
                files = []
                # Synthetic live doc always listed first
                files.append({'file': 'this-server.md', 'title': 'This Server'})
                if os.path.isdir(GUIDES_DIR):
                    for f in sorted(os.listdir(GUIDES_DIR)):
                        if f.endswith('.md'):
                            full = os.path.join(GUIDES_DIR, f)
                            with open(full, 'r', encoding='utf-8') as fh:
                                first_line = fh.readline().strip().lstrip('#').strip()
                            files.append({'file': f, 'title': first_line or f})
                self.send_json(files)
            except Exception as e:
                self.send_json([])

        elif p == '/api/docs/content':
            fname = ''
            if '?' in self.path:
                qs = self.path.split('?', 1)[1]
                for part in qs.split('&'):
                    if part.startswith('file='):
                        fname = part[5:]
            if not fname or '/' in fname or '\\' in fname or not fname.endswith('.md'):
                self.send_response(400); self.end_headers(); return
            # Special synthetic file: this-server.md — generated live from server_info
            if fname == 'this-server.md':
                content = _build_this_server_doc()
                self.send_json({'content': content, 'file': fname})
                return
            fpath = os.path.join(GUIDES_DIR, fname)
            try:
                with open(fpath, 'r', encoding='utf-8') as fh:
                    content = fh.read()
                # Template substitution: replace {{server.*}} and {{hub.*}} tokens with live values
                content = _substitute_guide_tokens(content)
                self.send_json({'content': content, 'file': fname})
            except FileNotFoundError:
                self.send_response(404); self.end_headers()

        elif p == '/api/auth/check':
            sess = check_auth(self)
            if sess:
                self.send_json({'ok': True, 'user': sess['user']})
            else:
                self.send_json({'ok': False}, 401)

        elif p == '/api/my-ip':
            # Return the connecting client's IP address (useful for fail2ban unban)
            client_ip = self.client_address[0]
            # X-Forwarded-For from reverse proxy
            xff = self.headers.get('X-Forwarded-For', '')
            if xff:
                client_ip = xff.split(',')[0].strip()
            self.send_json({'ip': client_ip})

        elif p == '/api/storage':
            self.send_json(get_storage_info())

        elif p == '/api/files':
            path = get_server_info().get('home_dir', '/')
            if '?' in self.path:
                for part in self.path.split('?',1)[1].split('&'):
                    if part.startswith('path='):
                        path = part[5:].replace('%2F','/')
            self.send_json(get_files(path))

        elif p == '/api/journal':
            limit = 100
            if '?' in self.path:
                for part in self.path.split('?',1)[1].split('&'):
                    if part.startswith('limit='):
                        try: limit = int(part[6:])
                        except: pass
            self.send_json(journal_get(limit))

        elif p == '/api/config':
            try:
                conn = db_conn()
                rows = conn.execute("SELECT key,value FROM hub_config").fetchall()
                conn.close()
                self.send_json({r['key']:r['value'] for r in rows})
            except Exception:
                self.send_json({})

        elif p == '/api/users':
            self.send_json(users_list())

        elif p == '/api/integrations':
            self.send_json(get_integrations())

        elif p == '/api/access':
            self.send_json(get_access_info())

        elif p == '/api/ai/config':
            self.send_json({
                'provider': config_get('ai_provider', 'claude'),
                'has_key': bool(config_get('ai_api_key', os.environ.get('HUB_AI_KEY', ''))),
            })

        elif p == '/api/totp/status':
            secret = config_get('totp_secret', '')
            with _gate_lock:
                now = time.time()
                gates = [{'level': v['level'], 'user': v['user'],
                          'expires_in': int(v['expires'] - now)}
                         for v in _gate_sessions.values() if v['expires'] > now]
            self.send_json({'configured': bool(secret), 'gates': gates})

        elif p == '/api/totp/setup':
            # Always generate a fresh temp secret — never saved to DB here.
            # The status endpoint tells the UI whether 2FA is already active.
            # This endpoint is only called when the user wants to begin setup.
            new_secret = totp_new_secret()
            sess = check_auth(self)
            account = sess['user'] if sess else 'admin'
            self.send_json({
                'secret': new_secret,
                'uri': totp_uri(new_secret, account),
            })

        elif p == '/api/manifest':
            data = get_manifest()
            body = json.dumps(data, default=str, indent=2).encode()
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(body)))
            self.send_header('Access-Control-Allow-Origin', '*')
            if 'download' in self.path:
                fname = f'server-manifest-{datetime.now().strftime("%Y%m%d-%H%M")}.json'
                self.send_header('Content-Disposition', f'attachment; filename="{fname}"')
            self.end_headers()
            self.wfile.write(body)

        elif p.startswith('/proxy/'):
            # /proxy/3000/some/path?query=string
            remainder = p[7:]  # e.g. "3000/some/path"
            slash = remainder.find('/')
            if slash == -1:
                port_str, subpath = remainder, ''
            else:
                port_str, subpath = remainder[:slash], remainder[slash+1:]
            query = self.path.split('?', 1)[1] if '?' in self.path else ''
            try:
                port = int(port_str)
            except ValueError:
                self.send_response(400)
                self.end_headers()
                return
            content, ct, status = proxy_fetch(port, subpath, query)
            self.send_response(status)
            self.send_header('Content-Type', ct)
            self.send_header('Content-Length', str(len(content)))
            # Explicitly NOT forwarding X-Frame-Options or CSP frame-ancestors
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            self.wfile.write(content)

        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        p = self.path
        body = self.get_body()

        if p == '/api/run':
            cmd = body.get('command', '').strip()
            if not cmd:
                self.send_json({'error': 'No command provided'}, 400)
                return
            if not gate_check(self.headers, required_level=3):
                self.send_json({'error': 'gate_required', 'layer': 3,
                                'message': 'Shell access requires TOTP verification'}, 403)
                return
            result = ssh_run(cmd, timeout=int(body.get('timeout', 30)))
            self.send_json(result)

        elif p == '/api/vault':
            blob = body.get('blob')
            if blob is None:
                self.send_json({'ok': False, 'error': 'No blob'}, 400)
                return
            if not gate_check(self.headers, required_level=2):
                self.send_json({'error': 'gate_required', 'layer': 2,
                                'message': 'Vault writes require TOTP verification'}, 403)
                return
            ok = vault_put(blob)
            if ok is True:
                self.send_json({'ok': True})
            else:
                self.send_json({'ok': False, 'error': str(ok)})

        elif p == '/api/refresh':
            get_status(force=True)
            get_containers(force=True)
            self.send_json({'ok': True})

        elif p == '/api/auth/login':
            username = body.get('username','').strip()
            password = body.get('password','')
            user = user_auth(username, password)
            if user:
                token = secrets.token_hex(32)
                with _users_lock:
                    _sessions[token] = {'user': username, 'role': user.get('role','admin'), 'created': datetime.now().isoformat()}
                self.send_json({'ok': True, 'token': token, 'user': username, 'role': user.get('role','admin')})
            else:
                self.send_json({'ok': False, 'error': 'Invalid username or password'}, 401)

        elif p == '/api/auth/logout':
            token = body.get('token','')
            with _users_lock:
                _sessions.pop(token, None)
            self.send_json({'ok': True})

        elif p == '/api/config':
            if not gate_check(self.headers, required_level=2):
                self.send_json({'error': 'gate_required', 'layer': 2,
                                'message': 'Config writes require TOTP verification'}, 403)
                return
            for k, v in body.items():
                config_set(k, str(v))
            self.send_json({'ok': True})

        elif p == '/api/journal':
            body_text = body.get('body','').strip()
            if body_text:
                journal_add(body.get('type','manual'), body_text, body.get('user',''))
                self.send_json({'ok': True})
            else:
                self.send_json({'ok': False, 'error': 'No body'}, 400)

        elif p == '/api/ai/chat':
            message    = body.get('message', '').strip()
            image_b64  = body.get('image')       # base64 string, no data-URI prefix
            image_type = body.get('image_type', 'image/jpeg')
            if not message and not image_b64:
                self.send_json({'error': 'No message or image'}, 400)
                return
            result = ai_chat(message or 'Describe this image in the context of my server.', image_b64, image_type)
            self.send_json(result)

        elif p == '/api/ai/config':
            provider = body.get('provider', '').strip()
            api_key  = body.get('api_key', '').strip()
            if provider: config_set('ai_provider', provider)
            if api_key:  config_set('ai_api_key', api_key)
            self.send_json({'ok': True})

        elif p == '/api/totp/confirm':
            # Activate 2FA: verify code against a temp secret, save only if valid.
            # This is called during setup — not for gate unlock.
            secret = str(body.get('secret', '')).strip()
            code   = str(body.get('code', '')).strip()
            if not secret:
                self.send_json({'ok': False, 'error': 'No secret provided'}, 400)
                return
            if not totp_verify_secret(secret, code):
                self.send_json({'ok': False, 'error': 'Invalid code — check your authenticator app'}, 401)
                return
            # Code is valid → save secret → 2FA is now active
            config_set('totp_secret', secret)
            journal_add('security', '2FA enabled via setup confirmation', '')
            self.send_json({'ok': True})

        elif p == '/api/totp/verify':
            code = str(body.get('code', '')).strip()
            level = max(1, min(4, int(body.get('level', 3))))
            duration = int(body.get('duration_s', 1800))
            if not totp_verify(code):
                self.send_json({'ok': False, 'error': 'Invalid or expired code'}, 401)
                return
            sess = check_auth(self)
            user = sess['user'] if sess else 'api'
            gate_token, expires = gate_create(level, user, duration)
            journal_add('gate_unlock', f'Level {level} gate opened ({duration//60}m) by {user}', user)
            self.send_json({
                'ok': True,
                'gate_token': gate_token,
                'expires_at': datetime.fromtimestamp(expires).isoformat(),
                'expires_in': int(expires - time.time()),
                'level': level,
            })

        elif p == '/api/totp/disable':
            code = str(body.get('code', '')).strip()
            if not totp_verify(code):
                self.send_json({'ok': False, 'error': 'Invalid code'}, 401)
                return
            config_set('totp_secret', '')
            with _gate_lock:
                _gate_sessions.clear()
            journal_add('gate_unlock', 'TOTP disabled', '')
            self.send_json({'ok': True})

        elif p == '/api/service/install':
            name = body.get('name','').strip().lower()
            INSTALLABLE = {
                'n8n':       'cd /srv/docker/n8n && docker compose up -d',
                'redis':     'cd /srv/docker/redis && docker compose up -d',
                'surrealdb': 'cd /srv/docker/surrealdb && docker compose up -d',
                'minio':     'cd /srv/docker/minio && docker compose up -d',
                'adminer':   'cd /srv/docker/adminer && docker compose up -d',
                'mailpit':   'cd /srv/docker/mailpit && docker compose up -d',
                'wikijs':    'cd /srv/docker/wikijs && docker compose up -d',
            }
            if name not in INSTALLABLE:
                self.send_json({'ok': False, 'error': f'Unknown service: {name}'}, 400)
                return
            result = ssh_run(INSTALLABLE[name], timeout=60)
            self.send_json({'ok': result.get('exitcode',1)==0, 'output': result.get('output',''), 'error': result.get('error','')})

        elif p == '/api/tunnel/start':
            if not gate_check(self.headers, required_level=2):
                self.send_json({'error': 'gate_required', 'layer': 2,
                                'message': 'Tunnel control requires TOTP verification'}, 403)
                return
            ok = tunnel_start()
            self.send_json({'ok': ok})

        elif p == '/api/tunnel/stop':
            if not gate_check(self.headers, required_level=2):
                self.send_json({'error': 'gate_required', 'layer': 2,
                                'message': 'Tunnel control requires TOTP verification'}, 403)
                return
            ok = tunnel_stop()
            self.send_json({'ok': ok})

        elif p == '/api/update':
            # git pull + restart hub service
            if not gate_check(self.headers, required_level=3):
                self.send_json({'error': 'gate_required', 'layer': 3,
                                'message': 'Hub update requires TOTP verification'}, 403)
                return
            hub_dir = os.path.expanduser('~/hub')
            lines = []
            pull = ssh_run(f'cd {hub_dir} && git pull origin master 2>&1', timeout=60)
            lines.append(pull.get('output', pull.get('error', '(no output)')))
            restart = ssh_run('systemctl --user restart hub 2>&1', timeout=15)
            lines.append(restart.get('output', '') or ('restarted' if restart.get('exitcode',1)==0 else restart.get('error','')))
            self.send_json({'ok': pull.get('exitcode',1)==0, 'output': '\n'.join(lines)})

        elif p == '/api/setup/generate-claude-md':
            # Write a filled-in CLAUDE.md to the hub directory on the server
            if not gate_check(self.headers, required_level=3):
                self.send_json({'error': 'gate_required', 'layer': 3,
                                'message': 'Generating CLAUDE.md requires TOTP verification'}, 403)
                return
            si = get_server_info()
            ts_ip = si.get('tailscale_ip','none')
            ts_name_r = ssh_run('tailscale status --self 2>/dev/null | head -1 | awk \'{print $2}\'')
            ts_name = ts_name_r.get('output','').strip() or 'unknown'
            home = si.get('home_dir', '/root')
            user = si.get('ssh_user', '')
            local_ip = si.get('local_ip','')
            claude_md = f"""# Claude Server — {si.get('hostname','Server')} Session
> This workspace connects directly to the home server via SSH.
> Claude can run commands on the server from this machine.

---

## Connection

| Key | Value |
|-----|-------|
| Server IP (local) | {local_ip} |
| Server IP (Tailscale) | {ts_ip if ts_ip != 'none' else 'not connected'} |
| SSH User | {user} |
| SSH Command (local) | `ssh {user}@{local_ip}` |
| SSH Command (remote) | `ssh {user}@{ts_ip}` |
| Tailscale name | {ts_name} |
| OS | {si.get('os','')} |
| CPU Cores | {si.get('cpu_cores','')} |

## Session Rules

- SSH commands run on the server — always prefix with `ssh {user}@{local_ip} "..."`
- Always confirm before restarting or stopping services
- AI stack should stay OFF unless user asks for it
"""
            dest = os.path.join(home, 'hub', 'CLAUDE.md')
            # Write via SSH echo to avoid escaping issues — use Python heredoc via ssh
            import tempfile, shlex
            tmp = f'/tmp/_hub_claudemd_{secrets.token_hex(6)}.md'
            # Write content to a temp file on the server using printf
            escaped = claude_md.replace("'", "'\\''")
            r1 = ssh_run(f"printf '%s' '{escaped}' > {tmp}", timeout=10)
            r2 = ssh_run(f'mv {tmp} {dest}', timeout=5)
            if r2.get('exitcode',1) == 0:
                self.send_json({'ok': True, 'path': dest})
            else:
                self.send_json({'ok': False, 'error': r2.get('error','Write failed')})

        elif p == '/api/users':
            action = body.get('action','')
            if action == 'add':
                username = body.get('username','').strip()
                password = body.get('password','')
                display = body.get('display', username)
                role = body.get('role', 'viewer')
                if not username or not password:
                    self.send_json({'ok': False, 'error': 'Username and password required'}, 400)
                    return
                h = hashlib.sha256(password.encode()).hexdigest()
                try:
                    conn = db_conn()
                    conn.execute("INSERT INTO users(username,display,password_hash,role,created) VALUES(?,?,?,?,?)",
                        (username, display, h, role, datetime.now().isoformat()))
                    conn.commit()
                    conn.close()
                    self.send_json({'ok': True})
                except Exception as e:
                    self.send_json({'ok': False, 'error': str(e)})
            elif action == 'delete':
                uid = body.get('id')
                try:
                    conn = db_conn()
                    conn.execute("DELETE FROM users WHERE id=? AND username != 'admin'", (uid,))
                    conn.commit()
                    conn.close()
                    self.send_json({'ok': True})
                except Exception as e:
                    self.send_json({'ok': False, 'error': str(e)})
            elif action == 'passwd':
                uid = body.get('id')
                pw = body.get('password','')
                if not pw:
                    self.send_json({'ok': False, 'error': 'Password required'}, 400)
                    return
                h = hashlib.sha256(pw.encode()).hexdigest()
                try:
                    conn = db_conn()
                    conn.execute("UPDATE users SET password_hash=? WHERE id=?", (h, uid))
                    conn.commit()
                    conn.close()
                    self.send_json({'ok': True})
                except Exception as e:
                    self.send_json({'ok': False, 'error': str(e)})
            else:
                self.send_json({'ok': False, 'error': 'Unknown action'}, 400)

        else:
            self.send_response(404)
            self.end_headers()


if __name__ == '__main__':
    db_ensure_tables()
    print(f'\n  Server Hub API  —  http://localhost:{PORT}')
    print(f'  SSH: {SSH_HOST}  |  DB: {DB_PATH}\n')
    class ThreadedServer(socketserver.ThreadingMixIn, http.server.HTTPServer):
        daemon_threads = True
    server = ThreadedServer(('0.0.0.0', PORT), Handler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print('\n  Hub stopped.')
