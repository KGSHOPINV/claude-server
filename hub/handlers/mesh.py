#!/usr/bin/env python3
"""
# 20204012  handlers.mesh — heartbeat receiver, registration, fleet view (module 12)

Central-mode endpoints. A node in NODE mode still serves these (same codebase,
one binary) but they stay empty, which is the honest answer: a node has no
fleet, only itself.

Per the FlareVault mesh spec, nodes never talk to each other. Everything here
is nodes reporting UP.
"""
import json
from datetime import datetime

from kernel import fleet as _fleet
from kernel import identity as _id
from kernel.db import db_conn
from kernel.log import log_activity


# 20312701  POST /api/heartbeat — a node reports in
def post_heartbeat(handler, path, params, body):
    """# 20312701  POST /api/heartbeat

    Body is the node's /api/node response, unchanged. Deliberately not a
    bespoke shape: one payload, so what the fleet view shows is exactly what
    the node said about itself, with no lossy translation in between.
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

    handler.send_json({'ok': True, 'server_id': rec['server_id'],
                       'status': rec['status'], 'authenticated': authed,
                       'next_beat_seconds': _fleet.HEARTBEAT_INTERVAL})


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
    """
    handler.send_json({
        'mode':      _id.mode(),
        'self': {
            'server_id':  _id.server_id(),
            'name':       _id.node_name(),
            'machine_id': _id.machine_id(),
        },
        'generated': datetime.now().isoformat(timespec='seconds'),
        'summary':   _fleet.summary(),
        'fleet':     _fleet.fleet(),
    })
