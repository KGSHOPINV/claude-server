#!/usr/bin/env python3
"""
# 20204013  handlers.registry — the endpoints a project talks to (module 13)

Every part of this existed as markdown first. A project cannot POST to a
document, cannot be told its master moved, and cannot acknowledge anything.
These are the same design, running.

    GET  /api/registry                      everything on THIS server
    GET  /api/registry/<project>            one project's standing record
    GET  /api/registry/<project>/diffs      the differences, with dispositions
    POST /api/registry/<project>            file or refile a claim
    POST /api/registry/<project>/verify     check the claim against the machine
    POST /api/registry/<project>/dispose    decide what to do about one diff
    POST /api/ack/<project>                 acknowledge the server's master

A claim on its own is a suggestion box. `verify` is the other half of the
exchange: the project says what it believes, and the machine is read and asked
whether it agrees. Verify REPORTS -- it never touches a container, never
relabels, never rebinds a port. Every difference carries the command that would
close it, and a human runs that command.

Scoped to one server by construction. The rules a project is given are derived
from THIS host's disks and THIS host's bound ports, so the same project on the
other machine is a different record with different values -- which is correct,
not duplication.

Cross-server comes free later: a node's heartbeat already carries its payload
to central, so central can serve the other server's registry without either box
reaching the other's network.
"""
import json
import re
import subprocess

from kernel import control as _ctl
from kernel import identity as _id
from kernel import storage as _store
from kernel.db import db_conn
from kernel.log import log_activity
from kernel.ssh import ssh_run


def _master():
    """The code ref this server is running. Derived, never stored -- a stored
    copy would be the exact drift this whole system exists to catch.

    CWD IS NOT OPTIONAL. This ran git with no cwd, so it inherited the
    service's, which is the user's home -- not a git repository. git failed,
    this returned '', and every consumer read that as "unknown".

    The cost was silent and total: _congruence() treats a missing ref as
    unknown rather than congruent, correctly, so /api/mesh/fleet has reported
    ref=None and congruent=None since the day it was written. The one check
    that answers "are both servers running the same build" has never once
    been able to answer, while the two servers drifted apart and back.

    Anchored to this file's own location instead, which is inside the repo by
    construction.
    """
    import os                                   # noqa: PLC0415
    repo = os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))))            # handlers/ -> hub/ -> repo
    try:
        r = subprocess.run(['git', 'rev-parse', '--short', 'HEAD'],
                           capture_output=True, text=True, timeout=5, cwd=repo)
        return r.stdout.strip() if r.returncode == 0 else ''
    except Exception:
        return 


def _who():
    return {'node': _id.node_name(), 'server_id': _id.server_id(),
            'master': _master(), 'mode': _id.mode()}


# 20313706  _target — the project and the sub-action inside one prefix route
def _target(path, prefix='/api/registry/'):
    """kernel/router.resolve matches the LONGEST LITERAL prefix, and the
    longest literal any of these paths can offer is `/api/registry/` -- the
    project name sits in the MIDDLE of `/api/registry/babyhelp/verify`, so
    /verify, /diffs and /dispose cannot be declared as route entries of their
    own. A second entry on the same prefix would sort equal and, because the
    sort is stable, never win against the one already there.

    So the split happens here, in the handler the router does reach. Returns
    ('', '') for a missing name rather than raising: a bare /api/registry/ is a
    bad request, not a crash.
    """
    tail = path[len(prefix):] if path.startswith(prefix) else path.rsplit('/', 1)[-1]
    parts = [s for s in tail.strip('/').split('/') if s]
    return ((parts[0].strip().lower() if parts else ''),
            (parts[1].strip().lower() if len(parts) > 1 else ''))


ACTIONS = {'GET': ('diffs',), 'POST': ('verify', 'dispose')}


# 20313701  GET /api/registry — every project on this server
def get_registry(handler, path, params):
    """# 20313701  GET /api/registry"""
    reg = _ctl.registry(_master())
    reg['who'] = _who()
    # Stale is surfaced at the top because it is the number that matters: how
    # many projects have NOT been told what this server is running.
    reg['stale_count'] = sum(1 for p in reg['projects'] if p.get('stale'))
    handler.send_json(reg)


