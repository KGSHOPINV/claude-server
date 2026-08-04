#!/usr/bin/env python3
"""
Hub nightly maintenance agent.
Runs on the server, reads system state, does safe cleanup,
diffs against baseline, sends AI-narrated report to ntfy.

Cron: 0 3 * * * /usr/bin/python3 /home/admin1/hub/maintenance.py
"""
import json, os, subprocess, time, urllib.request, urllib.error
from datetime import datetime

# ── Config ─────────────────────────────────────────────────────────────────────
HUB_API      = os.environ.get('HUB_API',     'http://localhost:8765')
NTFY_URL     = os.environ.get('NTFY_URL',    'http://localhost:8085')
NTFY_TOPIC   = os.environ.get('NTFY_TOPIC',  'server-alerts')
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

def ntfy(title, body, priority='default', tags='wrench'):
    try:
        req = urllib.request.Request(
            f'{NTFY_URL}/{NTFY_TOPIC}',
            data=body.encode(),
            headers={
                'Title': title,
                'Priority': priority,
                'Tags': tags,
                'Content-Type': 'text/plain',
            }, method='POST')
        urllib.request.urlopen(req, timeout=8)
    except Exception as e:
        print(f'ntfy error: {e}')

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

    status     = manifest.get('status') or {}
    containers = manifest.get('containers', {})
    disk       = manifest.get('disk', {})
    services   = manifest.get('services', [])
    baseline   = load_baseline()

    disk_pct    = pct_int(disk.get('pct', '0'))
    disk_used   = disk.get('used', '?')
    disk_total  = disk.get('total', '?')
    ram_used    = status.get('ram_used_mb', 0)
    ram_total   = status.get('ram_total_mb', 1)
    ram_pct     = round(ram_used / ram_total * 100) if ram_total else 0
    load        = status.get('load', '?')
    uptime      = status.get('uptime', '?')
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
    lines = [f'Server Hub — Nightly Report\n{ts} | Uptime: {uptime}', '']

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
        title = f'Server Alert — {len(warnings)} issue{"s" if len(warnings)>1 else ""}'
    elif actions:
        priority = 'default'
        tags = 'white_check_mark,wrench'
        title = 'Server Maintenance Done'
    else:
        priority = 'min'
        tags = 'white_check_mark'
        title = 'Server Nightly — All Good'

    ntfy(title, report, priority=priority, tags=tags)
    print(f'\n  → ntfy sent: [{priority}] {title}')

if __name__ == '__main__':
    main()
