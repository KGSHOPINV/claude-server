#!/usr/bin/env python3
"""
# 20204014  handlers.events_stream — notifications, without a second system

    GET /api/events/stream    Server-Sent Events, live
    GET /api/events/since     catch-up, for a client that was away

WHY NOT ntfy. ntfy is installed on :8085, publicly routed at ntfy.ksgco.app,
correctly locked to deny-all -- and silent, because the hub has no token for it.
Its own counter says messages_published=0. It has sat there working perfectly
and delivering nothing.

Using it means a second auth system, a second config file, a second thing that
can be misconfigured without saying so. The hub already has the events, already
has the session, and is already the origin the PWA loads from. One origin, one
session, one place a notification can fail.

ntfy keeps ONE advantage worth remembering: it reaches a phone when nothing is
open, because it has native apps holding a background connection. This does not
replace that, and it is not trying to. What it replaces is the part where a
notification has to leave the hub and come back.

THE THREE LAYERS, and only the middle one is new:

    HOLDING     activity_log. Already exists, already written to. Nothing is
                lost when nobody is listening -- which is the whole reason a
                stream can be this simple.
    LIVE        this file. An open PWA holds one connection and sees events
                the moment they land.
    BACKGROUND  a phone with nothing open. Still ntfy's job, later.

SSE rather than WebSocket deliberately: it is one-directional, which is all a
notification needs; it is plain HTTP, so it crosses the Cloudflare tunnel with
no special handling; and EventSource reconnects on its own. A WebSocket would
be more capable and more to go wrong.
"""
import json
import time

from kernel.db import db_conn

# How often the server looks for new rows. Not a poll from the client -- the
# client holds one connection open and is pushed to. Two seconds is under the
# threshold where a person would call it delayed, and cheap: one indexed
# SELECT against a local SQLite file.
# ── What this thing IS ────────────────────────────────────────────────────────
# It is four files and one table. Nothing else. That is deliberate: a
# notification path you cannot lift out in an afternoon is a notification path
# you will not fix at 2am.
#
# It reads activity_log and writes nothing. It holds no state of its own, no
# config file, no second database, no credential. Delete these four files and
# the hub loses notifications and nothing else -- no other feature calls into
# here. That is the test of whether it is really separate, and it passes.
#
# TO LIFT IT TO ITS OWN REPO: the only hub-specific line in this file is the
# db_conn import. Swap that for any callable returning a DB-API connection over
# a table with (id, ts, source, category, action, detail, level) and the rest
# moves unchanged. The two JS files have no hub dependency at all.
NAME    = 'events-stream'
VERSION = '1.0.0'
DEPENDS = ['activity_log table', 'kernel.db.db_conn', 'kernel.router (2 routes)']

PARTS = [
    {'file': 'handlers/events_stream.py', 'code': '20204014', 'role': 'server: the two endpoints',
     'without_it': 'no stream at all'},
    {'file': 'ui/sw.js', 'code': '20301704', 'role': 'service worker: owns showNotification, makes the app installable',
     'without_it': 'stream works, no OS notification, no "Install app"'},
    {'file': 'ui/notify.js', 'code': '20301711', 'role': 'client: registers the worker, holds the connection, catches up',
     'without_it': 'endpoints exist and nothing calls them'},
    {'file': 'app.html', 'code': '20301716', 'role': 'the Enable button — permission needs a user gesture',
     'without_it': 'permission can never be asked for'},
]


TICK = 2.0

# A connection is closed after this and EventSource reconnects by itself. A
# stream held open forever accumulates half-dead sockets behind a proxy that
# has already given up on its end.
MAX_SECONDS = 600

# Below this, nothing is delivered. 'info' is the firehose -- every container
# start, every port appearing -- and a notification stream that fires constantly
# gets muted, which is the same as not having one.
LEVELS = {'info': 0, 'warn': 1, 'high': 2, 'error': 2, 'critical': 3}
DEFAULT_MIN = 'warn'


def _rows_after(last_id, min_level):
    floor = LEVELS.get(min_level, 1)
    try:
        conn = db_conn()
        rows = conn.execute(
            'SELECT id, ts, source, category, action, detail, level '
            'FROM activity_log WHERE id > ? ORDER BY id LIMIT 50',
            (last_id,)).fetchall()
        conn.close()
    except Exception:
        return []
    out = []
    for r in rows:
        if LEVELS.get(r['level'], 0) < floor:
            continue
        out.append({'id': r['id'], 'ts': r['ts'], 'source': r['source'],
                    'category': r['category'], 'action': r['action'],
                    'detail': r['detail'], 'level': r['level']})
    return out


def _last_id():
    try:
        conn = db_conn()
        r = conn.execute('SELECT MAX(id) m FROM activity_log').fetchone()
        conn.close()
        return r['m'] or 0
    except Exception:
        return 0