# 20313702  GET /api/registry/<project> — one standing record
def get_registry_project(handler, path, params):
    """# 20313702  GET /api/registry/<project>

    The question a project asks forever: what is my state on my home server.
    Answered live -- the claim comes from the database, everything about the
    machine is read now.
    """
    name, action = _target(path)
    if action == 'diffs':
        get_registry_diffs(handler, path, params)
        return
    if action:
        handler.send_json({'ok': False, 'error': 'unknown action: %s' % action,
                           'available': list(ACTIONS['GET'])}, 404)
        return
    reg = _ctl.registry(_master())
    rec = next((p for p in reg['projects'] if p['name'] == name), None)
    if not rec:
        handler.send_json({'ok': False, 'error': 'not registered',
                           'who': _who(),
                           'how_to_register': 'POST /api/registry/%s' % name}, 404)
        return
    handler.send_json({'ok': True, 'who': _who(), 'project': rec,
                       'pending': _pending()})


# 20313703  POST /api/registry/<project> — file or refile a claim
def post_registry_project(handler, path, params, body):
    """# 20313703  POST /api/registry/<project>"""
    name, action = _target(path)
    if action == 'verify':
        post_registry_verify(handler, path, params, body)
        return
    if action == 'dispose':
        post_registry_dispose(handler, path, params, body)
        return
    if action:
        handler.send_json({'ok': False, 'error': 'unknown action: %s' % action,
                           'available': list(ACTIONS['POST'])}, 404)
        return
    if not name:
        handler.send_json({'ok': False, 'error': 'project name required'}, 400)
        return
    n, note = _ctl.register(name, body or {}, home=_id.server_id())
    if not n:
        handler.send_json({'ok': False, 'error': note}, 400)
        return
    log_activity(db_conn, 'registry: %s filed a claim (%s)' % (n, note),
                 'registry', 'project', n, 'info')
    handler.send_json({'ok': True, 'project': n, 'note': note,
                       'who': _who(), 'pending': _pending(),
                       'next': 'POST /api/ack/%s with the master above' % n})


# 20313704  POST /api/ack/<project> — acknowledge this server's master
def post_ack(handler, path, params, body):
    """# 20313704  POST /api/ack/<project>

    Body: {"ref": "<master>", "answer": "what I will do about pending"}

    `answer` is recorded even when it is "nothing, does not affect me". An
    unanswered pending change is how a project ends up bound to a port that
    moved underneath it.
    """
    name = path.rsplit('/', 1)[-1].strip().lower()
    b = body or {}
    ref = (b.get('ref') or '').strip()
    cur = _master()
    if ref and cur and ref != cur:
        # Acknowledging a ref the server is not on is recorded, not refused --
        # it is evidence the project is working from a stale view, which is
        # exactly what this is meant to surface.
        note = 'recorded, but this server is on %s not %s' % (cur, ref)
    else:
        note = 'current'
    n, msg = _ctl.acknowledge(name, ref or cur, b.get('answer', ''))
    if not n:
        handler.send_json({'ok': False, 'error': msg}, 400)
        return
    log_activity(db_conn, 'registry: %s acknowledged %s' % (n, (ref or cur)[:7]),
                 'registry', 'ack', n, 'info')
    handler.send_json({'ok': True, 'project': n, 'acknowledged': ref or cur,
                       'note': note, 'who': _who()})


# 20313705  _pending — what is about to move underneath every project here
def _pending():
    """Hardcoded for now and deliberately so: this is the list of KNOWN staged
    changes, and there is exactly one. When kernel/control.releases is driving
    stage/promote it comes from there instead.

    Empty must be reported as "none" rather than omitted -- silence and
    nothing-pending are different, and only one of them is information.
    """
    band = []
    try:
        from kernel import collect as _srv
        band = [_srv.PROJECT_BAND_FLOOR, _srv.PROJECT_BAND_CEIL]
    except Exception:
        pass
    if band and band[0] == 7100:
        return [{
            'change': 'project port band moves 10020-10990 -> 7100-7899',
            'why': '10000-10999 is the Supabase stack reserved lane; admit was '
                   'handing out ports another service owns',
            'when': 'on the next deploy of this server',
            'what_you_must_do': 'rebind before you publish, or acknowledge with '
                                'answer="accept" to record that you are '
                                'knowingly inside a reserved lane',
        }]
    return []


