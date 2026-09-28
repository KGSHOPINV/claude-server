#!/usr/bin/env python3
"""
Hub nightly maintenance agent.
Runs on the server, reads system state, does safe cleanup,
diffs against baseline, sends AI-narrated report to ntfy.

Cron: 0 3 * * * /usr/bin/python3 /home/admin1/hub/maintenance.py
"""
import base64, json, os, subprocess, time, urllib.request, urllib.error
from datetime import datetime

# ── Config ─────────────────────────────────────────────────────────────────────
def _alerts_conf(path=None):
    """Parse ~/.server-alerts.conf into a dict.

    This is the same file hub/kernel/log.py reads and hub/scripts/ntfy-lib.sh
    sources -- the machine's own answer to "where do the alerts go". It is why
    maintenance.py no longer trusts the unit file: hub-maintenance.service sets
    Environment=NTFY_URL=http://localhost:8085 and NTFY_TOPIC=server-alerts, and
    on fks-services both are wrong. ntfy there listens on 7001 with the topic
    fks-services and its ACL denies anonymous publish, so every nightly report
    was a POST to a closed port -- and ntfy() swallowed the error.
    """
    if path is None:
        path = (os.environ.get('SERVER_ALERTS_CONF')
                or os.path.expanduser('~/.server-alerts.conf'))
    conf = {}
    try:
        with open(path) as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith('#') or '=' not in line:
                    continue
                k, v = line.split('=', 1)
                conf[k.strip()] = v.strip().strip('"').strip("'")
    except OSError:
        pass
    return conf


_CONF = _alerts_conf()

# Precedence is the same as hub/scripts/ntfy-lib.sh, on purpose: an explicitly
# exported HUB_NTFY_* wins (someone redirecting a single run), then the conf
# file (the machine), then a plain NTFY_* out of the unit, then a default. The
# unit's values deliberately lose to the conf -- that is the whole repair.
HUB_API      = os.environ.get('HUB_API',     'http://localhost:8765')
NTFY_URL     = (os.environ.get('HUB_NTFY_URL') or _CONF.get('NTFY_URL')
                or os.environ.get('NTFY_URL') or 'http://localhost:7001')
NTFY_TOPIC   = (os.environ.get('HUB_NTFY_TOPIC') or _CONF.get('NTFY_TOPIC')
                or os.environ.get('NTFY_TOPIC') or 'fks-services')
NTFY_TOKEN   = os.environ.get('NTFY_TOKEN') or _CONF.get('NTFY_TOKEN') or ''
BASELINE_FILE= os.environ.get('BASELINE',    '/home/admin1/hub/.maintenance-baseline.json')
DISK_PRUNE_THRESHOLD = int(os.environ.get('DISK_PRUNE_PCT', '75'))
AI_API_KEY   = os.environ.get('HUB_AI_KEY',  '')
AI_PROVIDER  = os.environ.get('HUB_AI_PROV', 'claude')

# ── Helpers ────────────────────────────────────────────────────────────────────
def run(cmd, timeout=30):
    try:
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout)
        return r.stdout.strip()
    except Exception:
        return ''

def api_get(path):
    try:
        with urllib.request.urlopen(f'{HUB_API}{path}', timeout=10) as r:
            return json.loads(r.read())
    except Exception:
        return {}

def _ascii_header(value):
    """Return value unchanged if it is ASCII, else as an RFC 2047 encoded-word.

    ntfy carries Title/Priority/Tags as HTTP headers, and http.client encodes
    header values as latin-1, so a single non-ASCII character raises
    UnicodeEncodeError before the request ever leaves the process. That fault
    cost ksgcohub every alert it tried to send: 24 failed, 0 sent. Same
    function and same reason as hub/kernel/log.py's _ascii_header. ntfy accepts
    encoded-words in any header, title included (docs.ntfy.sh/publish/#utf-8).
    """
    try:
        value.encode('ascii')
        return value
    except (UnicodeEncodeError, AttributeError):
        raw = value if isinstance(value, str) else str(value)
        return '=?UTF-8?B?' + base64.b64encode(raw.encode('utf-8')).decode('ascii') + '?='


