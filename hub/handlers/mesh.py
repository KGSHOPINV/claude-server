#!/usr/bin/env python3
"""
# 20204012  handlers.mesh — heartbeat receiver, registration, fleet view (module 12)

Central-mode endpoints. A node in NODE mode still serves these (same codebase,
one binary) but they stay empty, which is the honest answer: a node has no
fleet, only itself. The one exception is /api/mesh/registry, where "only
itself" is a row rather than nothing — a machine always knows what it runs.

Per the FlareVault mesh spec, nodes never talk to each other. Everything here
is nodes reporting UP.

Cross-server visibility rides that same beat rather than opening a second
channel: a node may attach a `registry` block to its heartbeat, and central
serves every node's block from one address. This costs no new reachability,
which matters because the two servers currently sit on different tailnets and
cannot reach each other at all — the beat is the only wire there is.
"""
import json
import threading
from datetime import datetime, timezone

from kernel import control as _ctl
from kernel import fleet as _fleet
from kernel import identity as _id
from kernel.db import db_conn
from kernel.log import log_activity
# Borrowed rather than re-derived. "Which ref is this server on" already has
# one answer in handlers/registry; a second `git rev-parse` here would be a
# second source for one question, which is the bug this file is checking for.
from handlers.registry import _master as _central_ref

# server_id -> the registry SUMMARY that node last sent. Only what a node
# alone can answer is kept; see _record_registry for what is deliberately
# dropped. Bounded by the fleet, since nothing lands here that _fleet.heartbeat
# did not already accept, and lost on restart like the fleet itself — one beat
# interval of blindness, not a rebuild.
_registries = {}
_reg_lock = threading.Lock()


def _now():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


# 20312704  _count — a malformed number from a node must not take a route down
def _count(value, fallback):
    """Counts arrive over the network from a machine central does not control.
    A node sending "12" or null is a bug on that node; a 500 here would turn
    one node's bug into the whole fleet view going dark.
    """
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return fallback


# 20312705  _record_registry — what central keeps from a beat, and what it drops
def _record_registry(server_id, block):
    """Returns (record, previous_ref), or (None, None) if there was no block.

    Deliberately lossy. The claims themselves are NOT copied here: central
    holding a second copy of data the node owns is the two-sources bug this
    project spent a fortnight deleting, and between beats that copy would be
    wrong besides. What is kept is only what cannot be asked of a node central
    cannot reach — how many projects it carries, how many have not been told
    what it is running, and the ref, which is the one field drift may compare.
    """
    if not isinstance(block, dict):
        return None, None
    projects = []
    for p in block.get('projects') or []:
        if isinstance(p, dict):
            projects.append({'name':   str(p.get('name', '')),
                             'status': str(p.get('status', '')),
                             'stale':  bool(p.get('stale'))})
    # /api/registry calls this field `master`; the heartbeat calls it `ref`.
    # Both are accepted rather than making one side rename a field it already
    # publishes — a rename is a flag day across two machines for no gain.
    ref = str(block.get('ref') or block.get('master') or '').strip()
    rec = {
        'ref': ref,
        # The node's own count wins over a recount of the list it sent. A node
        # that truncated the list still knows its true total, and a recount
        # here would quietly disagree with the node about the node.
        'projects': _count(block.get('project_count'), len(projects)),
        'stale':    _count(block.get('stale_count'),
                           sum(1 for p in projects if p['stale'])),
        'list':     projects,
        'at':       _now(),
    }
    with _reg_lock:
        prior = _registries.get(server_id) or {}
        _registries[server_id] = rec
    return rec, prior.get('ref') or ''


# 20312706  _congruence — the drift rule, and the one field it is allowed to read
def _congruence(node_ref, central_ref):
    """Congruence is SAME CODE REF. It is never same values.

    ksgcohub derives /srv/data; fks-services derives /srv/docker and /backup.
    Those disagree because each machine was read correctly — identical values
    across the fleet would mean the derivation is broken, not that the fleet
    agrees. So nothing but the ref is ever compared.

    A node that has never reported a ref is 'unknown', not congruent. Reading
    silence as agreement is the monitor lying instead of alarming, which is the
    failure `_derive_status` exists to avoid one layer down.
    """
    if not node_ref or not central_ref:
        return 'unknown'
    return 'congruent' if node_ref == central_ref else 'drift'


# 20312707  _age — how old the beat behind a cached summary is
def _age(iso):
    """A cached summary must carry its age or it reads as live. Negative ages
    (clock skew between node and central) clamp to 0, the same clamp fleet
    applies, so skew cannot present as a fresher report than exists.
    """
    try:
        return max(0, int((datetime.now(timezone.utc)
                           - datetime.fromisoformat(iso)).total_seconds()))
    except Exception:
        return None


