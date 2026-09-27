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
from kernel import storage as _store

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


# 20204318  _ntfy_health — is the notification path actually delivering?
def _ntfy_health():
    try:
        from kernel.log import ntfy_state  # noqa: PLC0415
        st = ntfy_state()
    except Exception:
        return {'healthy': None, 'error': 'unavailable'}
    return {
        'healthy': st['healthy'],
        'sent': st['sent'],
        'failed': st['failed'],
        'error': st['last_error'],
    }


# 20204319  _registry_block — the half of the beat that no node ever sent
def _registry_block():
    """THE BUG THIS EXISTS FOR. `mesh.post_heartbeat` has read
    body['registry'] since the day it was written, and no node has ever put one
    there. So `_record_registry` returned (None, None) on every beat of every
    node, central kept no ref for anything, and `_congruence('', central)`
    answered 'unknown' forever — correctly, and uselessly.

    The cost was not that the check was wrong. It is that the check could not be
    wrong: on 2026-09-26 both servers sat on fb09de8 and /api/mesh/fleet
    reported ref '' and congruence unknown for fks-services, exactly as it would
    have if the two boxes had been six weeks apart. "Are both servers running
    the same build" was answered by a human running git on each box by hand,
    while the thing built to answer it said nothing, and said it quietly.

    WHAT GOES IN, AND WHY ONLY THIS. Two fields exist to be compared, and they
    are the only two that are MEANT to be identical fleet-wide: `ref`, and
    `console`, the sha of the one app.html every server serves byte for byte.
    The counts ride along because central cannot ask an unreachable node for
    them — they are carried, never compared. See `mesh._congruence`.

    NEVER RAISES, AND NEVER OMITS ITSELF SILENTLY. A node whose control database
    is unreadable still knows its ref and its console, so it still sends them
    and names the failure in `error`. An absent block means something else at
    central — "this node's build predates the field" — and the two must not be
    collapsed into one another.
    """
    block = {'ref': '', 'console': ''}
    try:
        from handlers.registry import _master, console_sha   # noqa: PLC0415
        block['ref'] = _master()
        block['console'] = console_sha()
    except Exception as e:
        # Nothing below this line can be answered either, and a beat is worth
        # more than a crash: the emitter would swallow the exception and the
        # node would drop off the fleet view entirely rather than appear with a
        # reason.
        block['error'] = 'ref/console unavailable: %s' % e
        return block
    try:
        from kernel import control as _ctl                   # noqa: PLC0415
        projects = [{'name':   p.get('name', ''),
                     'status': p.get('status', ''),
                     'stale':  bool(p.get('stale'))}
                    for p in _ctl.registry(block['ref'])['projects']]
    except Exception as e:
        # No counts at all rather than zeroes. A zero project count from a node
        # whose database would not open is indistinguishable from a node that
        # genuinely runs nothing, and the fleet total would quietly shrink.
        block['error'] = 'control db unreadable: %s' % e
        return block
    block['project_count'] = len(projects)
    block['stale_count'] = sum(1 for p in projects if p['stale'])
    block['projects'] = projects
    return block


