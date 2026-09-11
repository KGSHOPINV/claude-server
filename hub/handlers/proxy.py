#!/usr/bin/env python3
"""
# 20204009  handlers.proxy -- reverse proxy, docs, files endpoints
Hub handler module: proxy layer (module 09).
"""
import json
import os
import re
import ssl
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime

from kernel.db   import db_conn
from kernel.ssh  import ssh_run, LOCAL_MODE, SSH_HOST, SSH_USER, SERVER_IP
from kernel.auth import check_auth, gate_check

PORT       = int(os.environ.get('HUB_PORT', 8765))
_BASE_DIR  = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GUIDES_DIR = os.environ.get('HUB_GUIDES', os.path.join(_BASE_DIR, 'guides'))

HTTPS_PORTS = {9443, 9090}

_ssl_ctx = ssl.create_default_context()
_ssl_ctx.check_hostname = False
_ssl_ctx.verify_mode = ssl.CERT_NONE

# ── Proxy cache ───────────────────────────────────────────────────────────────
# HTML pages: 5s TTL (they change). JS/CSS/images: 60s TTL (static assets).

_proxy_cache = {}
_pcache_lock = threading.Lock()


# 20209301  _pcache_get — proxy cache read, 5s HTML / 60s asset TTL
def _pcache_get(key):
    with _pcache_lock:
        hit = _proxy_cache.get(key)
    if not hit:
        return None
    content, ct, status, ts = hit
    ttl = 5 if 'text/html' in ct else 60
    return (content, ct, status) if time.time() - ts < ttl else None


# 20209302  _pcache_put — proxy cache write, evict oldest when >400
def _pcache_put(key, content, ct, status):
    with _pcache_lock:
        if len(_proxy_cache) > 400:
            oldest = min(_proxy_cache, key=lambda k: _proxy_cache[k][3])
            del _proxy_cache[oldest]
        _proxy_cache[key] = (content, ct, status, time.time())


# 20209303  _rewrite_proxy_html — rewrite src/href/action attrs through proxy
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


# 20209304  _rewrite_proxy_css — rewrite url(/path) in CSS through proxy
def _rewrite_proxy_css(css, port):
    """Rewrite url(/path) references in CSS through proxy."""
    def _sub(m):
        path = m.group(1)
        skip = ('http://', 'https://', '//', 'data:', '#')
        return m.group(0) if any(path.startswith(s) for s in skip) else f'url("/proxy/{port}{path}")'
    return re.sub(r'url\(["\']?(/[^"\')\s]+)["\']?\)', _sub, css)


# 20209305  proxy_fetch — proxy HTTP/HTTPS request to local service
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


# ── Server info ───────────────────────────────────────────────────────────────

_server_info_cache = None


# 20201301  get_server_info — hostname/OS/IP/cores via SSH, cached process-lifetime
def get_server_info():
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
            'hostname':    parts[0].strip() if len(parts) > 0 else '',
            'os':          parts[1].strip() if len(parts) > 1 else '',
            'local_ip':    parts[2].strip() if len(parts) > 2 else '',
            'tailscale_ip': parts[3].strip() if len(parts) > 3 else 'none',
            'cpu_cores':   int(parts[4].strip()) if len(parts) > 4 and parts[4].strip().isdigit() else 0,
            'home_dir':    parts[5].strip() if len(parts) > 5 and parts[5].strip() else os.path.expanduser('~'),
            'ssh_user':    SSH_USER or (SSH_HOST.split('@')[0] if '@' in SSH_HOST else ''),
        }
    else:
        # Offline / local mode fallback
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


# 20209309  _get_files — ls -lah via SSH for file browser
def _get_files(path):
    safe = path.replace('..', '').replace('~', '').strip()
    if not safe.startswith('/'):
        safe = get_server_info().get('home_dir', os.path.expanduser('~'))
    r = ssh_run(f"ls -lah --time-style=short-iso '{safe}' 2>&1 | head -60")
    return {'path': safe, 'listing': r.get('output', ''), 'error': r.get('error', '') if not r.get('online') else ''}


