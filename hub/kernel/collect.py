#!/usr/bin/env python3
"""
# 20200009  kernel.collect — system-state collectors.

Everything that gathers state about the machine: Docker, ports, storage,
services, receipts, manifests, proxy fetch, tunnel control.

Handlers import from here. Previously these lived in server.py and handlers
reached back into them via `import server as _srv`, which made server.py a
dependency of its own handlers. This module breaks that cycle.
"""
import base64
import hmac
import http.server
import re
import socketserver
import json
import os
import secrets
import shutil
import sqlite3
import struct
import subprocess
import threading
import time
import urllib.parse
from datetime import datetime

# ── Kernel imports ────────────────────────────────────────────────────────────
from kernel.db   import db_conn, db_ensure_tables, DB_PATH
from kernel.ssh  import ssh_run, LOCAL_MODE, SSH_HOST, SSH_USER, SERVER_IP
from kernel.log  import log_activity, activity_recent, _ntfy_send, _docker_event_loop
from kernel.auth import (
    check_auth, gate_check, gate_create,
    _totp_hotp, totp_verify, totp_new_secret, totp_verify_secret, totp_uri,
    _sessions, _users_lock, _gate_sessions, _gate_lock,
)


PORT      = int(os.environ.get('HUB_PORT', 8765))
BASE_DIR  = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APP_PATH    = os.path.join(BASE_DIR, 'app.html')
MOBILE_PATH = os.path.join(BASE_DIR, 'mobile.html')
GUIDES_DIR= os.environ.get('HUB_GUIDES', os.path.join(BASE_DIR, 'guides'))

HTTPS_PORTS = {9443, 9090}

# ── Project port space ───────────────────────────────────────────────────────
# The one place the project band is defined. /api/admit hands these out and the
# node receipt advertises what is free inside them, so a project is never told
# two different things about where it may bind.
#
# 7100-7899 because it is the only wide stretch no PORT_LANE claims. It must
# stay that way: anything above 10000 collides with the Supabase stack lane.
# Moved off 7100-7899 (800 ports, 16 projects) on 2026-09-24. 12000-18999 is
# 7000 unclaimed ports -- nothing between the Supabase lane and Monitoring --
# which is 70 projects at 100 each with room to widen rather than shrink.
#
# MIGRATION, not a cutover. Existing projects keep their ports until they choose
# to move; only new ones are held to this. fksinv sits at 10100/10101 and
# babyhelp at 12080, and neither is urgent.
PROJECT_BAND_FLOOR = 12000
PROJECT_BAND_CEIL  = 18999
# 100 per project. The band has to hold everything a project will ever publish,
# because the alternative is what fksinv and babyhelp already are: ports picked
# one at a time from whatever was free that day, leaving a project scattered
# with no way to see where it starts or ends.
#
# 100 also makes the OFFSET meaningful. Within a band the last two digits can
# carry the role, so a port number tells you what kind of thing it is without
# looking anything up:
#
#     x00-x19   UI / frontend
#     x20-x39   API / services
#     x40-x59   data -- db, cache, search
#     x60-x79   workers, jobs, queues
#     x80-x99   dev, preview, debug, temporary
#
# Suggested, never enforced. The band is the boundary; the split inside it
# belongs to the project, which knows its own shape better than the hub does.
# Outgrowing 100 is a ticket, not a violation.
PROJECT_BAND_SIZE  = 100

DOCKER_ROOT = os.environ.get('HUB_DOCKER_ROOT', '/srv/docker')

# ── Proxy ─────────────────────────────────────────────────────────────────────
# REMOVED (dead): _pcache_get, _pcache_put, _rewrite_proxy_html, _rewrite_proxy_css,
# proxy_fetch, plus the _proxy_cache / _pcache_lock / _ssl_ctx state they owned.
# handlers/proxy.py carries its own copies under the same telescope codes and is
# what the /proxy/* routes dispatch to; nothing ever called the copies here.

# ── SSH ────────────────────────────────────────────────────────────────────────
# KERNEL: ssh_run moved to kernel/ssh.py

# ── Status cache ───────────────────────────────────────────────────────────────

_cache = {'status': None, 'ts': 0, 'containers': None, 'containers_ts': 0}
_lock = threading.Lock()
_server_info_cache = None   # cached once per process restart

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

# 20202301  get_status — uptime/RAM/disk/containers/load, 60s SSH cache
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
        # Unattached raw disks — disk with NO mounted partitions/children at all
        # Uses full tree check (-r = raw, includes children) so LVM, RAID, and partitioned
        # OS disks are never falsely flagged as unattached.
        '"$(for d in $(lsblk -dn -o NAME,TYPE 2>/dev/null | awk \'$2=="disk" && !/loop/{print $1}\'); do '
        'mnt=$(lsblk -rno MOUNTPOINT /dev/$d 2>/dev/null | grep -cv \'^$\' || echo 0); '
        'size=$(lsblk -dn -o SIZE /dev/$d 2>/dev/null); '
        '[ "$mnt" -eq 0 ] && echo "${d}|${size}"; done)"'
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
            # Cross-check: skip disks whose partitions are already mounted (e.g. /dev/sdb1 at /backup)
            mounted_devs = {d['device'] for d in disks}
            unattached = []
            for entry in (parts[6].strip().split(';') if len(parts) > 6 else []):
                p = entry.strip().split('|')
                if len(p) >= 2 and p[0]:
                    name = p[0]
                    has_mounted_part = any(dev.startswith(f'/dev/{name}') for dev in mounted_devs)
                    if not has_mounted_part:
                        unattached.append({'name': name, 'size': p[1]})

            data = {
                'online': True,
                'uptime': parts[0].strip(),
                'ram_used_mb': int(ram[0]),
                'ram_total_mb': int(ram[1]),
                # Root FS only. Kept under these names for backward compat with
                # the header stat -- but on a machine with a second disk they
                # describe one filesystem, not the machine. ksgcohub reported
                # "98G" for months while carrying 556G, because nothing added
                # up the mounts. The machine-wide figures are below.
                'disk_used': disk[0],
                'disk_total': disk[1],
                'disk_pct': disk[2],
                'containers': int(parts[3].strip()),
                'load': parts[4].strip(),
                'fetched_at': datetime.now().strftime('%H:%M:%S'),
                'disks': disks,
                'unattached_drives': unattached,
            }
            # Machine-wide storage, summed across REAL filesystems only.
            # /api/storage was listing tmpfs, /run and /dev/shm alongside real
            # disks, so even the detailed view could not be totalled honestly.
            try:
                from kernel import storage as _st
                ms = _st.landscape()['mounts']
                data['storage_total_gb'] = round(sum(m['size_gb'] for m in ms), 1)
                data['storage_used_gb']  = round(sum(m['used_gb'] for m in ms), 1)
                data['storage_avail_gb'] = round(sum(m['avail_gb'] for m in ms), 1)
                data['storage_pct'] = (round(100 * data['storage_used_gb']
                                             / data['storage_total_gb'])
                                       if data['storage_total_gb'] else 0)
                data['storage_mounts'] = ms
            except Exception:
                pass   # a missing total is better than a wrong one
        except Exception as e:
            data = {'online': True, 'parse_error': str(e), 'raw': r['output']}

    if data.get('online'):
        # Read system power draw from ACPI power meter (microwatts → watts)
        try:
            import glob as _glob
            _pw = 0
            for _nf in _glob.glob('/sys/class/hwmon/hwmon*/name'):
                if open(_nf).read().strip() == 'power_meter':
                    _avg = _nf.replace('/name', '/power1_average')
                    _pw = round(int(open(_avg).read().strip()) / 1_000_000)
                    break
            data['power_watts'] = _pw
        except Exception:
            data['power_watts'] = 0
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