# ── VERIFY ───────────────────────────────────────────────────────────────────
# The claim is stored. The machine is read. Neither is corrected to match the
# other -- the DISTANCE between them is the product, and a verify that quietly
# fixed a label would destroy the only evidence there was ever a gap.
#
# Nothing below writes to Docker. Every command that would change something is
# returned as text for a human to run.

# {{.State}} not {{.Status}}: State is "running", Status is "Up 4 hours". A
# difference is stored and carries its disposition forward by its text, so an
# uptime string in that text would re-open every decided difference each hour.
_PS_FMT = ('{{.Names}}|{{.Label "com.ksg.project"}}|'
           '{{.Label "com.docker.compose.project"}}|'
           '{{.Label "com.docker.compose.project.config_files"}}|'
           '{{.State}}|{{.Image}}')

_INSPECT_FMT = '{{.Name}}|{{json .NetworkSettings.Ports}}|{{json .Mounts}}'

# A container name is data read off the machine, and it is about to be pasted
# into a shell command. Docker's own charset is narrower than this; anything
# outside it is dropped rather than quoted, because a name that cannot occur is
# a name worth refusing.
_SAFE_NAME = re.compile(r'^[A-Za-z0-9][A-Za-z0-9_.-]*$')

# Mounts every container has and no project owns. Counting these as "where the
# data sits" would report the docker socket as a project's database.
_NOT_DATA = ('/var/run/docker.sock', '/etc/localtime', '/etc/timezone',
             '/sys/fs/cgroup', '/proc', '/dev')


def _docker_root():
    """The directory convention /api/admit hands out. Read from the kernel so
    there is one root, not a second copy of it in this file."""
    try:
        from kernel import collect as _srv
        return _srv.DOCKER_ROOT
    except Exception:
        return '/srv/docker'


def _band():
    """Same rule as the root: the band belongs to the kernel. It was declared
    in a handler once, and the server spent a fortnight with two of them."""
    try:
        from kernel import collect as _srv
        return _srv.PROJECT_BAND_FLOOR, _srv.PROJECT_BAND_CEIL
    except Exception:
        return None, None


def _owns_name(cname, project):
    """A container belongs to a project by name when it IS the name or is
    prefixed by it at a separator. Plain startswith would hand `babyhelp` the
    containers of `babyhelp-staging`, which is the quiet mis-grouping this
    whole exchange exists to catch."""
    c = (cname or '').lower()
    return c == project or any(c.startswith(project + s) for s in ('-', '_', '.'))


# 20313707  _machine — what this host actually runs for a project, read now
def _machine(project):
    """Three independent channels, on purpose:

        label    com.ksg.project=<p>              the contract (Constitution VI)
        name     <p>, <p>-*, <p>_*                the convention
        compose  com.docker.compose.project=<p>   what compose grouped

    Asking only the first is how babyhelp reads as "0 containers" on a machine
    running three of them. Asking all three, and reporting WHICH channel found
    each container, turns that into a finding instead of a blank.

    Returns None when Docker could not be read at all -- distinct from "found
    nothing", because recording zero differences against an unreadable machine
    would mark the project verified and clean.
    """
    r = ssh_run("docker ps -a --format '%s'" % _PS_FMT, timeout=20)
    if not r.get('online'):
        return None

    found = {}
    for line in (r.get('output') or '').splitlines():
        p = line.split('|')
        if len(p) < 6:
            continue
        name, ksg, comp, cfg, state, image = (x.strip() for x in p[:6])
        via = []
        if ksg.lower() == project:
            via.append('label')
        if _owns_name(name, project):
            via.append('name')
        if comp.lower() == project:
            via.append('compose')
        if not via:
            continue
        found[name] = {'name': name, 'via': via, 'labelled': 'label' in via,
                       'state': state, 'image': image,
                       'compose_files': [f for f in cfg.split(',') if f]}

    ports, data, unreadable = set(), set(), []
    names = sorted(n for n in found if _SAFE_NAME.match(n))
    if names:
        ins = ssh_run("docker inspect --format '%s' %s"
                      % (_INSPECT_FMT, ' '.join(names)), timeout=30)
        for line in (ins.get('output') or '').splitlines():
            p = line.split('|', 2)
            if len(p) < 3:
                continue
            cname = p[0].strip().lstrip('/')
            try:
                pmap = json.loads(p[1]) or {}
                mounts = json.loads(p[2]) or []
            except Exception:
                # Named, so a container whose shape could not be read is not
                # counted as a container with no ports and no data.
                unreadable.append(cname)
                continue
            for bindings in pmap.values():
                for b in bindings or []:
                    hp = str(b.get('HostPort') or '')
                    if hp.isdigit():
                        ports.add(int(hp))
            for mnt in mounts:
                dst = mnt.get('Destination', '')
                if any(dst.startswith(x) for x in _NOT_DATA):
                    continue
                if mnt.get('Type') == 'volume' and mnt.get('Name'):
                    data.add('volume:%s' % mnt['Name'])
                elif mnt.get('Source'):
                    data.add(mnt['Source'])

    cfiles = sorted({f for c in found.values() for f in c['compose_files']})
    return {
        'containers': sorted(found.values(), key=lambda c: c['name']),
        'labelled': sorted(c['name'] for c in found.values() if c['labelled']),
        'published_ports': ports,
        'data': data,
        'compose_files': cfiles,
        'inspect_failed': sorted(unreadable),
    }