# 20204317  node_payload — the self-description, as data
def node_payload():
    """Shared by GET /api/node and the heartbeat emitter, so what a node
    reports to central is byte-identical to what it reports to a browser.
    Two builders would drift; one cannot.

    Which is also why the `registry` block is added HERE rather than in
    kernel.heartbeat: an emitter that enriched the payload on its way out would
    make the beat and /api/node two different shapes, and the thing central is
    comparing would be the one thing a browser could not check."""
    si = _srv.get_server_info()
    projects = _projects()
    enrolled = _enrollment()

    unassigned = projects.get('unassigned', {}).get('containers', [])
    unclaimed = [p for p in projects.values() if not p['claimed'] and p['project'] != 'unassigned']

    from kernel import identity as _idm  # noqa: PLC0415
    return {
        'generated':  datetime.now().isoformat(timespec='seconds'),
        'server_id':  _idm.server_id(),
        'mode':       _idm.mode(),

        # ── identity ────────────────────────────────────────────────────────
        'machine_id': _machine_id(),
        'hostname':   si.get('hostname', ''),
        # identity file is authoritative for the name; enroll.sh's node.json
        # and the hostname are only fallbacks. Reported the wrong name until
        # the two-instance test caught it.
        'node':       _idm.node_name() or (enrolled or {}).get('node') or si.get('hostname', ''),

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

        # ── what CODE runs here ─────────────────────────────────────────────
        # The only block in this payload that exists to be compared against
        # another machine's. Everything above is this box describing itself and
        # is expected to differ; this is the ref and the console sha, which are
        # expected not to. Rides the beat because the two servers sit on
        # different tailnets and cannot reach each other at all.
        'registry': _registry_block(),

        # ── things that need a human ────────────────────────────────────────
        # Not errors. Facts an authority should be able to see without asking.
        'attention': {
            'unassigned_containers': [c['name'] for c in unassigned],
            'projects_without_ksg_label': [p['project'] for p in unclaimed],
            'not_enrolled': enrolled is None,
            # A silently-failing alerting system is worse than none: you
            # believe you are covered. Report it as a fact about this node.
            'notifications': _ntfy_health(),
            # Storage is reported for the same reason as notifications: the
            # failure is silent. 40GB of dead build cache sat on this node's
            # OS disk for two weeks while a 458GB disk sat empty, because
            # nothing was looking.
            'storage': _store.landscape()['findings'],
        },
    }


# 20311701  GET /api/node — full node self-description
def get_node(handler, path, params):
    """# 20311701  GET /api/node"""
    handler.send_json(node_payload())

# ── Admission ────────────────────────────────────────────────────────────────
# A project asking "what are my boundaries here?" should get a live answer, not
# a wiki page someone last edited in March. Everything below is computed from
# the machine at call time.

RESERVED = {
    8765: 'hub — reserved on every node, never reassign',
    22:   'ssh',
    80:   'http', 443: 'https',
}
# The band is the kernel's to define, not this handler's. It was briefly
# declared here as 10020-10990, which sits inside the Supabase stack lane —
# /api/admit was handing out ports another service already owns. One source.
BAND_FLOOR = _srv.PROJECT_BAND_FLOOR
BAND_CEIL  = _srv.PROJECT_BAND_CEIL
BAND_SIZE  = _srv.PROJECT_BAND_SIZE


# 20204315  _ports_in_use — every bound TCP port on the host
def _ports_in_use():
    r = ssh_run("ss -tln | awk 'NR>1{print $4}' | grep -oE '[0-9]+$' | sort -n -u")
    if not r.get('online'):
        return []
    out = []
    for line in (r.get('output') or '').splitlines():
        line = line.strip()
        if line.isdigit():
            out.append(int(line))
    return out


# 20204316  _free_band — first unused contiguous block, so two projects cannot collide
def _free_band(used):
    taken = set(used)
    start = BAND_FLOOR
    while start + BAND_SIZE - 1 <= BAND_CEIL:
        if not any(p in taken for p in range(start, start + BAND_SIZE)):
            return [start, start + BAND_SIZE - 1]
        start += BAND_SIZE
    return None


