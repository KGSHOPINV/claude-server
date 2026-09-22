#!/usr/bin/env python3
"""
# 20200011  kernel.fleet — the fleet registry and status state machine (central)

Hub-and-spoke, per the FlareVault mesh spec (2026-09-22):

    node -> central    heartbeat, pushed every 30s
    central -> node    console proxy, on demand when a user drills in
    node -> node       NEVER. No lateral mesh.

Central is the only aggregator. If central goes down the nodes keep running,
they just cannot report; when it returns they resume. No split-brain, because
there is only ever one writer of fleet state.

Status is DERIVED from last_seen on every read rather than written by a
sweeper. A timer that stops running would otherwise leave every node frozen at
"healthy" — the failure mode where the monitor lies rather than alarms.

In-memory for now. SQLite persistence later; losing the registry on restart
costs one heartbeat interval, since every node re-reports within 30s.
"""
import threading
import time
from datetime import datetime, timezone

HEARTBEAT_INTERVAL = 30          # seconds; nodes push on this cadence
DEGRADED_AFTER = 3               # missed beats
UNREACHABLE_AFTER = 6            # missed beats

ENROLLING = 'enrolling'
HEALTHY = 'healthy'
DEGRADED = 'degraded'
UNREACHABLE = 'unreachable'
RECOVERING = 'recovering'

_fleet = {}                      # server_id -> record
_lock = threading.Lock()


def _now():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


# 20200331  register — a node joins the mesh
def register(server_id, name, machine_id, reachability=None):
    """Returns (record, note). `note` flags anything an operator should see.

    Two checks worth making at join time, both cheap and both catching real
    situations: a known server_id re-registering (a reimage or a restart), and
    a known machine_id arriving under a DIFFERENT server_id — the same physical
    box claiming a new identity, which is either a legitimate reprovision or
    something worth asking about.
    """
    if not server_id:
        return None, 'server_id required'
    note = None
    with _lock:
        prior = _fleet.get(server_id)
        if prior:
            note = 're-registration of a known server_id'
        else:
            for sid, rec in _fleet.items():
                if machine_id and rec.get('machine_id') == machine_id:
                    note = (f'machine_id already registered as {sid} — same hardware, '
                            f'new server_id (reimage or reprovision?)')
                    break
        rec = prior or {}
        rec.update({
            'server_id':    server_id,
            'name':         name or rec.get('name', ''),
            'machine_id':   machine_id or rec.get('machine_id', ''),
            'reachability': reachability or rec.get('reachability', []),
            'registered':   rec.get('registered', _now()),
            'status':       rec.get('status', ENROLLING),
            'last_seen':    rec.get('last_seen'),
            'path':         rec.get('path'),
            'misses':       rec.get('misses', 0),
        })
        _fleet[server_id] = rec
        return dict(rec), note


# 20200332  heartbeat — record a beat, return any transition worth logging
def heartbeat(payload, path='unknown', authenticated=False):
    """payload is the node's /api/node response, unchanged.

    Returns (record, event) where event is a human-readable transition, or
    None. Two things are events: a status change, and a PATH change — a node
    that fell back from cloudflare to tailscale is still up, but the fact it
    had to is exactly the sort of quiet degradation that otherwise goes unseen.
    """
    sid = payload.get('server_id') or payload.get('machine_id')
    if not sid:
        return None, 'heartbeat without server_id or machine_id — ignored'

    with _lock:
        rec = _fleet.get(sid, {
            'server_id': sid, 'registered': _now(), 'status': ENROLLING, 'misses': 0,
        })
        prev_status = rec.get('status', ENROLLING)
        prev_path = rec.get('path')

        # Coming back from a bad state announces itself once, then settles.
        if prev_status in (DEGRADED, UNREACHABLE):
            new_status = RECOVERING
        else:
            new_status = HEALTHY

        attention = payload.get('attention') or {}
        flags = []
        for c in attention.get('unassigned_containers', []) or []:
            flags.append(f'unassigned: {c}')
        if attention.get('not_enrolled'):
            flags.append('not enrolled')

        reach = [k for k, v in (
            ('lan', payload.get('local_ip')),
            ('tailscale', payload.get('tailscale_ip')),
            ('public', payload.get('public')),
        ) if v]

        rec.update({
            'name':          payload.get('node') or payload.get('hostname') or rec.get('name', ''),
            'machine_id':    payload.get('machine_id', rec.get('machine_id', '')),
            'status':        new_status,
            'last_seen':     _now(),
            'path':          path,
            'authenticated': authenticated,
            'reachability':  reach,
            'containers':    sum(len(p.get('containers', [])) for p in payload.get('projects', [])),
            'projects':      len(payload.get('projects', [])),
            'attention':     flags,
            'os':            payload.get('os', ''),
            'uptime':        payload.get('uptime', ''),
            'misses':        0,
        })
        _fleet[sid] = rec

        event = None
        if prev_status != new_status:
            event = f'{rec["name"] or sid}: {prev_status} -> {new_status}'
        elif prev_path and prev_path != path:
            event = f'{rec["name"] or sid}: heartbeat path changed {prev_path} -> {path}'
        return dict(rec), event


# 20200333  _derive_status — staleness decides status, computed at read time
def _derive_status(rec):
    last = rec.get('last_seen')
    if not last:
        return rec.get('status', ENROLLING), 0
    try:
        seen = datetime.fromisoformat(last)
        age = (datetime.now(timezone.utc) - seen).total_seconds()
    except Exception:
        return rec.get('status', ENROLLING), 0
    # Clamp: a future-dated last_seen (clock skew between node and central)
    # would otherwise yield negative misses and silently report healthy.
    missed = max(0, int(age // HEARTBEAT_INTERVAL))
    if missed >= UNREACHABLE_AFTER:
        return UNREACHABLE, missed
    if missed >= DEGRADED_AFTER:
        return DEGRADED, missed
    # A node that reported while RECOVERING settles to HEALTHY on the next read.
    if rec.get('status') == RECOVERING:
        return HEALTHY, missed
    return rec.get('status', HEALTHY), missed


# 20200334  fleet — full state for the UI
def fleet():
    out = {}
    with _lock:
        items = list(_fleet.items())
    for sid, rec in items:
        r = dict(rec)
        status, missed = _derive_status(rec)
        r['status'] = status
        r['missed_beats'] = missed
        out[sid] = r
    return out


def summary():
    f = fleet()
    counts = {}
    for r in f.values():
        counts[r['status']] = counts.get(r['status'], 0) + 1
    return {
        'nodes': len(f),
        'by_status': counts,
        'interval': HEARTBEAT_INTERVAL,
        'degraded_after': DEGRADED_AFTER,
        'unreachable_after': UNREACHABLE_AFTER,
    }