# ── the claim, as the project wrote it ───────────────────────────────────────
# Keys this comparator understands. Anything else in the claim is reported as
# UNCHECKED rather than passed over: a claim field nobody compares is a
# statement nobody can be wrong about, which is the failure mode of the
# markdown this replaced.
_CHECKED_KEYS = ('ports', 'port', 'data', 'data_dir', 'data_path', 'volumes',
                 'containers', 'compose', 'compose_file', 'directory', 'dir')
# Recorded by kernel/control, not answerable by the machine. Not a gap.
_NOT_MACHINE_KEYS = ('owner', 'status', 'purpose', 'name', 'project', 'note')


def _claim(project):
    """The claim column, verbatim. kernel/control.registry() drops it on
    purpose (it is per-project), and control.py owns this schema -- so its own
    connection factory is reused rather than reopening CONTROL_DB here, which
    would put the database path in two files."""
    try:
        _ctl.ensure_tables()
        c = _ctl._conn()
        row = c.execute('SELECT claim FROM projects WHERE name=?',
                        (project,)).fetchone()
        c.close()
    except Exception:
        return None
    if row is None:
        return None
    try:
        v = json.loads(row['claim'] or '{}')
        return v if isinstance(v, dict) else {'claim': v}
    except Exception:
        # A claim filed as YAML or prose is still a filed claim. It just cannot
        # be compared field by field, and says so instead of reading as empty.
        return {'_unparsed': row['claim'] or ''}


def _as_list(v):
    if v is None:
        return []
    if isinstance(v, (list, tuple, set)):
        return list(v)
    if isinstance(v, dict):
        return list(v.values())
    return [v]


def _claimed_ports(claim):
    """Accepts 7100, "7100", "7100:3000", "127.0.0.1:7100:3000" and
    "0.0.0.0:7100->3000/tcp" -- the shapes projects actually file. Anything
    else comes back as unparsed rather than silently becoming zero ports
    claimed.

    The HOST port is what this compares, and the two syntaxes put it on
    opposite ends: compose writes HOST:CONTAINER, `docker ps` writes
    IP:HOST->CONTAINER. Taking the last number of both reads "7100:3000" as
    port 3000 -- a claim of 7100 that verifies against nothing.
    """
    out, bad = set(), []
    for v in _as_list(claim.get('ports')) + _as_list(claim.get('port')):
        if isinstance(v, bool):
            continue
        if isinstance(v, int):
            out.add(v)
            continue
        if isinstance(v, dict):
            v = v.get('host') or v.get('published') or v.get('port') or ''
        s = str(v).strip()
        if '->' in s:
            head = s.split('->')[0].split(':')[-1]
        else:
            parts = s.split('/')[0].split(':')
            head = parts[0] if len(parts) == 1 else parts[-2]
        head = head.strip()
        if head.isdigit():
            out.add(int(head))
        elif s:
            bad.append(s)
    return out, sorted(set(bad))


def _claimed_paths(claim):
    out = []
    for k in ('data', 'data_dir', 'data_path', 'volumes'):
        for v in _as_list(claim.get(k)):
            if isinstance(v, dict):
                v = v.get('source') or v.get('path') or ''
            s = str(v).strip()
            if s:
                out.append(s.split(':')[0])
    return sorted(set(out))


