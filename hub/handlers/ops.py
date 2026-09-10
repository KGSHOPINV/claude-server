#!/usr/bin/env python3
"""
# 20204010  handlers.ops -- run, update, install, ops endpoints
Hub handler module: ops layer (module 10).
All routes require gate level 2 or 3 (admin/TOTP).
"""
import json
import os
import secrets

from kernel.db   import db_conn
from kernel.ssh  import ssh_run, SSH_HOST, SSH_USER
from kernel.auth import check_auth, gate_check
from kernel.log  import log_activity

DOCKER_ROOT = os.environ.get('HUB_DOCKER_ROOT', '/srv/docker')
BASE_DIR    = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

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


# ── Route handlers ────────────────────────────────────────────────────────────

# 20310701  POST /api/run — run a shell command (gate level 3)
def post_run(handler, body):
    cmd = body.get('command', '').strip()
    if not cmd:
        handler.send_json({'error': 'No command provided'}, 400)
        return
    if not gate_check(handler.headers, 3, db_conn):
        handler.send_json({'error': 'gate_required', 'layer': 3,
                           'message': 'Shell access requires TOTP verification'}, 403)
        return
    result = ssh_run(cmd, timeout=int(body.get('timeout', 30)))
    handler.send_json(result)


# 20310702  POST /api/update — git pull + restart hub (gate level 3)
def post_update(handler, body):
    # git pull + restart hub service
    if not gate_check(handler.headers, 3, db_conn):
        handler.send_json({'error': 'gate_required', 'layer': 3,
                           'message': 'Hub update requires TOTP verification'}, 403)
        return
    hub_dir = BASE_DIR
    lines = []
    pull = ssh_run(f'cd {hub_dir} && git pull 2>&1', timeout=60)
    lines.append(pull.get('output', pull.get('error', '(no output)')))
    restart = ssh_run('systemctl --user restart hub 2>&1', timeout=15)
    lines.append(restart.get('output', '') or ('restarted' if restart.get('exitcode', 1) == 0 else restart.get('error', '')))
    handler.send_json({'ok': pull.get('exitcode', 1) == 0, 'output': '\n'.join(lines)})


# 20310703  POST /api/setup/generate-claude-md — regenerate CLAUDE.md
def post_setup_generate_claude_md(handler, body):
    # Write a filled-in CLAUDE.md to the hub directory on the server
    if not gate_check(handler.headers, 3, db_conn):
        handler.send_json({'error': 'gate_required', 'layer': 3,
                           'message': 'Generating CLAUDE.md requires TOTP verification'}, 403)
        return
    si = get_server_info()
    ts_ip = si.get('tailscale_ip', 'none')
    ts_name_r = ssh_run('tailscale status --self 2>/dev/null | head -1 | awk \'{print $2}\'')
    ts_name = ts_name_r.get('output', '').strip() or 'unknown'
    home = si.get('home_dir', os.path.expanduser('~'))
    user = si.get('ssh_user', '')
    local_ip = si.get('local_ip', '')
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
    if r2.get('exitcode', 1) == 0:
        handler.send_json({'ok': True, 'path': dest})
    else:
        handler.send_json({'ok': False, 'error': r2.get('error', 'Write failed')})


# 20310704  POST /api/service/install — install a service
def post_service_install(handler, body):
    name = body.get('name', '').strip().lower()
    INSTALLABLE = {
        'n8n':       'cd ' + DOCKER_ROOT + '/n8n && docker compose up -d',
        'redis':     'cd ' + DOCKER_ROOT + '/redis && docker compose up -d',
        'surrealdb': 'cd ' + DOCKER_ROOT + '/surrealdb && docker compose up -d',
        'minio':     'cd ' + DOCKER_ROOT + '/minio && docker compose up -d',
        'adminer':   'cd ' + DOCKER_ROOT + '/adminer && docker compose up -d',
        'mailpit':   'cd ' + DOCKER_ROOT + '/mailpit && docker compose up -d',
        'wikijs':    'cd ' + DOCKER_ROOT + '/wikijs && docker compose up -d',
    }
    if name not in INSTALLABLE:
        handler.send_json({'ok': False, 'error': f'Unknown service: {name}'}, 400)
        return
    result = ssh_run(INSTALLABLE[name], timeout=60)
    handler.send_json({'ok': result.get('exitcode', 1) == 0, 'output': result.get('output', ''), 'error': result.get('error', '')})
