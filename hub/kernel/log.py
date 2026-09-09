#!/usr/bin/env python3
"""
# 20200004  kernel.log — activity logging, ntfy push, Docker event watcher
Hub kernel: observability layer.
"""
import json
import os
import subprocess
import threading
import time
import urllib.error
import urllib.request
import ssl
from datetime import datetime

_ssl_ctx = ssl.create_default_context()
_ssl_ctx.check_hostname = False
_ssl_ctx.verify_mode = ssl.CERT_NONE

_docker_watcher_running = False

# 20200307  log_activity — append to activity_log, never raises
def log_activity(db_conn_fn, action, source='system', category='general', detail='', level='info'):
    """Write one line to the activity log. Universal — always safe to call."""
    try:
        conn = db_conn_fn()
        conn.execute(
            "INSERT INTO activity_log (ts,source,category,action,detail,level) VALUES (?,?,?,?,?,?)",
            (datetime.now().isoformat(timespec='seconds'), source, category, action, detail, level)
        )
        conn.commit()
        conn.close()
    except Exception:
        pass  # never crash the caller

# 20200308  activity_recent — SELECT recent activity_log rows
def activity_recent(db_conn_fn, limit=100, category=None):
    try:
        conn = db_conn_fn()
        if category:
            rows = conn.execute(
                "SELECT * FROM activity_log WHERE category=? ORDER BY id DESC LIMIT ?",
                (category, limit)).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM activity_log ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        conn.close()
        return [dict(r) for r in rows]
    except Exception:
        return []

# 20206302  _ntfy_send — POST push notification to ntfy
def _ntfy_send(title, body, priority='default', tags='server'):
    """Send ntfy push notification. Reads config from ~/.server-alerts.conf or env."""
    try:
        conf_path = os.path.expanduser('~/.server-alerts.conf')
        url = os.environ.get('HUB_NTFY_URL', 'http://localhost:8085')
        topic = os.environ.get('HUB_NTFY_TOPIC', 'server-alerts')
        token = ''
        if os.path.exists(conf_path):
            for line in open(conf_path):
                line = line.strip()
                if line.startswith('NTFY_URL='):    url   = line.split('=',1)[1].strip()
                if line.startswith('NTFY_TOPIC='):  topic = line.split('=',1)[1].strip()
                if line.startswith('NTFY_TOKEN='):  token = line.split('=',1)[1].strip()
        headers = {'Title': title, 'Priority': priority, 'Tags': tags}
        if token: headers['Authorization'] = f'Bearer {token}'
        req = urllib.request.Request(
            f'{url}/{topic}', data=body.encode(),
            headers=headers, method='POST')
        urllib.request.urlopen(req, timeout=5, context=_ssl_ctx)
    except Exception:
        pass

# 20206301  _docker_event_loop — stream docker events; write activity_log; ntfy on die/start
def _docker_event_loop(db_conn_fn, ssh_run_fn, ntfy_send_fn):
    """Stream docker events and write to activity log. Restarts on failure."""
    global _docker_watcher_running
    import shutil
    if not shutil.which('docker'):
        return  # Docker not installed — skip silently
    while True:
        try:
            proc = subprocess.Popen(
                ['docker', 'events', '--format', '{{json .}}'],
                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                text=True, bufsize=1
            )
            _docker_watcher_running = True
            for line in proc.stdout:
                line = line.strip()
                if not line:
                    continue
                try:
                    ev = json.loads(line)
                    etype  = ev.get('Type', '')
                    action = ev.get('Action', '')
                    actor  = ev.get('Actor', {})
                    name   = actor.get('Attributes', {}).get('name', actor.get('ID', '')[:12])
                    image  = actor.get('Attributes', {}).get('image', '')

                    if etype == 'container':
                        if action in ('start', 'die', 'create', 'destroy', 'restart'):
                            level = 'warn' if action in ('die', 'destroy') else 'info'
                            log_activity(
                                db_conn_fn,
                                action   = f'Container {action}: {name}',
                                source   = 'docker',
                                category = 'container',
                                detail   = image,
                                level    = level
                            )
                            # ntfy for significant events
                            if action == 'die':
                                ntfy_send_fn(f'🔴 Container died: {name}', image or '', 'high', 'whale,rotating_light')
                            elif action == 'start' and name not in ('watchtower',):
                                ntfy_send_fn(f'🟢 Container started: {name}', image or '', 'min', 'whale')
                    elif etype == 'image' and action == 'pull':
                        img = actor.get('Attributes', {}).get('name', name)
                        log_activity(db_conn_fn, f'Image pulled: {img}', 'docker', 'image', '', 'info')
                    elif etype == 'network':
                        pass  # too noisy — skip
                except Exception:
                    continue
            proc.wait()
        except Exception:
            pass
        _docker_watcher_running = False
        time.sleep(10)  # wait before reconnecting