# 20311702  GET /api/admit — the boundaries a new project must work inside
def get_admit(handler, path, params):
    """# 20311702  GET /api/admit?project=<name>

    ServerHub owns the port landscape and knows every container. So rather than
    a project guessing — or a human remembering — it asks, and gets the live
    answer: what name is free, what band it may bind, what it must never touch.
    """
    wanted = (params.get('project') or '').strip().lower()
    used = _ports_in_use()
    projects = _projects()
    existing = sorted(k for k in projects if k != 'unassigned')

    band = _free_band(used)
    collision = wanted in projects if wanted else None

    # Derived, not assumed. This node's data path depends on this node's disks:
    # ksgcohub has a 458GB mount at /srv/data, fks-services does not. A single
    # hardcoded path is correct on one machine and wrong on the other, and the
    # project that believes it fills the OS disk.
    land = _store.landscape()
    dr = land['data_root']
    data_dir = ('%s/<project>' % dr['path'].rstrip('/')) if dr['dedicated']                else '/srv/docker/<project>/data'

    # WHICH SERVER, AND WHAT IS COMING. THE-PLAN step 6, verbatim: "YOUR GOING
    # TO ALSO PROVIDE THEM WITH THERE SERVER REIPET AND THERE SERVER ID ... AND
    # ALSO ALL THE PAENDINDING SHIT THAT IS GOING TO GO DOWN STREAM LATER".
    # Both were missing.
    #
    # server_id: a project learned the node's NAME and machine-id, never
    # fvn_xxxxxx -- the derived id the whole fleet keys on, which survives a
    # rename while a hostname does not. A project recording "ksgcohub"
    # recorded something that can change under it.
    #
    # pending: a project told its band is 7100-7899 will bind there. If that
    # band is due to move it must know AT THE MOMENT IT IS TOLD, not in a
    # bulletin it may never read. Pending is what makes a receipt honest about
    # its own shelf life -- and it is why a NEW project can expect zero diffs:
    # it was told everything, including what is coming, before it built.
    # Both imported HERE. _idm is imported inside node_payload(), not at module
    # scope, so referencing it from this function raised NameError and took
    # /api/admit down completely -- the front door every project knocks on,
    # returning nothing at all.
    from kernel import identity as _idm         # noqa: PLC0415
    try:
        from handlers import registry as _reg   # noqa: PLC0415
        _pend = _reg._pending()
    except Exception:
        _pend = []

    handler.send_json({
        'node':        (_enrollment() or {}).get('node', ''),
        'server_id':   _idm.server_id(),
        'machine_id':  _machine_id(),
        'pending':     _pend,
        'project':     wanted or None,
        'name_available': (not collision) if wanted else None,
        'existing_projects': existing,

        'assigned_band': band,          # [lo, hi] — bind only inside this
        'ports_in_use':  used,

        # The disks this answer was derived from, so a project (or a human)
        # can check the reasoning rather than trusting the conclusion.
        'storage': {
            'data_root': dr['path'],
            'dedicated': dr['dedicated'],
            'mounts':    land['mounts'],
            'findings':  land['findings'],
        },

        # The contract. Same words every project, so the fleet stays queryable.
        'contract': {
            'directory': '/srv/docker/<project>',
            'network':   '<project>-net, declared in the compose file',
            'container': '<project>-<NN>-<service>-<version>',
            'labels': {
                'com.ksg.project': '<project>',
                'com.ksg.owner':   '<owner>',
                'com.ksg.role':    '<api|ui|db|worker>',
                'com.ksg.data':    '/srv/docker/<project>/data',
            },
            'data':      data_dir + '  — one bind mount, the only thing needing backup',
            'secrets':   '.env, gitignored, generated fresh. Never copied between projects.',
            'git':       'its own repo. The server is never the source of truth.',
        },

        'forbidden': {
            'ports':  RESERVED,
            'rules': [
                'do not bind outside the assigned band',
                "do not join the docker network of another project",
                "do not open the database of another project — cross-project data moves over HTTP",
                'do not write outside /srv/docker/<project>',
                "do not reuse secrets belonging to another project",
                'no docker run — every container comes from a compose file in the project directory',
            ],
        },

        # The test. If deleting the project disturbs anything else, it was not isolated.
        'acceptance': "docker ps --filter label=com.ksg.project=<project> returns "
                      "every container you own and nothing else; deleting your "
                      "directory and those containers disturbs nothing else on the host",
    })
