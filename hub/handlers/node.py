#!/usr/bin/env python3
"""
# 20204011  handlers.node — this node's complete self-description (module 11)

ServerHub doctrine: "I am the ops floor. I watch, I deploy, I report."
This is the report. One call returns everything an authority (FlareVault) needs
to know about this node, so assembling a fleet view is polling N nodes rather
than N authorities each guessing.

Deliberately NOT here: credentials, domain configuration, project state. Those
belong to FlareVault and Metaforge. This endpoint describes what is, and
nothing about what should be — intent lives with the authority, not the node.

Everything is derived from the machine at call time. Nothing is maintained
alongside it, because records maintained alongside a machine drift away from it.
"""
import json
import os
from datetime import datetime

from kernel.ssh import ssh_run
from kernel import collect as _srv

PORT = int(os.environ.get('HUB_PORT', 8765))

# Written by enroll.sh. Absent on a node that has never been enrolled, which is
# a legitimate state, not an error.
NODE_FILE = os.path.expanduser('~/.flare/node.json')


# 20204311  _machine_id — the stable node key
def _machine_id():
    """/etc/machine-id. Survives hostname, IP and tailnet changes.

    This is why peers should be keyed by machine-id rather than URL: an address
    that changes makes a URL-keyed peer dead, but a machine-id-keyed peer has
    simply moved.
    """
    r = ssh_run('cat /etc/machine-id 2>/dev/null')
    return (r.get('output') or '').strip() if r.get('online') else ''


# 20204312  _enrollment — what enroll.sh recorded, if anything
def _enrollment():
    try:
        with open(NODE_FILE, encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return None


# 20204313  _projects — containers grouped by owning project, from labels
def _projects():
    """Group every container by the project that claims it.

    Preference order for ownership:
      com.ksg.project             explicit claim (the convention)
      com.docker.compose.project  implicit, from the compose file
      "unassigned"                nothing claims it

    That last bucket is the useful one. A container nobody claims cannot be
    reasoned about, backed up, or safely deleted — it just accrues. Surfacing
    them is the point.
    """
    fmt = ('{{.Names}}|{{.Label "com.ksg.project"}}|'
           '{{.Label "com.docker.compose.project"}}|{{.Status}}|{{.Ports}}|{{.Image}}')
    r = ssh_run('docker ps -a --format \'%s\'' % fmt)
    projects = {}
    if not r.get('online'):
        return projects
    for line in (r.get('output') or '').splitlines():
        parts = line.split('|')
        if len(parts) < 4:
            continue
        name, ksg, compose, status = parts[0], parts[1], parts[2], parts[3]
        owner = (ksg or compose or '').strip() or 'unassigned'
        projects.setdefault(owner, {
            'project': owner,
            'claimed': bool(ksg.strip()),   # explicit com.ksg.project label
            'containers': [],
        })['containers'].append({
            'name':    name,
            'status':  status,
            'ports':   parts[4] if len(parts) > 4 else '',
            'image':   parts[5] if len(parts) > 5 else '',
            'running': status.lower().startswith('up'),
        })
    return projects


# 20311701  GET /api/node — full node self-description
def get_node(handler, path, params):
    """# 20311701  GET /api/node"""
    si = _srv.get_server_info()
    projects = _projects()
    enrolled = _enrollment()

    unassigned = projects.get('unassigned', {}).get('containers', [])
    unclaimed = [p for p in projects.values() if not p['claimed'] and p['project'] != 'unassigned']

    handler.send_json({
        'generated':  datetime.now().isoformat(timespec='seconds'),

        # ── identity ────────────────────────────────────────────────────────
        'machine_id': _machine_id(),
        'hostname':   si.get('hostname', ''),
        'node':       (enrolled or {}).get('node', si.get('hostname', '')),

        # ── reachability ────────────────────────────────────────────────────
        'local_ip':     si.get('local_ip', ''),
        'tailscale_ip': si.get('tailscale_ip', ''),
        'hub_port':     PORT,
        'public':       (enrolled or {}).get('hostname'),   # None if not enrolled
        'enrolled':     enrolled,

        # ── host ────────────────────────────────────────────────────────────
        'os':     si.get('os', ''),
        'uptime': si.get('uptime', ''),

        # ── what runs here ──────────────────────────────────────────────────
        'projects': sorted(projects.values(), key=lambda p: p['project']),

        # ── things that need a human ────────────────────────────────────────
        # Not errors. Facts an authority should be able to see without asking.
        'attention': {
            'unassigned_containers': [c['name'] for c in unassigned],
            'projects_without_ksg_label': [p['project'] for p in unclaimed],
            'not_enrolled': enrolled is None,
        },
    })