def ntfy(title, body, priority='default', tags='wrench'):
    """Send one notification. Returns True only if it landed.

    It used to return nothing and print only when it raised, while the caller
    printed "ntfy sent" either way -- so a closed port and a delivered report
    read identically in the journal. Now the caller is told the truth.
    """
    headers = {
        'Title': _ascii_header(title),
        'Priority': _ascii_header(priority),
        'Tags': _ascii_header(tags),
        'Content-Type': 'text/plain',
    }
    if NTFY_TOKEN:
        headers['Authorization'] = f'Bearer {NTFY_TOKEN}'
    try:
        req = urllib.request.Request(
            f'{NTFY_URL}/{NTFY_TOPIC}',
            data=body.encode('utf-8'),
            headers=headers, method='POST')
        with urllib.request.urlopen(req, timeout=8) as r:
            if 200 <= r.status < 300:
                return True
            print(f'ntfy error: HTTP {r.status} from {NTFY_URL}/{NTFY_TOPIC}')
    except urllib.error.HTTPError as e:
        extra = ('  - denies anonymous publish and no NTFY_TOKEN is set'
                 if e.code in (401, 403) and not NTFY_TOKEN else '')
        print(f'ntfy error: HTTP {e.code} from {NTFY_URL}/{NTFY_TOPIC}{extra}')
    except Exception as e:
        print(f'ntfy error: {e} ({NTFY_URL}/{NTFY_TOPIC})')
    return False

def load_baseline():
    try:
        with open(BASELINE_FILE) as f:
            return json.load(f)
    except Exception:
        return {}

def save_baseline(data):
    try:
        with open(BASELINE_FILE, 'w') as f:
            json.dump(data, f, indent=2)
    except Exception as e:
        print(f'baseline save error: {e}')

def pct_int(s):
    try:
        return int(str(s).rstrip('%'))
    except Exception:
        return 0