def _claimed_containers(claim):
    out = []
    for v in _as_list(claim.get('containers')):
        if isinstance(v, dict):
            v = v.get('name') or ''
        s = str(v).strip()
        if s:
            out.append(s)
    return sorted(set(out))


def _claimed_compose(claim):
    for k in ('compose', 'compose_file', 'directory', 'dir'):
        v = claim.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()
    return ''


# 20313708  _compare — one difference per disagreement, each with its command
def _compare(project, claim, m):
    """Every difference is {claimed, machine, why, fix}.

    `claimed` and `machine` are the IDENTITY kernel/control.record_diffs uses to
    carry a disposition across re-verification, so both are written to be stable
    while the situation is: counts and sorted lists, never timestamps, uptimes
    or iteration order. When the text does change the situation changed, and a
    decision taken about the old one should not silently cover the new one.
    """
    d = []
    found = m['containers']
    n = len(found)
    compose_hint = m['compose_files'][0] if m['compose_files'] else 'the compose file'
    root = _docker_root().rstrip('/')

    # ── Tenancy ──────────────────────────────────────────────────────────────
    if not found:
        d.append({
            'claimed': 'a project deployed on this server',
            'machine': 'no container matches by label, name or compose project',
            'why': 'the claim describes something this host is not running. '
                   'Either it was never deployed here, or it runs under a name '
                   'the claim never mentions -- and a container nothing names '
                   'cannot be backed up, moved or safely deleted.',
            'fix': "docker ps -a --format '{{.Names}} {{.Image}}' | grep -i %s"
                   % project,
        })
    elif not m['labelled']:
        d.append({
            'claimed': 'com.ksg.project=%s on every container' % project,
            'machine': '%d container(s) match by name or compose project, '
                       '0 carry the label' % n,
            'why': 'Constitution VI: `docker ps --filter '
                   'label=com.ksg.project=%s` is the isolation test, and it '
                   'returns 0 of %d. The project is invisible to every tool '
                   'that asks the host what belongs to whom, so backup, '
                   'reclaim and delete all become a human reading names.'
                   % (project, n),
            'fix': 'add `labels: ["com.ksg.project=%s"]` to each service in %s, '
                   'then `docker compose up -d` (recreates the containers)'
                   % (project, compose_hint),
        })
    elif len(m['labelled']) < n:
        missing = sorted(c['name'] for c in found if not c['labelled'])
        d.append({
            'claimed': 'com.ksg.project=%s on every container' % project,
            'machine': '%d of %d labelled; unlabelled: %s'
                       % (len(m['labelled']), n, ', '.join(missing)),
            'why': 'a partly labelled project is worse than an unlabelled one: '
                   'the acceptance test PASSES and returns an incomplete '
                   'answer, so a delete that looks scoped leaves %d container(s) '
                   'behind.' % len(missing),
            'fix': 'add com.ksg.project=%s to %s in %s and recreate'
                   % (project, ', '.join(missing), compose_hint),
        })

    claimed_names = _claimed_containers(claim)
    if claimed_names:
        here = {c['name'] for c in found}
        absent = [c for c in claimed_names if c not in here]
        if absent:
            d.append({
                'claimed': 'containers: %s' % ', '.join(claimed_names),
                'machine': 'not present: %s' % ', '.join(absent),
                'why': 'the claim names containers this host does not have. A '
                       'claim listing more than exists is how a restore gets '
                       'declared complete while a service is still down.',
                'fix': 'refile the claim (POST /api/registry/%s) or bring the '
                       'missing container(s) up' % project,
            })

    # ── Ports ────────────────────────────────────────────────────────────────
    cports, bad = _claimed_ports(claim)
    pub = m['published_ports']
    if pub and not cports:
        d.append({
            'claimed': 'no published port named in the claim',
            'machine': 'publishes %s' % ', '.join(str(p) for p in sorted(pub)),
            'why': 'an unclaimed published port is a port /api/admit believes '
                   'is free and can hand to the next project, which then fails '
                   'to bind on a machine that looked fine.',
            'fix': 'POST /api/registry/%s with {"ports": [%s]}'
                   % (project, ', '.join(str(p) for p in sorted(pub))),
        })
    else:
        extra = sorted(pub - cports)
        gone = sorted(cports - pub)
        if extra:
            d.append({
                'claimed': 'ports %s' % ', '.join(str(p) for p in sorted(cports)),
                'machine': 'also publishes %s' % ', '.join(str(p) for p in extra),
                'why': 'a port bound but not claimed is invisible to admission: '
                       'the band arithmetic is computed from what is claimed, so '
                       'the next project is offered a lane already in use.',
                'fix': 'POST /api/registry/%s naming every published port, or '
                       'stop publishing %s'
                       % (project, ', '.join(str(p) for p in extra)),
            })
        if gone:
            d.append({
                'claimed': 'ports %s' % ', '.join(str(p) for p in sorted(cports)),
                'machine': 'not published: %s' % ', '.join(str(p) for p in gone),
                'why': 'the claim reserves a port nothing is listening on. It '
                       'stays reserved against every other project while '
                       'delivering nothing.',
                'fix': 'refile without %s, or publish it'
                       % ', '.join(str(p) for p in gone),
            })

    floor, ceil = _band()
    if floor and pub:
        outside = sorted(p for p in pub if not floor <= p <= ceil)
        if outside:
            d.append({
                'claimed': "binds inside this server's project band",
                'machine': 'publishes %s, outside %d-%d'
                           % (', '.join(str(p) for p in outside), floor, ceil),
                'why': 'the band is the one lane this server promises not to '
                       'hand to anything else. Outside it the port belongs to '
                       'whoever got there first, which is how a project ends up '
                       'inside a reserved stack lane and nobody finds out until '
                       'both are down.',
                'fix': 'GET /api/admit?project=%s for a free band, rebind, then '
                       'refile the claim' % project,
            })

    # ── Data ─────────────────────────────────────────────────────────────────
    vols = sorted(x for x in m['data'] if x.startswith('volume:'))
    binds = sorted(x for x in m['data'] if not x.startswith('volume:'))
    cpaths = _claimed_paths(claim)
    try:
        dr = _store.data_root()
    except Exception:
        dr = {'path': root, 'dedicated': False}
    droot = (dr.get('path') or root).rstrip('/')

    if vols:
        d.append({
            'claimed': ('data at %s' % ', '.join(cpaths)) if cpaths
                       else 'data at a path on this host',
            'machine': 'data is in named volume(s): %s'
                       % ', '.join(v.split(':', 1)[1] for v in vols),
            'why': 'a named volume lives under /var/lib/docker on the OS disk '
                   'whatever the data disk says, and the backup job copies '
                   'PATHS -- so this data is in no backup and does not travel '
                   "when the project moves. This host's data root is %s."
                   % droot,
            'fix': 'docker run --rm -v %s:/from -v %s/%s/data:/to alpine cp -a '
                   '/from/. /to/   then point the compose mount at the bind and '
                   'recreate' % (vols[0].split(':', 1)[1], droot, project),
        })

    if cpaths and binds:
        stray = [b for b in binds
                 if not any(b.startswith(c.rstrip('/')) for c in cpaths)]
        if stray:
            d.append({
                'claimed': 'data at %s' % ', '.join(cpaths),
                'machine': 'also writes to %s' % ', '.join(sorted(stray)),
                'why': 'a mount outside the claimed data directory is a path no '
                       'backup covers and no reclaim knows to spare, because '
                       'both work from the claim.',
                'fix': 'refile the claim naming every bind, or consolidate '
                       'under %s' % cpaths[0],
            })

    off_root = [b for b in binds
                if not b.startswith(droot) and not b.startswith(root)]
    if off_root and dr.get('dedicated'):
        d.append({
            'claimed': "data on this host's data root (%s)" % droot,
            'machine': 'binds %s' % ', '.join(sorted(off_root)),
            'why': 'this machine has a dedicated data mount and these paths are '
                   'not on it. The OS disk fills while the data disk sits '
                   'empty -- silently, until something cannot write.',
            'fix': 'move the directory under %s and update the compose mount'
                   % droot,
        })

    # ── Compose ──────────────────────────────────────────────────────────────
    expect = '%s/%s' % (root, project)
    off = sorted(f for f in m['compose_files'] if not f.startswith(expect))
    if off:
        d.append({
            'claimed': _claimed_compose(claim) or ('compose under %s' % expect),
            'machine': 'compose file is %s' % ', '.join(off),
            'why': 'the convention is %s, and every tool that rebuilds, backs '
                   'up or inspects a project starts there. A compose file '
                   'somewhere else means the project cannot be brought back by '
                   'anyone who does not already know where it lives.' % expect,
            'fix': 'move the project to %s, or record the real location by '
                   'refiling with {"compose": "%s"}' % (expect, off[0]),
        })
    elif found and not m['compose_files']:
        d.append({
            'claimed': _claimed_compose(claim) or ('compose under %s' % expect),
            'machine': 'containers carry no compose project label -- nothing on '
                       'this host says a compose file built them',
            'why': 'containers started by `docker run` exist until they do not. '
                   'There is no file to re-apply after a reboot, an image '
                   'update or a disk swap.',
            'fix': 'write %s/compose.yaml describing what is running, then '
                   '`docker compose up -d`' % expect,
        })

    if bad:
        d.append({
            'claimed': 'ports %s' % ', '.join(bad),
            'machine': 'not comparable -- could not be read as a port number',
            'why': 'an unreadable claim field is never checked against '
                   'anything, so it can never be wrong. That is the failure '
                   'this exchange exists to end.',
            'fix': 'refile with ports as numbers, e.g. {"ports": [7100]}',
        })

    return d