# 20202302  get_containers — docker ps -a parsed, 30s cache
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

# 20202303  build_services — enrich SERVICES list with live Docker state
def build_services(server_info=None):
    """Build service list: known services enriched with live Docker state,
    plus auto-discovered containers not in the known list."""
    si = server_info or get_server_info()
    ip = si.get('local_ip') or SERVER_IP or 'localhost'

    # Use cached containers (get_containers has a 30s cache + ssh_run)
    containers = get_containers()

    # Build running map: container_name → {ports, status, image}
    running = {}
    for c in containers:
        if not c.get('running'):
            continue
        name = c['name']
        ports_str = c.get('ports', '')
        host_ports = []
        for m in re.finditer(r'(?:0\.0\.0\.0|\[::\]):(\d+)->', ports_str):
            try:
                host_ports.append(int(m.group(1)))
            except ValueError:
                pass
        running[name] = {
            'ports': host_ports,
            'status': c.get('status', ''),
            'image': c.get('image', ''),
        }

    services = []
    seen_containers = set()

    # First pass: known services — enrich with live running state
    for s in SERVICES:
        name = s.get('name', '')
        port = s.get('port')

        # Heuristic match by container field or name variants
        matched_container = None
        explicit = s.get('container', '')
        if explicit and explicit in running:
            matched_container = explicit
        else:
            n = name.lower().replace(' ', '-').replace('.', '')
            for cname in running:
                if cname.lower() in (n, name.lower()):
                    matched_container = cname
                    break

        if matched_container:
            seen_containers.add(matched_container)

        is_running = matched_container is not None
        actual_ports = running[matched_container]['ports'] if matched_container else []
        display_port = actual_ports[0] if actual_ports else port
        scheme = 'https' if s.get('https') or port in HTTPS_PORTS else 'http'

        svc = dict(s)
        svc['running'] = is_running
        svc['actual_ports'] = actual_ports
        svc['url'] = (f"{scheme}://{ip}:{display_port}" if display_port else '') if not s.get('no_ui') else None
        services.append(svc)

    # Second pass: auto-discovered containers NOT in the known list
    for cname, info in running.items():
        if cname in seen_containers:
            continue
        if not info['ports']:
            continue  # skip containers with no exposed ports

        port = info['ports'][0]
        services.append({
            'name': cname,
            'label': cname,
            'description': f"Auto-discovered — {info['image']}",
            'port': port,
            'actual_ports': info['ports'],
            'url': f"http://{ip}:{port}",
            'running': True,
            'installed': True,
            'group': 'Discovered',
            'discovered': True,
        })

    return services

# ── Port lanes ─────────────────────────────────────────────────────────────────

PORT_LANES = [
    {'name': 'Hub',            'color': 'accent',  'ranges': [(8765, 8765)]},
    {'name': 'System',         'color': 'muted',   'ranges': [(1, 1023)]},
    {'name': 'Infrastructure', 'color': 'blue',    'ranges': [(3000, 3099), (80, 81), (443, 443)]},
    {'name': 'Monitoring',     'color': 'teal',    'ranges': [(19000, 19999), (8090, 8090)]},
    {'name': 'Automation',     'color': 'green',   'ranges': [(5600, 5699)]},
    {'name': 'Database',       'color': 'yellow',  'ranges': [(5400, 5499), (6300, 6399), (6379, 6379)]},
    {'name': 'Admin',          'color': 'muted',   'ranges': [(9090, 9090), (9400, 9499), (9443, 9443)]},
    {'name': 'Storage',        'color': 'yellow',  'ranges': [(9000, 9089), (9091, 9099)]},
    {'name': 'AI',             'color': 'purple',  'ranges': [(11000, 11999)]},
    {'name': 'Tools',          'color': 'blue',    'ranges': [(8000, 8999)]},
    {'name': 'Supabase Stack', 'color': 'teal',    'ranges': [(10000, 10999)]},
    {'name': 'Projects',       'color': 'green',   'ranges': [(12000, 18999)]},
]

# Flat port → service name registry for quick lookup
_PORT_NAMES = {}
for _s in SERVICES:
    _PORT_NAMES[_s['port']] = _s['name']
_PORT_NAMES[22]   = 'SSH'
_PORT_NAMES[80]   = 'HTTP (NPM)'
_PORT_NAMES[443]  = 'HTTPS (NPM)'
_PORT_NAMES[8765] = 'Hub'
_PORT_NAMES[8085] = 'ntfy'
_PORT_NAMES[5678] = 'n8n'
_PORT_NAMES[7003] = 'Redis (server)'

# 20202304  _port_lane — map port number to lane name
def _port_lane(port):
    """Return the lane name for a port number."""
    for lane in PORT_LANES:
        for lo, hi in lane['ranges']:
            if lo <= port <= hi:
                return lane['name']
    return 'Other'