# ── Main ───────────────────────────────────────────────────────────────────────
def main():
    now = datetime.now()
    ts  = now.strftime('%Y-%m-%d %H:%M')
    print(f'\n[maintenance] {ts}')

    # 1. Pull current state
    manifest = api_get('/api/manifest')
    if not manifest:
        ntfy('Hub Maintenance Failed', 'Could not reach hub API at maintenance time.', priority='high', tags='warning')
        return

    # manifest top-level keys: uptime, load, disk, containers, server, services
    server     = manifest.get('server', {})
    containers = manifest.get('containers', {})
    disk       = manifest.get('disk', {})
    services   = manifest.get('services', [])
    baseline   = load_baseline()

    disk_pct    = pct_int(disk.get('pct', '0'))
    disk_used   = disk.get('used', '?')
    disk_total  = disk.get('total', '?')
    ram_total_gb= server.get('ram_total_gb', 0)
    load        = manifest.get('load', '?')
    uptime      = manifest.get('uptime', '?')
    # estimate RAM pct from hub status cache via API
    status_d    = api_get('/api/status')
    ram_used    = status_d.get('ram_used_mb', 0)
    ram_total   = status_d.get('ram_total_mb', 1)
    ram_pct     = round(ram_used / ram_total * 100) if ram_total else 0
    ctr_total   = containers.get('total', 0)
    ctr_running = containers.get('running', 0)
    ctr_stopped = containers.get('stopped', 0)

    actions  = []   # things we did
    warnings = []   # things that need attention
    ok_items = []   # things that look fine

    # 2. Docker prune if disk is high
    freed_space = ''
    if disk_pct >= DISK_PRUNE_THRESHOLD:
        print(f'  Disk at {disk_pct}% — running docker system prune...')
        before = run("df / | awk 'NR==2{print $3}'")
        run('docker system prune -f --volumes 2>/dev/null', timeout=60)
        after = run("df / | awk 'NR==2{print $3}'")
        try:
            freed_kb = int(before) - int(after)
            freed_space = f'{freed_kb // 1024}MB'
            actions.append(f'Ran docker prune — freed {freed_space} (disk was {disk_pct}%)')
        except Exception:
            actions.append(f'Ran docker prune (disk was {disk_pct}%)')
        # re-read disk after prune
        new_pct = pct_int(run("df / | awk 'NR==2{print $5}'"))
        disk_pct = new_pct

    # 3. Check stopped containers
    stopped_names = [c['name'] for c in containers.get('list', []) if not c.get('running')]
    if stopped_names:
        warnings.append(f'Stopped containers ({len(stopped_names)}): {", ".join(stopped_names)}')
    else:
        ok_items.append(f'All {ctr_running} containers running')

    # 4. Disk status
    if disk_pct >= 90:
        warnings.append(f'Disk CRITICAL: {disk_pct}% ({disk_used}/{disk_total})')
    elif disk_pct >= 80:
        warnings.append(f'Disk high: {disk_pct}% ({disk_used}/{disk_total})')
    else:
        ok_items.append(f'Disk {disk_pct}% ({disk_used}/{disk_total})')

    # 5. RAM
    if ram_pct >= 90:
        warnings.append(f'RAM high: {ram_pct}% ({ram_used}MB/{ram_total}MB)')
    else:
        ok_items.append(f'RAM {ram_pct}% ({ram_used}MB/{ram_total}MB)')

    # 6. Load
    try:
        load1 = float(load.split()[0])
        cpu_cores = manifest.get('server', {}).get('cpu_cores', 4)
        if load1 > cpu_cores * 0.8:
            warnings.append(f'High load: {load} ({cpu_cores} cores)')
        else:
            ok_items.append(f'Load {load}')
    except Exception:
        ok_items.append(f'Load {load}')

    # 7. Diff against baseline — catch drift
    if baseline:
        prev_running = baseline.get('ctr_running', ctr_running)
        if ctr_running < prev_running:
            delta = prev_running - ctr_running
            warnings.append(f'Container count dropped by {delta} since last check (was {prev_running}, now {ctr_running})')

        prev_disk = baseline.get('disk_pct', 0)
        growth = disk_pct - prev_disk
        if growth >= 10:
            warnings.append(f'Disk grew {growth}% since last maintenance (was {prev_disk}%, now {disk_pct}%)')

    # 8. Save new baseline
    save_baseline({
        'ts': ts,
        'disk_pct': disk_pct,
        'ctr_running': ctr_running,
        'ram_pct': ram_pct,
    })

    # 9. Build report
    lines = [f'Server Hub - Nightly Report\n{ts} | Uptime: {uptime}', '']

    if actions:
        lines.append('ACTIONS TAKEN')
        for a in actions:
            lines.append(f'  ✓ {a}')
        lines.append('')

    if warnings:
        lines.append('NEEDS ATTENTION')
        for w in warnings:
            lines.append(f'  ⚠ {w}')
        lines.append('')

    lines.append('STATUS')
    for item in ok_items:
        lines.append(f'  ✓ {item}')

    report = '\n'.join(lines)
    print(report)

    # 10. Send to ntfy
    if warnings:
        priority = 'high' if any('CRITICAL' in w or 'dropped' in w for w in warnings) else 'default'
        tags = 'warning,wrench'
        title = f'Server Alert - {len(warnings)} issue{"s" if len(warnings)>1 else ""}'
    elif actions:
        priority = 'default'
        tags = 'white_check_mark,wrench'
        title = 'Server Maintenance Done'
    else:
        priority = 'min'
        tags = 'white_check_mark'
        title = 'Server Nightly - All Good'

    if ntfy(title, report, priority=priority, tags=tags):
        print(f'\n  → ntfy sent: [{priority}] {title}')
    else:
        print(f'\n  → ntfy NOT sent: [{priority}] {title}')

if __name__ == '__main__':
    main()