def _unchecked(claim):
    """Claim keys this comparator did not compare against the machine. Said out
    loud so an unverified field is a visible gap rather than a silence."""
    return sorted(k for k in claim
                  if k not in _CHECKED_KEYS and k not in _NOT_MACHINE_KEYS)


def _store_form(diffs):
    """kernel/control's diffs table has three text columns and none for the fix.
    The command has to survive storage -- a finding read back tomorrow without
    it is the prose this project deleted -- so it is appended to `why` here, in
    one place, while the live response keeps the two separate."""
    return [{'claimed': x['claimed'], 'machine': x['machine'],
             'why': x['why'] + (('  FIX: ' + x['fix']) if x.get('fix') else '')}
            for x in diffs]


# 20313709  POST /api/registry/<project>/verify — the claim, against the machine
def post_registry_verify(handler, path, params, body):
    """# 20313709  POST /api/registry/<project>/verify

    Reports. Never repairs. The response carries the evidence it reasoned from,
    so the conclusion can be checked rather than believed.
    """
    name, _action = _target(path)
    if not name:
        handler.send_json({'ok': False, 'error': 'project name required'}, 400)
        return
    claim = _claim(name)
    if claim is None:
        handler.send_json({'ok': False, 'error': 'not registered', 'who': _who(),
                           'how_to_register': 'POST /api/registry/%s' % name}, 404)
        return

    m = _machine(name)
    if m is None:
        # Nothing is recorded. record_diffs([]) would mark this project verified
        # with zero differences -- an all-clear derived from a machine that was
        # never read, which is the worst answer this endpoint could give.
        handler.send_json({'ok': False, 'error': 'docker_unreadable',
                           'detail': 'docker ps did not answer; nothing was '
                                     'recorded and the previous verification '
                                     'still stands',
                           'who': _who()}, 503)
        return

    diffs = _compare(name, claim, m)
    recorded = _ctl.record_diffs(name, _store_form(diffs))
    log_activity(db_conn, 'registry: %s verified -- %d difference(s)'
                 % (name, recorded), 'registry', 'verify', name,
                 'warn' if recorded else 'info')

    handler.send_json({
        'ok': True, 'project': name, 'who': _who(),
        'differences': diffs,
        'count': recorded,
        # The evidence, not just the verdict -- same reason /api/admit returns
        # the mounts its answer was derived from.
        'machine': {
            'containers': m['containers'],
            'labelled': m['labelled'],
            'published_ports': sorted(m['published_ports']),
            'data': sorted(m['data']),
            'compose_files': m['compose_files'],
            'inspect_failed': m['inspect_failed'],
        },
        'claim_checked': sorted(k for k in claim if k in _CHECKED_KEYS),
        'unchecked': _unchecked(claim),
        'acceptance': 'docker ps --filter label=com.ksg.project=%s' % name,
        'next': 'POST /api/registry/%s/dispose with {"diff_id": N, '
                '"disposition": "fix|accept|defer|hub-wrong"}' % name,
    })