# 20314701  GET /api/events/stream — one open connection, events pushed down it
def get_events_stream(handler, path, params):
    """# 20314701  GET /api/events/stream

    Params:
      since=<id>     resume from an id the client already has
      level=<name>   minimum level, default warn

    The client sends the last id it saw, so a reconnect loses nothing: the rows
    are in activity_log whether anyone was listening or not. That is what makes
    a dropped connection a non-event instead of a lost notification.
    """
    try:
        last = int(params.get('since') or 0)
    except Exception:
        last = 0
    if not last:
        # A client with no history should not be buried in backlog on connect.
        last = _last_id()
    min_level = (params.get('level') or DEFAULT_MIN).lower()

    try:
        handler.send_response(200)
        handler.send_header('Content-Type', 'text/event-stream')
        handler.send_header('Cache-Control', 'no-cache')
        handler.send_header('Connection', 'keep-alive')
        # Buffering is what silently breaks SSE behind a proxy: events arrive
        # in a clump minutes late, or never. Say no explicitly.
        handler.send_header('X-Accel-Buffering', 'no')
        handler.end_headers()
    except Exception:
        return

    def send(event, data):
        try:
            handler.wfile.write(
                ('event: %s\ndata: %s\n\n' % (event, json.dumps(data))).encode())
            handler.wfile.flush()
            return True
        except Exception:
            return False          # client went away; that is normal, not an error

    if not send('open', {'since': last, 'level': min_level, 'tick': TICK}):
        return

    started = time.time()
    while time.time() - started < MAX_SECONDS:
        rows = _rows_after(last, min_level)
        for r in rows:
            last = r['id']
            if not send('activity', r):
                return
        if not rows:
            # A comment line keeps the connection alive through a proxy that
            # would otherwise drop it as idle. It is not an event and no client
            # sees it.
            try:
                handler.wfile.write(b': keepalive\n\n')
                handler.wfile.flush()
            except Exception:
                return
        time.sleep(TICK)

    send('bye', {'reason': 'max duration', 'since': last})


# 20314702  GET /api/events/since — catch-up for a client that was away
def get_events_since(handler, path, params):
    """# 20314702  GET /api/events/since?id=<n>&level=<name>

    The PWA calls this on wake with the last id it holds, then opens the
    stream. Between them nothing is missed, because activity_log kept the rows
    while nobody was connected.
    """
    try:
        last = int(params.get('id') or 0)
    except Exception:
        last = 0
    min_level = (params.get('level') or DEFAULT_MIN).lower()
    rows = _rows_after(last, min_level)
    handler.send_json({'events': rows,
                       'last_id': rows[-1]['id'] if rows else last,
                       'level': min_level,
                       'head': _last_id()})


# 20314703  GET /api/events/self — the part that checks itself
def get_events_self(handler, path, params):
    """# 20314703  GET /api/events/self

    Every part of this, whether it is actually there, and what breaks if it is
    not. REPORTS, NEVER REPAIRS -- a notification path that silently patches
    itself is one you cannot trust to tell you when it is broken, which is the
    only job it has.

    This is why the unit is worth keeping separate: one call says whether
    notifications can possibly work, without reading any other part of the hub.
    """
    import os
    hub = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    parts = []
    for p in PARTS:
        full = os.path.join(hub, p['file'])
        d = dict(p)
        d['present'] = os.path.isfile(full)
        d['bytes'] = os.path.getsize(full) if d['present'] else 0
        # app.html is shared, so its presence proves nothing -- look for the
        # function this unit actually needs it to contain.
        if p['file'] == 'app.html' and d['present']:
            try:
                with open(full, encoding='utf-8', errors='ignore') as f:
                    src = f.read()
                d['present'] = 'enableNotifications' in src and 'ui/notify.js' in src
                if not d['present']:
                    d['note'] = 'file exists but is not wired: needs the notify.js tag and enableNotifications()'
            except Exception:
                pass
        parts.append(d)

    holding = {'table': 'activity_log', 'ok': False, 'rows': 0, 'head': 0}
    try:
        conn = db_conn()
        holding['rows'] = conn.execute('SELECT COUNT(*) n FROM activity_log').fetchone()['n']
        conn.close()
        holding['head'] = _last_id()
        holding['ok'] = True
    except Exception as e:
        holding['error'] = str(e)

    broken = [p for p in parts if not p['present']]
    handler.send_json({
        'name': NAME, 'version': VERSION, 'depends': DEPENDS,
        'parts': parts,
        'holding': holding,
        'layers': {
            'holding': 'activity_log — kept whether anyone is listening',
            'live': 'this unit — delivers while the hub is open or installed',
            'background': 'NOT BUILT — a fully closed app needs Web Push and VAPID keys',
        },
        'ok': not broken and holding['ok'],
        'verdict': ('all parts present' if not broken and holding['ok']
                    else '; '.join([p['file'] + ': ' + p['without_it'] for p in broken]
                                   or ['activity_log unreadable'])),
    })
