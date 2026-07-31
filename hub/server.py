#!/usr/bin/env python3
"""
Hub local API server.
Run: python hub/server.py
Then open: http://localhost:8765
"""

import http.server
import json
import os
import sqlite3
import ssl
import subprocess
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime

PORT = 8765
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, '..', 'db', 'server.db')
APP_PATH = os.path.join(BASE_DIR, 'app.html')
GUIDES_DIR = os.path.join(BASE_DIR, '..', 'guides')

HTTPS_PORTS = {9443, 9090}  # ports that use HTTPS (self-signed certs)

# SSL context that skips cert verification for local self-signed certs
_ssl_ctx = ssl.create_default_context()
_ssl_ctx.check_hostname = False
_ssl_ctx.verify_mode = ssl.CERT_NONE
SSH_HOST = 'homeserver'
SERVER_IP = '192.168.1.229'

# ── Proxy ─────────────────────────────────────────────────────────────────────

def proxy_fetch(port, subpath, query=''):
    """Proxy a request to a local service, stripping X-Frame-Options."""
    scheme = 'https' if port in HTTPS_PORTS else 'http'
    url = f'{scheme}://{SERVER_IP}:{port}/{subpath}'
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

    # Inject <base> tag so relative URLs in the proxied page resolve correctly
    if status < 400 and 'text/html' in ct:
        base_url = f'{scheme}://{SERVER_IP}:{port}/'
        try:
            html = content.decode('utf-8', errors='replace')
            base_tag = f'<base href="{base_url}">'
            if '<head>' in html:
                html = html.replace('<head>', f'<head>\n  {base_tag}', 1)
            elif '<head ' in html.lower():
                idx = html.lower().index('<head')
                end = html.index('>', idx)
                html = html[:end+1] + f'\n  {base_tag}' + html[end+1:]
            else:
                html = f'<head>{base_tag}</head>' + html
            content = html.encode('utf-8')
        except Exception:
            pass

    return content, ct, status


# ── SSH ────────────────────────────────────────────────────────────────────────

def ssh_run(cmd, timeout=15):
    try:
        r = subprocess.run(
            ['ssh', SSH_HOST, cmd],
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
        '"$(cat /proc/loadavg | awk \'{print $1,$2,$3}\')"'
    )

    if not r['online']:
        data = {'online': False, 'error': r['error']}
    else:
        try:
            parts = r['output'].split('---')
            ram = parts[1].strip().split()
            disk = parts[2].strip().split()
            data = {
                'online': True,
                'uptime': parts[0].strip(),
                'ram_used_mb': int(ram[0]),
                'ram_total_mb': int(ram[1]),
                'disk_used': disk[0],
                'disk_total': disk[1],
                'disk_pct': disk[2],
                'containers': int(parts[3].strip()),
                'load': parts[4].strip(),
                'fetched_at': datetime.now().strftime('%H:%M:%S'),
            }
        except Exception as e:
            data = {'online': True, 'parse_error': str(e), 'raw': r['output']}

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
    {'name': 'n8n',         'port': 5678,  'group': 'Tools',          'description': 'Workflow automation',   'installed': False},
    {'name': 'Supabase',    'port': 8000,  'group': 'Tools',          'description': 'Database platform',     'installed': False},
    {'name': 'Redis',       'port': 6379,  'group': 'Tools',          'description': 'Cache / key-value',     'installed': False, 'no_ui': True},
    {'name': 'MinIO',       'port': 9001,  'group': 'Tools',          'description': 'Object storage (S3)',   'installed': False},
    {'name': 'Adminer',     'port': 8082,  'group': 'Tools',          'description': 'Database browser',      'installed': False},
    {'name': 'Mailpit',     'port': 8025,  'group': 'Tools',          'description': 'Dev email catcher',     'installed': False},
    {'name': 'Wiki.js',     'port': 3002,  'group': 'Tools',          'description': 'Knowledge base',        'installed': False},
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
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.end_headers()

    def get_body(self):
        n = int(self.headers.get('Content-Length', 0))
        return json.loads(self.rfile.read(n)) if n else {}

    def do_GET(self):
        p = self.path.split('?')[0]
        force = 'force' in self.path

        if p == '/':
            try:
                with open(APP_PATH, 'rb') as f:
                    content = f.read()
                self.send_response(200)
                self.send_header('Content-Type', 'text/html; charset=utf-8')
                self.send_header('Content-Length', str(len(content)))
                self.end_headers()
                self.wfile.write(content)
            except FileNotFoundError:
                self.send_response(404)
                self.end_headers()

        elif p == '/api/status':
            self.send_json(get_status(force=force))

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
            fpath = os.path.join(GUIDES_DIR, fname)
            try:
                with open(fpath, 'r', encoding='utf-8') as fh:
                    content = fh.read()
                self.send_json({'content': content, 'file': fname})
            except FileNotFoundError:
                self.send_response(404); self.end_headers()

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
            result = ssh_run(cmd, timeout=30)
            self.send_json(result)

        elif p == '/api/vault':
            blob = body.get('blob')
            if blob is None:
                self.send_json({'ok': False, 'error': 'No blob'}, 400)
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

        else:
            self.send_response(404)
            self.end_headers()


if __name__ == '__main__':
    print(f'\n  Server Hub API  —  http://localhost:{PORT}')
    print(f'  SSH: {SSH_HOST}  |  DB: {DB_PATH}\n')
    server = http.server.HTTPServer(('localhost', PORT), Handler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print('\n  Hub stopped.')