# 20313710  GET /api/registry/<project>/diffs — the differences and their fate
def get_registry_diffs(handler, path, params):
    """# 20313710  GET /api/registry/<project>/diffs

    Stored, not re-derived: the DIFFERENCE is derivable and is re-derived on
    every verify, but the DISPOSITION is a decision somebody made, and a
    decision cannot be read off a machine.
    """
    name, _action = _target(path)
    try:
        _ctl.ensure_tables()
        c = _ctl._conn()
        rows = [dict(r) for r in c.execute(
            'SELECT id,claimed,machine,why,disposition,at FROM diffs '
            'WHERE project=? ORDER BY id', (name,))]
        proj = c.execute('SELECT state,verified_at FROM projects WHERE name=?',
                         (name,)).fetchone()
        c.close()
    except Exception as e:
        handler.send_json({'ok': False, 'error': 'control_db_unreadable',
                           'detail': str(e)}, 500)
        return
    if proj is None:
        handler.send_json({'ok': False, 'error': 'not registered', 'who': _who(),
                           'how_to_register': 'POST /api/registry/%s' % name}, 404)
        return
    open_n = sum(1 for r in rows if not r['disposition'])
    handler.send_json({
        'ok': True, 'project': name, 'who': _who(),
        'state': proj['state'], 'verified_at': proj['verified_at'],
        'diffs': rows, 'open': open_n, 'disposed': len(rows) - open_n,
        # Never verified and verified-with-nothing-wrong are the same empty
        # list. They are not the same thing, and only one is good news.
        'note': ('never verified -- POST /api/registry/%s/verify' % name)
                if not proj['verified_at'] else
                ('reconciled: every difference has a disposition'
                 if rows and not open_n else ''),
    })