# 20209306  build_cutsheet_html — generate self-contained port cutsheet HTML
def build_cutsheet_html(ports, services, server_info):
    """Generate a live port cut-sheet as a self-contained HTML page."""
    from datetime import datetime as _dt

    # Lane colour map: server.py color name → CSS hex
    LANE_HEX = {
        'accent': '#58a6ff', 'blue': '#3b82f6', 'teal': '#14b8a6',
        'green':  '#22c55e', 'yellow': '#eab308', 'purple': '#a855f7',
        'muted':  '#6b7280', 'red':    '#ef4444',
    }

    # Build lane → colour lookup
    lane_color = {l['name']: LANE_HEX.get(l['color'], '#6b7280') for l in PORT_LANES}
    lane_color['Other'] = '#9ca3af'

    # Group ports by lane
    by_lane = {}
    for p in ports:
        ln = p.get('lane', 'Other')
        by_lane.setdefault(ln, []).append(p)

    # Ordered lanes (only those with ports, plus any from PORT_LANES that have ports)
    lane_order = [l['name'] for l in PORT_LANES] + ['Other']
    lane_order = [l for l in lane_order if l in by_lane]

    # Service lookup: port → {name, desc, running}
    svc_map = {s['port']: s for s in services}

    ts    = _dt.now().strftime('%Y-%m-%d %H:%M')
    ip    = server_info.get('local_ip', SERVER_IP)
    ts_ip = server_info.get('tailscale_ip', '—')
    os_   = server_info.get('os', 'Linux')
    ram   = server_info.get('ram_total_gb', '?')

    def flag(port_entry):
        parts = []
        if port_entry.get('local_only'):
            parts.append('<span class="flag f-local">local</span>')
        else:
            parts.append('<span class="flag f-pub">pub</span>')
        if port_entry.get('https'):
            parts.append('<span class="flag f-https">https</span>')
        svc = svc_map.get(port_entry['port'])
        if svc and not svc.get('running', True):
            parts.append('<span class="flag f-off">off</span>')
        return ''.join(parts)

    def lane_rows(lane_name):
        rows_html = []
        for p in sorted(by_lane.get(lane_name, []), key=lambda x: x['port']):
            svc  = svc_map.get(p['port'], {})
            name = p.get('service') or svc.get('name') or '—'
            desc = svc.get('description') or p.get('process', '')
            rows_html.append(f"""
      <div class="port-row">
        <span class="pnum">{p['port']}</span>
        <div class="pinfo">
          <span class="pname">{name}</span>
          <span class="pdesc">{desc}</span>
        </div>
        <div class="pflags">{flag(p)}</div>
      </div>""")
        return ''.join(rows_html)

    def lane_range_str(lane_name):
        for l in PORT_LANES:
            if l['name'] == lane_name:
                return ', '.join(f"{lo}–{hi}" if lo != hi else str(lo) for lo, hi in l['ranges'])
        return ''

    lane_sections = ''
    for ln in lane_order:
        color = lane_color.get(ln, '#9ca3af')
        rng   = lane_range_str(ln)
        lane_sections += f"""
  <div class="lane">
    <div class="lane-hdr">
      <div class="lane-stripe" style="background:{color}"></div>
      <span class="lane-name">{ln}</span>
      <span class="lane-range">{rng}</span>
    </div>
    {lane_rows(ln)}
  </div>"""

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Port Cut Sheet — {server_info.get('hostname', 'server')}</title>
<style>
:root{{
  --paper:#fff;--ink:#111827;--ink2:#374151;--dim:#6b7280;
  --faint:#f3f4f6;--rule:#e5e7eb;
  --mono:'SF Mono','Cascadia Code',ui-monospace,monospace;
  --sans:-apple-system,BlinkMacSystemFont,'Segoe UI',system-ui,sans-serif;
}}
@media(prefers-color-scheme:dark){{
  :root{{--paper:#0d1117;--ink:#f0f6fc;--ink2:#c9d1d9;--dim:#8b949e;--faint:#161b22;--rule:#30363d}}
}}
*,*::before,*::after{{box-sizing:border-box;margin:0;padding:0}}
body{{background:var(--paper);color:var(--ink);font-family:var(--sans);font-size:12px;line-height:1.4;padding:20px 24px;max-width:980px;margin:0 auto}}
/* header */
.hdr{{display:flex;align-items:flex-start;justify-content:space-between;padding-bottom:12px;margin-bottom:14px;border-bottom:2px solid var(--ink);flex-wrap:wrap;gap:8px}}
.hdr-eye{{font-size:9px;font-weight:700;letter-spacing:1px;text-transform:uppercase;color:var(--dim)}}
.hdr-title{{font-size:20px;font-weight:800;letter-spacing:-.5px;margin:2px 0}}
.hdr-sub{{font-size:10px;color:var(--dim);font-family:var(--mono);margin-top:2px}}
.hdr-right{{display:flex;flex-direction:column;align-items:flex-end;gap:4px}}
.badge{{font-size:9px;font-weight:700;letter-spacing:.5px;text-transform:uppercase;padding:2px 7px;border-radius:3px;background:var(--faint);color:var(--dim);border:1px solid var(--rule)}}
.ts{{font-size:10px;color:var(--dim);font-family:var(--mono)}}
/* legend */
.legend{{display:flex;flex-wrap:wrap;gap:5px 12px;padding:7px 10px;background:var(--faint);border:1px solid var(--rule);border-radius:5px;margin-bottom:14px;font-size:10px;color:var(--dim);align-items:center}}
/* grid */
.grid{{display:grid;grid-template-columns:1fr 1fr;gap:10px}}
@media(max-width:620px){{.grid{{grid-template-columns:1fr}}}}
/* lane */
.lane{{border:1px solid var(--rule);border-radius:6px;overflow:hidden}}
.lane-hdr{{display:flex;align-items:center;gap:7px;padding:6px 10px;background:var(--faint);border-bottom:1px solid var(--rule)}}
.lane-stripe{{width:4px;height:14px;border-radius:2px;flex-shrink:0}}
.lane-name{{font-size:9px;font-weight:800;letter-spacing:.6px;text-transform:uppercase;color:var(--ink2)}}
.lane-range{{font-size:9px;color:var(--dim);font-family:var(--mono);margin-left:auto}}
/* port rows */
.port-row{{display:grid;grid-template-columns:52px 1fr auto;align-items:center;gap:7px;padding:5px 10px;border-bottom:1px solid var(--rule)}}
.port-row:last-child{{border-bottom:none}}
.pnum{{font-family:var(--mono);font-size:12px;font-weight:700;font-variant-numeric:tabular-nums}}
.pinfo{{display:flex;flex-direction:column;gap:1px;min-width:0}}
.pname{{font-size:11px;font-weight:600;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}}
.pdesc{{font-size:9px;color:var(--dim);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}}
.pflags{{display:flex;gap:3px;flex-shrink:0}}
.flag{{font-size:8px;font-weight:700;letter-spacing:.3px;padding:1px 4px;border-radius:2px;text-transform:uppercase}}
.f-local{{background:var(--faint);color:var(--dim);border:1px solid var(--rule)}}
.f-pub{{background:#dcfce7;color:#166534;border:1px solid #bbf7d0}}
.f-https{{background:#fef3c7;color:#92400e;border:1px solid #fde68a}}
.f-off{{background:var(--faint);color:var(--dim);opacity:.5;border:1px solid var(--rule)}}
@media(prefers-color-scheme:dark){{
  .f-pub{{background:#14532d;color:#86efac;border-color:#166534}}
  .f-https{{background:#451a03;color:#fcd34d;border-color:#78350f}}
}}
/* quick ref strip */
.qref{{display:flex;flex-wrap:wrap;gap:4px 20px;padding:8px 10px;background:var(--faint);border:1px solid var(--rule);border-radius:5px;margin-top:10px;font-size:10px;color:var(--dim)}}
.qref strong{{color:var(--ink)}}
/* footer */
.foot{{margin-top:10px;padding-top:8px;border-top:1px solid var(--rule);display:flex;justify-content:space-between;flex-wrap:wrap;gap:4px;font-size:9px;color:var(--dim)}}
@media print{{
  body{{padding:10px 14px}}
  .port-row:hover{{background:none}}
  .f-pub{{background:#e6f4ea;color:#1a4731;border-color:#c3e6cb}}
  .f-https{{background:#fff8e1;color:#6d4c00;border-color:#ffe082}}
}}
</style>
</head>
<body>

<div class="hdr">
  <div>
    <div class="hdr-eye">Port Reference — {server_info.get('hostname', 'server')}</div>
    <div class="hdr-title">Port Cut Sheet</div>
    <div class="hdr-sub">{ip} &nbsp;·&nbsp; Tailscale {ts_ip} &nbsp;·&nbsp; {os_}</div>
  </div>
  <div class="hdr-right">
    <span class="badge">{ram} GB RAM</span>
    <span class="badge">{len(ports)} ports active</span>
    <span class="ts">Generated {ts}</span>
  </div>
</div>

<div class="legend">
  <strong>Flags:</strong>
  <span class="flag f-pub">pub</span> LAN accessible &nbsp;
  <span class="flag f-local">local</span> localhost only &nbsp;
  <span class="flag f-https">https</span> TLS required &nbsp;
  <span class="flag f-off">off</span> installed, stopped
</div>

<div class="grid">
{lane_sections}
</div>

<div class="qref">
  <span><strong>Hub</strong> · http://{ip}:7000</span>
  <span><strong>NPM</strong> · http://{ip}:81</span>
  <span><strong>Portainer</strong> · https://{ip}:9443</span>
  <span><strong>Cockpit</strong> · https://{ip}:9090</span>
  <span><strong>Netdata</strong> · http://{ip}:19999</span>
  <span><strong>SSH</strong> · {server_info.get('ssh_user', 'admin')}@{ip}</span>
</div>

<div class="foot">
  <span>{server_info.get('hostname', 'server')} · {os_} · {ram} GB RAM · Docker stack · Watchtower auto-update</span>
  <span>http://{ip}:7000/cutsheet &nbsp;·&nbsp; {ts}</span>
</div>

</body>
</html>"""


# 20202305  scan_ports — ss -tlnp4 + docker ps → enriched port list
def scan_ports():
    """Scan all listening TCP ports. Returns (ports_list, docker_port_map)."""
    # Get all listening TCP ports with process info
    r = ssh_run("ss -tlnp4 2>/dev/null | tail -n +2", timeout=10)
    ports = []
    seen = set()
    for line in r.get('output', '').splitlines():
        parts = line.split()
        if len(parts) < 4:
            continue
        addr_port = parts[3]
        process_info = parts[5] if len(parts) > 5 else ''
        if ':' not in addr_port:
            continue
        addr, port_str = addr_port.rsplit(':', 1)
        try:
            port = int(port_str)
        except ValueError:
            continue
        if port in seen:
            continue
        seen.add(port)
        proc, pid = '', None
        m = re.search(r'\("([^"]+)",pid=(\d+)', process_info)
        if m:
            proc = m.group(1)
            try:
                pid = int(m.group(2))
            except ValueError:
                pass
        # Filter out loopback-only listeners (127.x.x.x) for cleaner display
        is_local = addr.startswith('127.') or addr == '::1'
        ports.append({
            'port':     port,
            'addr':     addr,
            'process':  proc,
            'pid':      pid,
            'local_only': is_local,
        })

    # Get Docker container → ports mapping
    r2 = ssh_run("docker ps --format '{{.Names}}|{{.Ports}}' 2>/dev/null", timeout=10)
    docker_ports = {}  # port_num -> container_name
    for line in r2.get('output', '').splitlines():
        if '|' not in line:
            continue
        cname, ports_str = line.split('|', 1)
        for m in re.finditer(r'(?:0\.0\.0\.0|\[::\]):(\d+)->', ports_str):
            try:
                docker_ports[int(m.group(1))] = cname
            except ValueError:
                pass

    # Enrich: add container name + service name + lane
    for p in ports:
        pn = p['port']
        p['container'] = docker_ports.get(pn, '')
        # Process name heuristic for hub itself
        if pn == PORT and p['process'] in ('python3', 'python', ''):
            p['container'] = 'server-hub'
        p['service']   = _PORT_NAMES.get(pn, p['container'] if p['container'] else '')
        p['lane']      = _port_lane(pn)

    ports.sort(key=lambda x: x['port'])
    return ports, docker_ports

# ── Port background scanner ────────────────────────────────────────────────────

_port_cache       = {'ports': [], 'events': [], 'ts': ''}
_port_cache_lock  = threading.Lock()

# 20202306  _do_port_snapshot — scan ports, diff, write port_snapshots/port_events
def _do_port_snapshot():
    """Scan ports, detect changes, persist to DB."""
    ports, _ = scan_ports()
    now = datetime.now().isoformat()
    with _port_cache_lock:
        _port_cache['ports'] = ports
        _port_cache['ts'] = now

    conn = db_conn()
    prev_row = conn.execute("SELECT data FROM port_snapshots ORDER BY id DESC LIMIT 1").fetchone()
    prev_set = set()
    if prev_row:
        try:
            prev_set = {p['port'] for p in json.loads(prev_row['data'])}
        except Exception:
            pass

    curr_set = {p['port'] for p in ports if not p.get('local_only')}

    if prev_row:
        for port in sorted(curr_set - prev_set):
            p = next((x for x in ports if x['port'] == port), {})
            conn.execute(
                "INSERT INTO port_events(ts,event,port,process,container) VALUES(?,?,?,?,?)",
                (now, 'appeared', port, p.get('process',''), p.get('container',''))
            )
        for port in sorted(prev_set - curr_set):
            conn.execute(
                "INSERT INTO port_events(ts,event,port,process,container) VALUES(?,?,?,?,?)",
                (now, 'disappeared', port, '', '')
            )

    conn.execute("INSERT INTO port_snapshots(ts,data) VALUES(?,?)", (now, json.dumps(ports)))
    # Keep 96 snapshots (8h at 5min intervals)
    conn.execute("DELETE FROM port_snapshots WHERE id NOT IN (SELECT id FROM port_snapshots ORDER BY id DESC LIMIT 96)")
    conn.commit()

    # Cache recent events
    rows = conn.execute(
        "SELECT * FROM port_events WHERE acknowledged=0 ORDER BY id DESC LIMIT 50"
    ).fetchall()
    conn.close()
    with _port_cache_lock:
        _port_cache['events'] = [dict(r) for r in rows]

# 20202307  _port_scan_loop — background daemon: scan every 5 minutes
def _port_scan_loop():
    time.sleep(10)  # Give hub a moment to fully start up before first scan
    while True:
        try:
            _do_port_snapshot()
        except Exception:
            pass
        time.sleep(300)  # Scan every 5 minutes

# ── SQLite helpers ─────────────────────────────────────────────────────────────
# KERNEL: db_conn moved to kernel/db.py

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
        {'id': '04', 'label': 'Cloudflare Tunnel',  'done': cmd_ok('docker ps --filter name=server-hub-tunnel --format "{{.Names}}" | grep -q server-hub-tunnel')},
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

# REMOVED (dead): vault_get, vault_put, issues_get. handlers/config.py answers
# /api/vault and /api/issues with its own inline queries; these had no caller.

# KERNEL: db_ensure_tables moved to kernel/db.py

# ── Activity Logger ───────────────────────────────────────────────────────────
# KERNEL: log_activity, activity_recent, _ntfy_send, _docker_event_loop moved to kernel/log.py

# ── Server Receipt ────────────────────────────────────────────────────────────

# 20202317  build_receipt — full server snapshot via local subprocess
def build_receipt():
    """Full server snapshot — universal, degrades gracefully."""
    import platform, shutil
    now = datetime.now().isoformat(timespec='seconds')

    # Hostname + IPs
    hostname = 'unknown'
    try: hostname = subprocess.check_output(['hostname'], text=True).strip()
    except Exception: pass

    lan_ip = ''
    try:
        out = subprocess.check_output(['ip','route','get','1.1.1.1'], text=True, stderr=subprocess.DEVNULL)
        toks = out.split()
        if 'src' in toks:
            lan_ip = toks[toks.index('src') + 1]
    except Exception: pass
    if not lan_ip:
        try: lan_ip = subprocess.check_output(['hostname','-I'], text=True).strip().split()[0]
        except Exception: pass

    ts_ip = ''
    try:
        if shutil.which('tailscale'):
            ts_ip = subprocess.check_output(['tailscale','ip'], text=True, stderr=subprocess.DEVNULL).strip().split()[0]
    except Exception: pass

    # OS
    os_info = platform.system() + ' ' + platform.release()
    try:
        with open('/etc/os-release') as f:
            for line in f:
                if line.startswith('PRETTY_NAME='):
                    os_info = line.split('=',1)[1].strip().strip('"'); break
    except Exception: pass

    # Uptime
    uptime_str = ''
    try:
        with open('/proc/uptime') as f:
            secs = int(float(f.read().split()[0]))
        d, secs = divmod(secs, 86400)
        h, secs = divmod(secs, 3600)
        m = secs // 60
        parts = []
        if d: parts.append(f'{d}d')
        if h: parts.append(f'{h}h')
        parts.append(f'{m}m')
        uptime_str = ' '.join(parts)
    except Exception: pass

    # RAM
    ram_total, ram_used = '', ''
    try:
        with open('/proc/meminfo') as f:
            lines = f.read().splitlines()
        total = next(int(l.split()[1]) for l in lines if l.startswith('MemTotal:'))
        avail = next(int(l.split()[1]) for l in lines if l.startswith('MemAvailable:'))
        ram_total = f'{total//1048576}G'
        ram_used  = f'{(total-avail)//1048576}G'
    except Exception: pass

    # Disk
    disks = []
    try:
        out = subprocess.check_output(['df','-h','--output=target,size,used,pcent'],
            text=True, stderr=subprocess.DEVNULL).splitlines()[1:]
        for line in out:
            parts = line.split()
            if len(parts)==4 and not any(x in parts[0] for x in ['docker','overlay','tmpfs','udev','loop']):
                disks.append({'mount':parts[0],'size':parts[1],'used':parts[2],'pct':parts[3]})
    except Exception: pass

    # Containers
    containers = []
    try:
        out = subprocess.check_output(
            ['docker','ps','--format','{{.Names}}\t{{.Status}}\t{{.Ports}}'],
            text=True, stderr=subprocess.DEVNULL)
        for line in out.strip().splitlines():
            parts = line.split('\t')
            containers.append({'name':parts[0],'status':parts[1],'ports':parts[2] if len(parts)>2 else ''})
    except Exception: pass

    # Sync status — services expected but not running
    sync_issues = []
    running_names = {c['name'].lower() for c in containers}
    for svc in SERVICES:
        if svc.get('installed') and not svc.get('no_ui'):
            nm = svc['name'].lower()
            if nm not in running_names and not any(nm in r for r in running_names):
                sync_issues.append({'service': svc['name'], 'port': svc['port'], 'issue': 'not running'})

    # Recent activity
    recent = activity_recent(db_conn, 20)

    return {
        'generated': now,
        'hostname':  hostname,
        'lan_ip':    lan_ip,
        'tailscale': ts_ip,
        'os':        os_info,
        'uptime':    uptime_str,
        'ram':       {'total': ram_total, 'used': ram_used},
        'disks':     disks,
        'containers': containers,
        'container_count': len(containers),
        'sync_issues': sync_issues,
        'recent_activity': recent,
        'hub_port': PORT,
        'hub_url':  f'http://{lan_ip}:{PORT}',
    }


# 20202318  build_context — HANDOFF_SERVERHUB context payload for AI
def build_context():
    """Server context payload — per Metaforge HANDOFF_SERVERHUB spec.
    Sent to FlareVault at pairing; refresh every 60s or on significant change."""
    receipt = build_receipt()

    # RAM in MB from /proc/meminfo
    ram_total_mb = 0
    ram_available_mb = 0
    try:
        with open("/proc/meminfo") as f:
            lines = f.read().splitlines()
        ram_total_mb     = next(int(l.split()[1]) // 1024 for l in lines if l.startswith("MemTotal:"))
        ram_available_mb = next(int(l.split()[1]) // 1024 for l in lines if l.startswith("MemAvailable:"))
    except Exception:
        pass

    # Disk — root FS total/available in GB
    disk_total_gb = 0
    disk_available_gb = 0
    try:
        out = subprocess.check_output(
            ["df", "-BG", "--output=size,avail", "/"],
            text=True, stderr=subprocess.DEVNULL).splitlines()
        if len(out) > 1:
            parts = out[1].split()
            disk_total_gb     = int(parts[0].rstrip("G"))
            disk_available_gb = int(parts[1].rstrip("G"))
    except Exception:
        pass

    # Docker version
    docker_version = "unknown"
    try:
        docker_version = subprocess.check_output(
            ["docker", "version", "--format", "{{.Server.Version}}"],
            text=True, stderr=subprocess.DEVNULL).strip() or "unknown"
    except Exception:
        pass

    # CPU cores
    cpu_cores = 0
    try:
        cpu_cores = int(subprocess.check_output(["nproc"], text=True).strip())
    except Exception:
        pass

    # Running containers in spec shape
    running_containers = [
        {"name": c["name"], "image": c.get("image", ""), "ports": c["ports"], "status": c["status"]}
        for c in receipt.get("containers", [])
    ]

    # Network interfaces
    network_interfaces = []
    if receipt.get("lan_ip"):
        network_interfaces.append({"name": "lan", "ip": receipt["lan_ip"], "type": "lan"})
    if receipt.get("tailscale") and receipt["tailscale"] not in ("", "none"):
        network_interfaces.append({"name": "tailscale", "ip": receipt["tailscale"], "type": "tailscale"})

    # Available port ranges — project space, in blocks, skipping bound ports
    try:
        with _port_cache_lock:
            bound = {p["port"] for p in _port_cache["ports"]}
    except Exception:
        bound = set()
    available_port_ranges = []
    for base in range(PROJECT_BAND_FLOOR, PROJECT_BAND_CEIL + 1, PROJECT_BAND_SIZE):
        if not any(p in bound for p in range(base, base + PROJECT_BAND_SIZE)):
            available_port_ranges.append({"start": base,
                                          "end": base + PROJECT_BAND_SIZE - 1})
        if len(available_port_ranges) >= 10:
            break

    return {
        "hostname":              receipt.get("hostname", ""),
        "os":                    receipt.get("os", ""),
        "cpu_cores":             cpu_cores,
        "ram_total_mb":          ram_total_mb,
        "ram_available_mb":      ram_available_mb,
        "disk_total_gb":         disk_total_gb,
        "disk_available_gb":     disk_available_gb,
        "docker_version":        docker_version,
        "running_containers":    running_containers,
        "available_port_ranges": available_port_ranges,
        "network_interfaces":    network_interfaces,
        "hub_port":              PORT,
        "generated":             receipt.get("generated", datetime.now().isoformat(timespec="seconds")),
    }


# ── Storage + Docker management APIs ──────────────────────────────────────────

# 20202311  api_storage_info — df -BG + lsblk + docker system df
def api_storage_info():
    """Disk breakdown + Docker usage combined."""
    mounts = []
    try:
        out = subprocess.check_output(
            ['df', '-BG', '--output=source,target,size,used,avail,pcent'],
            text=True, stderr=subprocess.DEVNULL).splitlines()[1:]
        for line in out:
            p = line.split()
            if len(p) >= 6 and not any(x in p[1] for x in ['docker','overlay','tmpfs','udev','loop','/snap']):
                mounts.append({
                    'source': p[0], 'mount': p[1],
                    'total_gb': int(p[2].rstrip('G')),
                    'used_gb':  int(p[3].rstrip('G')),
                    'avail_gb': int(p[4].rstrip('G')),
                    'pct':      int(p[5].rstrip('%')),
                })
    except Exception: pass

    unattached = []
    try:
        out = subprocess.check_output(
            ['lsblk','-dn','-o','NAME,SIZE,TYPE'],
            text=True, stderr=subprocess.DEVNULL).splitlines()
        for line in out:
            p = line.split()
            if len(p) >= 3 and p[2] == 'disk':
                check = subprocess.check_output(
                    ['lsblk','-n','-o','MOUNTPOINT', '/dev/' + p[0]],
                    text=True, stderr=subprocess.DEVNULL).strip()
                if not check:
                    unattached.append({'name': p[0], 'size': p[1], 'path': '/dev/' + p[0]})
    except Exception: pass

    # Disk info tree — physical disks + partitions with fstype, label, uuid, mountpoint
    disk_tree = []
    try:
        raw = subprocess.check_output(
            ['lsblk', '-o', 'NAME,SIZE,TYPE,MOUNTPOINT,FSTYPE,LABEL,UUID', '-rn'],
            text=True, stderr=subprocess.DEVNULL).splitlines()
        current_disk = None
        disk_map = {}
        for line in raw:
            p = line.split()
            if len(p) < 3: continue
            name, size, typ = p[0], p[1], p[2]
            mount   = p[3] if len(p) > 3 else ''
            fstype  = p[4] if len(p) > 4 else ''
            label   = p[5] if len(p) > 5 else ''
            uuid    = p[6] if len(p) > 6 else ''
            if typ == 'disk':
                current_disk = {'name': name, 'size': size, 'path': '/dev/'+name, 'parts': []}
                disk_map[name] = current_disk
                disk_tree.append(current_disk)
            elif typ in ('part', 'lvm', 'crypt') and current_disk:
                current_disk['parts'].append({
                    'name': name, 'size': size, 'type': typ,
                    'mount': mount, 'fstype': fstype,
                    'label': label, 'uuid': uuid,
                    'path': '/dev/'+name,
                })
    except Exception: pass

    docker_df = {'images': {}, 'containers': {}, 'volumes': {}, 'build_cache': {}}
    try:
        raw = subprocess.check_output(
            ['docker', 'system', 'df'],
            text=True, stderr=subprocess.DEVNULL).splitlines()
        for line in raw[1:]:
            p = line.split()
            if not p: continue
            if 'Image' in line:
                docker_df['images'] = {'total': p[1], 'active': p[2], 'size': p[3], 'reclaimable': ' '.join(p[4:])}
            elif 'Container' in line:
                docker_df['containers'] = {'total': p[1], 'active': p[2], 'size': p[3], 'reclaimable': ' '.join(p[4:])}
            elif 'Volume' in line:
                docker_df['volumes'] = {'total': p[1], 'active': p[2], 'size': p[3], 'reclaimable': ' '.join(p[4:])}
            elif 'Build' in line or 'Cache' in line:
                docker_df['build_cache'] = {'total': p[1], 'active': p[2], 'size': p[3], 'reclaimable': ' '.join(p[4:])}
    except Exception: pass

    snap_count = 0
    try:
        snap_count = int(subprocess.check_output(
            ['bash', '-c', 'snap list 2>/dev/null | tail -n +2 | wc -l'],
            text=True).strip())
    except Exception: pass

    log_size = ''
    try:
        log_size = subprocess.check_output(
            ['du', '-sh', '/var/log'], text=True, stderr=subprocess.DEVNULL).split()[0]
    except Exception: pass

    return {
        'mounts': mounts,
        'unattached': unattached,
        'docker': docker_df,
        'snap_count': snap_count,
        'log_size': log_size,
        'disk_tree': disk_tree,
        'generated': datetime.now().isoformat(timespec='seconds'),
    }


# 20202312  api_docker_images — docker images parsed
def api_docker_images():
    """Docker images list with metadata."""
    images = []
    try:
        out = subprocess.check_output(
            ['docker', 'images', '--format',
             '{{.Repository}}\t{{.Tag}}\t{{.ID}}\t{{.Size}}\t{{.CreatedSince}}'],
            text=True, stderr=subprocess.DEVNULL).strip()
        for line in out.splitlines():
            p = line.split('\t')
            if len(p) >= 5:
                images.append({
                    'repo': p[0], 'tag': p[1], 'id': p[2],
                    'size': p[3], 'created_since': p[4],
                })
    except Exception: pass
    return {'images': images, 'count': len(images)}


# 20202313  api_docker_volumes — docker system df -v volumes
def api_docker_volumes():
    """Docker volumes with link counts and sizes."""
    volumes = []
    try:
        out = subprocess.check_output(
            ['docker', 'system', 'df', '-v'],
            text=True, stderr=subprocess.DEVNULL)
        in_vol = False
        for line in out.splitlines():
            if 'Local Volumes' in line: in_vol = True; continue
            if in_vol and 'Build Cache' in line: break
            if in_vol and line.strip() and 'VOLUME' not in line:
                p = line.split()
                if len(p) >= 3:
                    volumes.append({
                        'name': p[0],
                        'links': p[1],
                        'size': p[2],
                        'reclaimable': p[1] == '0',
                    })
    except Exception: pass
    return {'volumes': volumes, 'count': len(volumes)}


# 20202314  api_docker_stats — docker stats --no-stream per container
def api_docker_stats():
    """Per-container CPU + memory snapshot (non-streaming)."""
    stats = []
    try:
        out = subprocess.check_output(
            ['docker', 'stats', '--no-stream', '--format',
             '{{.Name}}\t{{.CPUPerc}}\t{{.MemUsage}}\t{{.MemPerc}}\t{{.NetIO}}\t{{.BlockIO}}'],
            text=True, stderr=subprocess.DEVNULL, timeout=15).strip()
        for line in out.splitlines():
            p = line.split('\t')
            if len(p) >= 4:
                stats.append({
                    'name': p[0], 'cpu': p[1], 'mem_usage': p[2],
                    'mem_pct': p[3], 'net_io': p[4] if len(p) > 4 else '',
                    'block_io': p[5] if len(p) > 5 else '',
                })
    except Exception: pass
    return {'stats': stats}


# 20202315  api_docker_diagnostics — interpreted findings: restarts, disk, unhealthy
def api_docker_diagnostics():
    """Interpreted diagnostic signals — actionable findings, not raw data."""
    findings = []
    containers = get_containers()
    running_names = [c['name'] for c in containers if c.get('running')]

    # High restart counts
    if running_names:
        try:
            out = subprocess.check_output(
                ['docker', 'inspect', '--format',
                 '{{.Name}}\t{{.RestartCount}}\t{{.State.Status}}'] + running_names,
                text=True, stderr=subprocess.DEVNULL).strip()
            for line in out.splitlines():
                p = line.strip().split('\t')
                if len(p) >= 2:
                    name = p[0].lstrip('/')
                    restarts = int(p[1]) if p[1].isdigit() else 0
                    if restarts >= 3:
                        lvl = 'error' if restarts >= 10 else 'warn'
                        findings.append({
                            'level': lvl, 'category': 'container', 'subject': name,
                            'message': f'Restarted {restarts} times. Common causes: missing env var, bad config, dependency not ready.',
                            'action': 'Check container logs for the crash reason.',
                        })
        except Exception: pass

    # Disk pressure on root
    try:
        out = subprocess.check_output(
            ['df', '-BG', '--output=target,pcent', '/'],
            text=True, stderr=subprocess.DEVNULL).splitlines()
        if len(out) > 1:
            pct = int(out[1].split()[1].rstrip('%'))
            if pct >= 90:
                findings.append({'level': 'error', 'category': 'disk', 'subject': 'Root disk /',
                    'message': f'Root disk at {pct}% — critical. Docker operations may start failing.',
                    'action': 'Run Docker prune immediately, or expand the volume.'})
            elif pct >= 80:
                findings.append({'level': 'warn', 'category': 'disk', 'subject': 'Root disk /',
                    'message': f'Root disk at {pct}% — getting tight.',
                    'action': 'Run Docker prune to recover reclaimable space.'})
    except Exception: pass

    # Unhealthy containers
    try:
        out = subprocess.check_output(
            ['docker', 'ps', '--filter', 'health=unhealthy', '--format', '{{.Names}}'],
            text=True, stderr=subprocess.DEVNULL).strip()
        for name in out.splitlines():
            if name:
                findings.append({'level': 'error', 'category': 'container', 'subject': name,
                    'message': 'Container health check is failing.',
                    'action': 'Check container logs and the HEALTHCHECK command definition.'})
    except Exception: pass

    # Containers exited with error (not clean exit)
    try:
        out = subprocess.check_output(
            ['docker', 'ps', '-a', '--filter', 'status=exited',
             '--format', '{{.Names}}\t{{.Status}}'],
            text=True, stderr=subprocess.DEVNULL).strip()
        for line in out.splitlines():
            p = line.split('\t')
            if len(p) >= 2 and 'Exited (0)' not in p[1]:
                findings.append({'level': 'warn', 'category': 'container', 'subject': p[0],
                    'message': f'Exited with error: {p[1]}',
                    'action': 'Check logs. Container may need a config fix or restart.'})
    except Exception: pass

    # Large reclaimable space
    try:
        raw = subprocess.check_output(['docker', 'system', 'df'],
            text=True, stderr=subprocess.DEVNULL).splitlines()
        for line in raw:
            p = line.split()
            if 'Image' in line and len(p) >= 5:
                rec = p[-1].replace('(','').replace(')','')
                if 'GB' in rec:
                    gb = float(rec.replace('GB',''))
                    if gb > 3:
                        findings.append({'level': 'info', 'category': 'docker', 'subject': 'Unused images',
                            'message': f'{rec} reclaimable from images not attached to any container.',
                            'action': 'Go to Docker → Cleanup → Prune Images to recover this space.'})
            if 'Volume' in line and len(p) >= 5:
                rec = p[-1].replace('(','').replace(')','')
                if 'GB' in rec:
                    gb = float(rec.replace('GB',''))
                    if gb > 1:
                        findings.append({'level': 'info', 'category': 'docker', 'subject': 'Orphaned volumes',
                            'message': f'{rec} reclaimable from volumes with no container attached.',
                            'action': 'Go to Docker → Volumes to review, then Cleanup → Prune Volumes.'})
    except Exception: pass

    if not findings:
        findings.append({'level': 'ok', 'category': 'system', 'subject': 'All checks passed',
            'message': 'No issues detected. Everything looks healthy.',
            'action': ''})

    return {'findings': findings, 'generated': datetime.now().isoformat(timespec='seconds')}



# REMOVED (dead): config_get, config_set, config_get_all, users_list, user_auth,
# journal_add, journal_get — handlers/config.py and handlers/users.py each keep
# private copies (_config_get, _config_set, _user_auth, _journal_add, ...).
# Also removed get_storage_info (old SSH df + docker-df reader; api_storage_info
# below is what /api/storage actually calls) and get_files (handlers/proxy.py
# has _get_files for /api/files). None of the seven had a caller outside here.

# 20202309  get_manifest — full manifest BOM: server info, services, docker df, git ref
def get_manifest():
    """Full system snapshot — server info, all services, containers, health."""
    now = datetime.now().isoformat()

    # One SSH call for server identity
    info_r = ssh_run(
        'printf "%s\t%s\t%s\t%s\t%s\t%s" '
        '"$(hostname)" '
        '"$(lsb_release -ds 2>/dev/null | tr -d \'"\')" '
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
            'os': parts[1] if len(parts) > 1 else '',
            'kernel': parts[2] if len(parts) > 2 else '',
            'local_ip': parts[3] if len(parts) > 3 else '',
            'tailscale_ip': parts[4] if len(parts) > 4 else 'none',
            'cpu_cores': int(parts[5]) if len(parts) > 5 and parts[5].strip().isdigit() else 0,
        }

    status = get_status()
    if status.get('ram_total_mb'):
        server['ram_total_gb'] = round(status['ram_total_mb'] / 1024, 1)

    containers = get_containers()
    services = build_services(server)

    # Hub git ref (if running from a git checkout)
    git_r = ssh_run(f'cd {BASE_DIR} && git log -1 --format="%h %s" 2>/dev/null || echo unknown')
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


# REMOVED (dead): _substitute_guide_tokens, _build_this_server_doc — guide token
# substitution and the live "this server" doc are served from handlers/proxy.py,
# which owns the /docs/* routes.
# REMOVED (dead): ai_system_prompt, ai_chat — handlers/ai.py has _ai_system_prompt
# and _ai_chat and reaches back into this module only for _cache.

# 20202316  get_integrations — live health: Redis PING, SurrealDB /health, n8n /healthz
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

# KERNEL: check_auth moved to kernel/auth.py

# ── TOTP ──────────────────────────────────────────────────────────────────────
# KERNEL: _totp_hotp, totp_verify, totp_new_secret, totp_verify_secret, totp_uri moved to kernel/auth.py

# ── Gate sessions ─────────────────────────────────────────────────────────────
# KERNEL: _gate_sessions, _gate_lock, gate_create, gate_check moved to kernel/auth.py

# ── Tunnel management ─────────────────────────────────────────────────────────
_tunnel_url    = ''
_tunnel_lock_t = threading.Lock()

# REMOVED (dead): _tunnel_watcher — handlers/tunnel.py runs the real watcher against
# its own _tunnel_url. This module's watcher was never started, so the _tunnel_url
# that tunnel_status() reads below has always been '' here. Deleting the watcher
# changes nothing; the empty url is pre-existing and left alone deliberately.

# 20208302  tunnel_status — docker inspect tunnel container; return {running, url}
def tunnel_status():
    try:
        r = subprocess.run(
            ['docker', 'inspect', '--format', '{{.State.Status}}', 'server-hub-tunnel'],
            capture_output=True, text=True, timeout=5
        )
        running = r.stdout.strip() == 'running'
    except Exception:
        running = False
    with _tunnel_lock_t:
        url = _tunnel_url if running else ''
    return {'running': running, 'url': url}

# REMOVED (dead): tunnel_start, tunnel_stop — handlers/tunnel.py owns the
# /api/tunnel/start and /api/tunnel/stop routes and has its own copies.

# 20201302  get_access_info — all hub URLs: local, Tailscale, tunnel
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