# 20312708  _self_entry — this machine's own row, derived at call time
def _self_entry(ref):
    """Central runs projects too, and in NODE mode this is the only row there
    is. Derived live from the control database rather than from a beat, which
    is why its source differs from every other row and says so.
    """
    entry = {
        'server_id':  _id.server_id(),
        'name':       _id.node_name(),
        'self':       True,
        'status':     'self',
        'ref':        ref,
        'congruence': 'self',
        'source':     'derived',
        # Reporting, with age 0: this row was read now, not remembered. Same
        # keys as every other row so the UI has one shape to render.
        'reporting':   True,
        'reported_at': None,
        'age_seconds': 0,
    }
    try:
        reg = _ctl.registry(ref)
        projects = [{'name': p.get('name', ''), 'status': p.get('status', ''),
                     'stale': bool(p.get('stale'))} for p in reg['projects']]
        entry['projects'] = len(projects)
        entry['stale'] = sum(1 for p in projects if p['stale'])
        entry['list'] = projects
    except Exception as e:
        # A local database that cannot be read is a finding, not a blank row.
        # Reporting zero projects here would be indistinguishable from a
        # machine that genuinely has none.
        entry['error'] = 'control db unreadable: %s' % e
        entry['fix'] = 'python3 -c "from kernel import control; control.ensure_tables()"'
    return entry


# 20312701  POST /api/heartbeat — a node reports in
def post_heartbeat(handler, path, params, body):
    """# 20312701  POST /api/heartbeat

    Body is the node's /api/node response, unchanged. Deliberately not a
    bespoke shape: one payload, so what the fleet view shows is exactly what
    the node said about itself, with no lossy translation in between.

    One OPTIONAL addition: a `registry` block — {ref, project_count,
    stale_count, projects:[{name,status,stale}]}. Optional in both directions.
    A node whose build predates it still beats normally and is reported as not
    reporting a registry, which is different from having no projects and must
    stay different.
    """
    if not _id.is_central():
        # Not an error — a node simply is not an aggregator. Say so plainly
        # rather than silently accepting and dropping.
        handler.send_json({'ok': False, 'error': 'not_central',
                           'mode': _id.mode()}, 409)
        return

    src = params.get('path') or 'unknown'
    # Authentication is FlareVault's to provide (join tokens). Until then the
    # receiver records whether a beat was authenticated rather than pretending
    # it was. An unauthenticated mesh accepts rogue nodes; this at least makes
    # that visible instead of invisible.
    authed = False
    tok = handler.headers.get('X-Flare-Token', '')
    if tok:
        authed = _id.verify(tok) is not None

    rec, event = _fleet.heartbeat(body or {}, path=src, authenticated=authed)
    if rec is None:
        handler.send_json({'ok': False, 'error': event}, 400)
        return
    if event:
        log_activity(db_conn, event, 'mesh', 'fleet', rec.get('server_id', ''), 'info')

    # Recorded only for a beat the fleet already accepted, so an unknown
    # server_id cannot grow this table behind the fleet's back.
    reg, prev_ref = _record_registry(rec['server_id'], (body or {}).get('registry'))
    central = _central_ref()
    congruence = _congruence(reg['ref'] if reg else '', central)
    if reg and prev_ref and prev_ref != reg['ref']:
        # A node changing ref is an event; a node SITTING on a different ref is
        # a state, and logging a state every 30s buries the events. So this
        # fires on the transition only.
        log_activity(db_conn,
                     'mesh: %s moved %s -> %s' % (rec.get('name') or rec['server_id'],
                                                  prev_ref[:7], reg['ref'][:7]),
                     'mesh', 'fleet', rec['server_id'],
                     'warn' if congruence == 'drift' else 'info')

    handler.send_json({'ok': True, 'server_id': rec['server_id'],
                       'status': rec['status'], 'authenticated': authed,
                       'next_beat_seconds': _fleet.HEARTBEAT_INTERVAL,
                       # Told back to the node, because the node is the one
                       # that can act on it: it learns central's ref without a
                       # second request, on a wire it already has.
                       'registry': {'recorded': reg is not None,
                                    'congruence': congruence,
                                    'central_ref': central}})


# 20312702  POST /api/mesh/register — a node joins
def post_mesh_register(handler, path, params, body):
    """# 20312702  POST /api/mesh/register"""
    if not _id.is_central():
        handler.send_json({'ok': False, 'error': 'not_central',
                           'mode': _id.mode()}, 409)
        return
    b = body or {}
    rec, note = _fleet.register(
        b.get('server_id', ''), b.get('name', ''),
        b.get('machine_id', ''), b.get('reachability'))
    if rec is None:
        handler.send_json({'ok': False, 'error': note}, 400)
        return
    msg = f'mesh register: {rec["name"] or rec["server_id"]}'
    if note:
        msg += f' — {note}'
    log_activity(db_conn, msg, 'mesh', 'fleet', rec['server_id'],
                 'warn' if note else 'info')
    handler.send_json({'ok': True, 'server_id': rec['server_id'],
                       'status': rec['status'], 'note': note})