# 20313711  POST /api/registry/<project>/dispose — a decision about one diff
def post_registry_dispose(handler, path, params, body):
    """# 20313711  POST /api/registry/<project>/dispose

    Body: {"diff_id": N, "disposition": "fix|accept|defer|hub-wrong"}

    `hub-wrong` is the one that keeps this honest. A project must be able to
    say the server read the machine incorrectly, or verification is an
    interrogation rather than an exchange -- and the hub has been wrong in
    exactly that way before, about which port band it owned.

    Disposing fixes nothing and never runs the command in the finding. It
    records what was decided.
    """
    name, _action = _target(path)
    b = body or {}
    try:
        diff_id = int(b.get('diff_id'))
    except (TypeError, ValueError):
        handler.send_json({'ok': False, 'error': 'diff_id required (integer)',
                           'hint': 'GET /api/registry/%s/diffs' % name}, 400)
        return
    disp = (b.get('disposition') or '').strip().lower()
    # control.dispose runs an UPDATE and cannot tell a decision from a no-op:
    # a diff_id belonging to another project, or to a difference the last
    # verify replaced, would come back "recorded" having changed nothing. A
    # decision nobody stored must not read as a decision made.
    try:
        _ctl.ensure_tables()
        c = _ctl._conn()
        row = c.execute('SELECT id FROM diffs WHERE id=? AND project=?',
                        (diff_id, name)).fetchone()
        c.close()
    except Exception as e:
        handler.send_json({'ok': False, 'error': 'control_db_unreadable',
                           'detail': str(e)}, 500)
        return
    if row is None:
        handler.send_json({'ok': False, 'error': 'no such diff for %s' % name,
                           'diff_id': diff_id,
                           'hint': 'GET /api/registry/%s/diffs -- ids change '
                                   'when a verify replaces the findings' % name},
                          404)
        return
    got, left = _ctl.dispose(name, diff_id, disp)
    if got is None:
        handler.send_json({'ok': False, 'error': left}, 400)
        return
    log_activity(db_conn, 'registry: %s disposed diff %d as %s (%d open)'
                 % (name, diff_id, disp, left), 'registry', 'dispose', name,
                 'info')
    handler.send_json({'ok': True, 'project': name, 'diff_id': diff_id,
                       'disposition': disp, 'open': left, 'who': _who(),
                       'state': 'reconciled' if left == 0 else 'verified',
                       'note': 'recorded, not applied -- the fix in the finding '
                               'is still yours to run'})