# ── Doc helpers ───────────────────────────────────────────────────────────────

# Module-level status cache mirror. Populated by server.py background threads when
# this module is wired in; gracefully returns defaults when empty.
_cache = {'status': None, 'containers': None}


# 20209307  _substitute_guide_tokens — replace {{server.*}} tokens with live values
def _substitute_guide_tokens(text):
    """Replace {{server.*}} and {{hub.*}} template tokens with live values."""
    si = get_server_info()
    replacements = {
        '{{server.hostname}}':    si.get('hostname', ''),
        '{{server.local_ip}}':    si.get('local_ip', ''),
        '{{server.tailscale_ip}}': si.get('tailscale_ip', 'none'),
        '{{server.os}}':          si.get('os', ''),
        '{{server.home_dir}}':    si.get('home_dir', os.path.expanduser('~')),
        '{{server.ssh_user}}':    si.get('ssh_user', ''),
        '{{server.cpu_cores}}':   str(si.get('cpu_cores', '')),
        '{{hub.port}}':           str(PORT),
        '{{hub.host}}':           SSH_HOST,
    }
    for token, val in replacements.items():
        text = text.replace(token, val)
    return text


# 20209308  _build_this_server_doc — generate live Markdown from server state
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
{ts_section}---

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


# ── Route handlers ────────────────────────────────────────────────────────────

# 20309701  GET /proxy/{port}/{path} — reverse proxy to container (prefix match)
def get_proxy(handler, path, params):
    p = handler.path.split('?')[0]
    remainder = p[7:]  # strip leading '/proxy/'
    slash = remainder.find('/')
    if slash == -1:
        port_str, subpath = remainder, ''
    else:
        port_str, subpath = remainder[:slash], remainder[slash+1:]
    query = handler.path.split('?', 1)[1] if '?' in handler.path else ''
    try:
        port = int(port_str)
    except ValueError:
        handler.send_response(400)
        handler.end_headers()
        return
    content, ct, status = proxy_fetch(port, subpath, query)
    handler.send_response(status)
    handler.send_header('Content-Type', ct)
    handler.send_header('Content-Length', str(len(content)))
    # Explicitly NOT forwarding X-Frame-Options or CSP frame-ancestors
    handler.send_header('Access-Control-Allow-Origin', '*')
    handler.end_headers()
    handler.wfile.write(content)


# 20309702  GET /api/docs — list docs
def get_docs(handler, path, params):
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
        handler.send_json(files)
    except Exception:
        handler.send_json([])


# 20309703  GET /api/docs/content — get doc content
def get_docs_content(handler, path, params):
    fname = ''
    if '?' in handler.path:
        qs = handler.path.split('?', 1)[1]
        for part in qs.split('&'):
            if part.startswith('file='):
                fname = part[5:]
    if not fname or '/' in fname or '\\' in fname or not fname.endswith('.md'):
        handler.send_response(400)
        handler.end_headers()
        return
    # Special synthetic file: this-server.md — generated live from server_info
    if fname == 'this-server.md':
        content = _build_this_server_doc()
        handler.send_json({'content': content, 'file': fname})
        return
    fpath = os.path.join(GUIDES_DIR, fname)
    try:
        with open(fpath, 'r', encoding='utf-8') as fh:
            content = fh.read()
        # Template substitution: replace {{server.*}} and {{hub.*}} tokens with live values
        content = _substitute_guide_tokens(content)
        handler.send_json({'content': content, 'file': fname})
    except FileNotFoundError:
        handler.send_response(404)
        handler.end_headers()


# 20309704  GET /api/files — list files
def get_files(handler, path, params):
    fpath = get_server_info().get('home_dir', '/')
    if '?' in handler.path:
        for part in handler.path.split('?', 1)[1].split('&'):
            if part.startswith('path='):
                fpath = part[5:].replace('%2F', '/')
    handler.send_json(_get_files(fpath))