# 20312703  GET /api/mesh/fleet — the whole fleet, for the UI
def get_mesh_fleet(handler, path, params):
    """# 20312703  GET /api/mesh/fleet

    On a node this returns an empty fleet and mode:node — which is the truthful
    answer, and lets one UI talk to either without branching.

    Each node also carries its `congruence`: congruent, drift or unknown. That
    is a ref comparison and nothing else — a node reporting different paths and
    different disks from central is a node deriving correctly, not a node out
    of step.
    """
    ref = _central_ref()
    with _reg_lock:
        snap = {k: dict(v) for k, v in _registries.items()}

    f = _fleet.fleet()
    drift = 0
    for sid, rec in f.items():
        rec['ref'] = (snap.get(sid) or {}).get('ref', '')
        rec['congruence'] = _congruence(rec['ref'], ref)
        if rec['congruence'] == 'drift':
            drift += 1

    summary = _fleet.summary()
    summary['ref'] = ref
    summary['drift'] = drift

    handler.send_json({
        'mode':      _id.mode(),
        'self': {
            'server_id':  _id.server_id(),
            'name':       _id.node_name(),
            'machine_id': _id.machine_id(),
            'ref':        ref,
        },
        'generated': datetime.now().isoformat(timespec='seconds'),
        'summary':   summary,
        'fleet':     f,
    })


# 20312709  GET /api/mesh/registry — what runs where, across the fleet
def get_mesh_registry(handler, path, params):
    """# 20312709  GET /api/mesh/registry

    One address answering, for every node: what it runs, and which of its
    projects have not been told what their server is running.

    In NODE mode this returns exactly one entry — itself — rather than an
    error, the same way /api/mesh/fleet returns an empty fleet. One UI talks to
    either without branching, and a node answering "here is me" is not a
    degraded version of the fleet answer; it is the true one for a machine with
    no fleet.

    Every row but this machine's is AS OF that node's last beat, and says so
    with age_seconds. A cached summary presented as live is how a monitor ends
    up describing a node that stopped reporting an hour ago.
    """
    ref = _central_ref()
    with _reg_lock:
        snap = {k: dict(v) for k, v in _registries.items()}

    self_id = _id.server_id()
    nodes = [_self_entry(ref)]

    # A summary older than the unreachable threshold is stale by the same rule
    # the fleet already uses for status. One threshold, not a second opinion.
    stale_after = _fleet.HEARTBEAT_INTERVAL * _fleet.UNREACHABLE_AFTER

    for sid, rec in _fleet.fleet().items():
        if sid == self_id:
            continue                       # central does not beat to itself
        reg = snap.get(sid)
        name = rec.get('name') or sid
        entry = {
            'server_id':   sid,
            'name':        name,
            'self':        False,
            'status':      rec.get('status', ''),
            'source':      'heartbeat',
            'ref':         (reg or {}).get('ref', ''),
            'reported_at': (reg or {}).get('at'),
        }
        entry['congruence'] = _congruence(entry['ref'], ref)
        if reg is None:
            # Not zero projects. Nothing was ever said, and the difference
            # between "none" and "never told" is the whole point of stale.
            entry['reporting'] = False
            entry['projects'] = None
            entry['stale'] = None
            entry['list'] = []
            entry['fix'] = ('%s beats without a registry block — deploy %s there '
                            'and restart its hub' % (name, ref or 'the current ref'))
        else:
            age = _age(reg['at'])
            entry['reporting'] = True
            entry['projects'] = reg['projects']
            entry['stale'] = reg['stale']
            entry['list'] = reg['list']
            entry['age_seconds'] = age
            entry['report_stale'] = age is not None and age > stale_after
        if entry['congruence'] == 'drift':
            # Report, never repair: the command is here, and running it is a
            # human's decision. Central cannot know which of the two refs is
            # the one that should win.
            entry['fix'] = ('git log --oneline %s..%s  (in the hub checkout) '
                            'shows what %s has not got' % (entry['ref'], ref, name))
        nodes.append(entry)

    reporting = [n for n in nodes if n.get('projects') is not None]
    handler.send_json({
        'mode':      _id.mode(),
        'ref':       ref,
        'generated': datetime.now().isoformat(timespec='seconds'),
        'summary': {
            'nodes':        len(nodes),
            'reporting':    len(reporting),
            # Summed only over nodes that actually reported. Counting a silent
            # node as zero would make the fleet total shrink when a node goes
            # quiet, which reads as good news.
            'projects':     sum(n.get('projects') or 0 for n in reporting),
            'stale':        sum(n.get('stale') or 0 for n in reporting),
            'drift':        sum(1 for n in nodes if n['congruence'] == 'drift'),
            'unknown_ref':  sum(1 for n in nodes if n['congruence'] == 'unknown'),
            'stale_after_seconds': stale_after,
        },
        'nodes': nodes,
    })
