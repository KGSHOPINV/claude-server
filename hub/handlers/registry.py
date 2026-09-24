#!/usr/bin/env python3
"""
# 20204013  handlers.registry — the endpoints a project talks to (module 13)

Every part of this existed as markdown first. A project cannot POST to a
document, cannot be told its master moved, and cannot acknowledge anything.
These are the same design, running.

    GET  /api/registry              everything on THIS server
    GET  /api/registry/<project>    one project's standing record
    POST /api/registry/<project>    file or refile a claim
    POST /api/ack/<project>         acknowledge the server's master

Scoped to one server by construction. The rules a project is given are derived
from THIS host's disks and THIS host's bound ports, so the same project on the
other machine is a different record with different values -- which is correct,
not duplication.

Cross-server comes free later: a node's heartbeat already carries its payload
to central, so central can serve the other server's registry without either box
reaching the other's network.
"""
import json
import subprocess

from kernel import control as _ctl
from kernel import identity as _id
from kernel.db import db_conn
from kernel.log import log_activity


def _master():
    """The code ref this server is running. Derived, never stored -- a stored
    copy would be the exact drift this whole system exists to catch."""
    try:
        r = subprocess.run(['git', 'rev-parse', '--short', 'HEAD'],
                           capture_output=True, text=True, timeout=5)
        return r.stdout.strip() if r.returncode == 0 else ''
    except Exception:
        return ''


def _who():
    return {'node': _id.node_name(), 'server_id': _id.server_id(),
            'master': _master(), 'mode': _id.mode()}


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
    name = path.rsplit('/', 1)[-1].strip().lower()
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
    name = path.rsplit('/', 1)[-1].strip().lower()
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
