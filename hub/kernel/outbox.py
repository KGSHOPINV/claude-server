#!/usr/bin/env python3
"""
# 20200017  kernel.outbox — the server's outbound side, staged and tracked

THE HOLE THIS FILLS. `hub/plan/BUILT-VS-ASKED.md` names it as build-order item
1: there is no outbound at all. The intake message in `hub/INTAKE.md` is a
paragraph the operator copies into a session by hand, which means the operator
IS the transport, and every step after it in THE-PLAN sits over that hole.

    "DID I NOT SETUP THIS EXCANGE FO U TO USE THE SERVER TO COMMUINCTE WITH A
     GIVEN PROJECT YES OR NO"

So: outbound exists, it goes through the server, and it fires when the operator
asks. The other half of that rule is the one that broke a session -- messages
went out that nobody asked for -- so nothing in this file sends anything on its
own. A message exists because someone POSTed it. Full stop.

WHY THIS IS A QUEUE A PROJECT COLLECTS, AND NOT A DELIVERY

    "I WANT ALWAYS ISOLATION FROM PROJECT PERIOD"

The server does not reach into a project. It does not exec into a container, it
does not read a project's socket, it does not discover an address by inspecting
Docker. If it did any of those, the isolation rule would be a wish and the
mechanism would be the thing breaking it.

What it does instead is what a post office does: the message is ADDRESSED to a
project, STAGED on the server, and the project COLLECTS it. Collection is the
project's own act, over the same authenticated URL it already uses for
bulletins and tickets.

The optional second leg -- an HTTP POST to a callback URL -- exists only for a
project that REGISTERED that URL itself. The hub never derives an address, and
`outbox_addresses` is the only place one can come from. A project handing over
its own doorbell is not the server reaching in; a server scanning for the
doorbell would be.

STAGED IS NOT DELIVERED. This is the whole discipline of the file.

    staged      it is on the server, addressed. Nobody has taken it.
    collected   the project fetched it (pull), or its own callback returned 2xx
    acked       the project said what it will DO about it
    failed      the OPTIONAL push leg failed. Loudly. The message is still
                staged and still collectable -- 'failed' describes the push,
                never the message.

A message nobody collected must never read as sent. That is why state is
DERIVED from the timestamps in the row (see _state) and never stored as a
column: a status column is a second write, and the second write is the one that
gets forgotten.

SCHEMA OWNERSHIP. control.py owns projects/acks/releases/diffs and the exchange
tables. This file owns the three below and nothing else. It reuses
control._conn() rather than reopening CONTROL_DB, for the same reason
handlers/registry.py:_claim does: two copies of a database path is two
databases the day one of them is edited.
"""
import json
import os
import re
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime

from kernel import control as _ctl

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INTAKE_PATH = os.path.join(BASE_DIR, 'INTAKE.md')

# The push leg. Bounded on purpose: a retry loop with no ceiling turns one
# unreachable project into a permanent outbound load and hides the failure in
# noise. After PUSH_MAX_ATTEMPTS the worker gives up on the PUSH and says so --
# the message stays staged, because the pull path never needed the push.
PUSH_TIMEOUT = 8
PUSH_MAX_ATTEMPTS = 3
WORKER_INTERVAL = 20

KINDS = ('intake', 'reply', 'note')


def _conn():
    return _ctl._conn()


def _now():
    return datetime.now().isoformat(timespec='seconds')


# 20200501  ensure_outbox — one schema owner, same rule as control.ensure_tables
def ensure_outbox():
    c = _conn()
    # The message itself. collected_at is written ONCE and never overwritten --
    # see collect(). A project that fetches twice must not be able to erase the
    # record of the first time, because "when did it first have this" is the
    # question the whole table exists to answer.
    c.execute("""CREATE TABLE IF NOT EXISTS outbox (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        project TEXT NOT NULL,            -- who it is addressed to
        kind TEXT DEFAULT 'intake',       -- intake | reply | note
        subject TEXT,
        body TEXT NOT NULL,               -- the payload, verbatim, never edited
        expects TEXT,                     -- what is owed back, in words
        staged_at TEXT,
        staged_by TEXT,                   -- who pressed it. Never 'system'.
        collected_at TEXT,                -- FIRST collection only
        collected_via TEXT,               -- pull | push
        collect_count INTEGER DEFAULT 0,
        acked_at TEXT,
        ack_note TEXT,
        push_attempts INTEGER DEFAULT 0,
        push_error TEXT                   -- last failure, kept verbatim
    )""")
    # Append-only, exactly like control.acks. What a project was told, and what
    # happened when we tried to tell it, is EVIDENCE -- not state to update.
    # A failed push that was later retried successfully must still show the
    # failure, or the second attempt is the only thing anyone ever sees.
    c.execute("""CREATE TABLE IF NOT EXISTS outbox_events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        message INTEGER NOT NULL,
        event TEXT NOT NULL,              -- staged|collected|pushed|push_failed|acked
        detail TEXT,
        at TEXT
    )""")
    # THE ADDRESS COLUMN THAT DOES NOT EXIST ON `projects`.
    #
    # control.projects has name/owner/status/purpose/claim/state/home and no
    # address of any kind. That is not an oversight to patch: a project's
    # address is not something the server derives or claims, and control.py
    # owns that table. Adding a column to another module's schema from here
    # would make two files the schema owner of one table, which is the exact
    # disease this codebase keeps deleting.
    #
    # So the address lives here, beside the thing that uses it, and it is
    # OPTIONAL by construction. No address means collect-only, which is the
    # normal case and the isolating one.
    c.execute("""CREATE TABLE IF NOT EXISTS outbox_addresses (
        project TEXT PRIMARY KEY,
        url TEXT NOT NULL,
        registered_at TEXT,
        registered_by TEXT,               -- the session that POSTed it, if known
        last_ok TEXT,
        last_error TEXT,
        failures INTEGER DEFAULT 0
    )""")
    c.commit()
    c.close()


def _event(c, message, event, detail=''):
    c.execute('INSERT INTO outbox_events (message,event,detail,at) '
              'VALUES (?,?,?,?)', (message, event, detail, _now()))


# 20200502  stage — the operator addresses a message to a project
def stage(project, body, kind='intake', subject='', expects='', staged_by=''):
    """Nothing is sent here. The message is written down, addressed, and left
    where the project can come and get it.

    `staged_by` is recorded because the failure this system is recovering from
    is messages going out that the operator did not ask for. A row that cannot
    say who pressed it is indistinguishable from one the server sent itself.

    An empty body is REFUSED. An empty message that reads as staged is the
    worst row this table could hold: the board would show a project owing a
    reply to nothing.
    """
    project = (project or '').strip().lower()
    body = (body or '').strip()
    if not project:
        return None, 'project required — a message with no addressee is not a message'
    if not body:
        return None, 'body required — staging an empty message would show as owed'
    if kind not in KINDS:
        return None, 'kind must be %s' % '|'.join(KINDS)
    ensure_outbox()
    c = _conn()
    cur = c.execute("""INSERT INTO outbox (project,kind,subject,body,expects,
                       staged_at,staged_by) VALUES (?,?,?,?,?,?,?)""",
                    (project, kind, subject, body, expects, _now(),
                     staged_by or 'unattributed'))
    n = cur.lastrowid
    _event(c, n, 'staged', 'by %s' % (staged_by or 'unattributed'))
    c.commit()
    c.close()
    return n, 'staged for %s — NOT sent. It is collected, or pushed if %s has ' \
              'registered a callback.' % (project, project)


# 20200510  _state — derived from the row, never stored
def _state(r):
    """Four states, and the order of these tests is the honesty of the file.

    acked beats collected beats failed beats staged. 'failed' is only ever
    reachable while the message is still sitting here uncollected, which is the
    only time a failed push is the most interesting fact about it.
    """
    if r['acked_at']:
        return 'acked'
    if r['collected_at']:
        return 'collected'
    if (r['push_attempts'] or 0) > 0 and r['push_error']:
        return 'failed'
    return 'staged'


# 20200511  _ball — whose move it is
def _ball(r):
    """THE-PLAN step 8: "HOLDING CONTIANERS WHERE U MOVE THE BALL EACH TIME".

    A count of staged messages does not tell the operator whether he is waiting
    or whether he is the one holding things up. This does, in one sentence per
    row, and it never flatters: an uncollected message says so plainly.
    """
    st = _state(r)
    if st == 'acked':
        return 'you — %s answered: %s' % (r['project'], (r['ack_note'] or '')[:80] or 'no note')
    if st == 'collected':
        return '%s — it has the message, it has not answered' % r['project']
    if st == 'failed':
        return 'you — the push to %s failed (%s); it can still collect' % (
            r['project'], r['push_error'])
    return '%s — staged, never collected. Nobody has read this.' % r['project']


def _row(r):
    d = dict(r)
    d['state'] = _state(r)
    d['ball'] = _ball(r)
    return d


# 20200503  waiting_for — what this project has not collected yet
def waiting_for(project, include_collected=False):
    """Oldest first, same reason bulletins_for is: the intake has to be read
    before the reply to it means anything."""
    ensure_outbox()
    c = _conn()
    q = 'SELECT * FROM outbox WHERE project=?'
    if not include_collected:
        q += ' AND collected_at IS NULL'
    rows = [_row(r) for r in c.execute(q + ' ORDER BY id', ((project or '').strip().lower(),))]
    c.close()
    return rows


# 20200504  collect — the project takes what is addressed to it
def collect(project, note='', via='pull'):
    """IDEMPOTENT, and the shape of that matters.

    A project collecting twice gets the same messages back both times. The
    FIRST collection timestamp is never overwritten; the second only
    increments the counter and appends an event. A retry, a restarted
    container, or a session that lost its scrollback must not be able to
    rewrite when the project first had the message -- that timestamp is the
    only evidence of what it knew and when.

    Returns (messages, note). The messages are returned in full, including ones
    already collected, because the point of collecting twice is usually that
    the first copy was lost.
    """
    project = (project or '').strip().lower()
    if not project:
        return [], 'project required'
    ensure_outbox()
    c = _conn()
    rows = [r for r in c.execute(
        'SELECT * FROM outbox WHERE project=? ORDER BY id', (project,))]
    first, again = 0, 0
    for r in rows:
        if r['collected_at']:
            again += 1
            c.execute('UPDATE outbox SET collect_count=collect_count+1 WHERE id=?',
                      (r['id'],))
            _event(c, r['id'], 'collected',
                   're-collected via %s (first was %s)' % (via, r['collected_at']))
        else:
            first += 1
            c.execute("""UPDATE outbox SET collected_at=?, collected_via=?,
                         collect_count=collect_count+1 WHERE id=?""",
                      (_now(), via, r['id']))
            _event(c, r['id'], 'collected', 'first collection via %s%s'
                   % (via, (' — %s' % note) if note else ''))
    c.commit()
    if not rows:
        c.close()
        return [], 'nothing addressed to %s' % project
    # Re-read AFTER the commit so what is returned is what is now recorded --
    # not the pre-update rows, which would report every message as uncollected
    # on the same call that collected it.
    out = [_row(r) for r in c.execute(
        'SELECT * FROM outbox WHERE project=? ORDER BY id', (project,))]
    c.close()
    return out, '%d newly collected, %d already held' % (first, again)


# 20200505  acknowledge — the project says what it will DO
def acknowledge(message, project, note=''):
    """Collection is not agreement. A project that pulled a message and said
    nothing has been told nothing that can be evidenced -- the same trap
    control.acknowledge was written to avoid, one layer out.

    An empty note is refused. "nothing, does not affect me" is a real answer;
    silence is not an answer, it is an absence.

    A message that was never collected CAN be acked -- it is recorded, not
    refused, and the trail shows the collection that never happened. Refusing
    would lose the only evidence that something odd occurred.
    """
    project = (project or '').strip().lower()
    note = (note or '').strip()
    if not note:
        return None, 'answer required — "none" is valid, silence is not'
    ensure_outbox()
    c = _conn()
    r = c.execute('SELECT * FROM outbox WHERE id=?', (message,)).fetchone()
    if not r:
        c.close()
        return None, 'no message %s' % message
    if project and r['project'] != project:
        c.close()
        return None, 'message %s is addressed to %s, not %s' % (
            message, r['project'], project)
    odd = '' if r['collected_at'] else ' (acked without ever being collected)'
    c.execute('UPDATE outbox SET acked_at=?, ack_note=? WHERE id=?',
              (_now(), note, message))
    _event(c, message, 'acked', note[:200] + odd)
    c.commit()
    c.close()
    return message, 'acknowledged' + odd


# 20200509  trail — every event for one message, in order
def trail(message):
    """Append-only and never collapsed. A push that failed twice and then
    succeeded reads as three rows here, which is the true story; one row saying
    'pushed' would be a lie of omission."""
    ensure_outbox()
    c = _conn()
    out = [dict(r) for r in c.execute(
        'SELECT * FROM outbox_events WHERE message=? ORDER BY id', (message,))]
    c.close()
    return out


# 20200506  board — the operator's staging view
def board(project=None, limit=200):
    """THE-PLAN step 8: "there is sorta a stage for me regarding things".

    Every message, to whom, in what state, and whose move it is. The counts are
    deliberately blunt: `never_collected` is its own number because it is the
    one that must never hide inside a total. A row in that number means the
    server thinks it said something and nobody has heard it.
    """
    ensure_outbox()
    # control.py owns `projects` and this reads it below. Asking its owner to
    # ensure it, rather than creating it here, is what keeps one schema owner
    # per table when the board is the first thing a fresh install touches.
    _ctl.ensure_tables()
    c = _conn()
    q = 'SELECT * FROM outbox'
    args = []
    if project:
        q += ' WHERE project=?'
        args.append((project or '').strip().lower())
    rows = [_row(r) for r in c.execute(q + ' ORDER BY id DESC LIMIT ?',
                                       tuple(args) + (int(limit),))]
    addr = {r['project']: dict(r) for r in
            c.execute('SELECT * FROM outbox_addresses')}
    known = [p['name'] for p in c.execute('SELECT name FROM projects ORDER BY name')]
    c.close()

    counts = {'staged': 0, 'collected': 0, 'acked': 0, 'failed': 0}
    for r in rows:
        counts[r['state']] = counts.get(r['state'], 0) + 1

    by_project = {}
    for r in rows:
        d = by_project.setdefault(r['project'], {
            'project': r['project'], 'staged': 0, 'collected': 0, 'acked': 0,
            'failed': 0, 'never_collected': 0, 'owed': []})
        d[r['state']] = d.get(r['state'], 0) + 1
        if not r['collected_at']:
            d['never_collected'] += 1
        if r['collected_at'] and not r['acked_at']:
            d['owed'].append(r['id'])

    for p, d in by_project.items():
        a = addr.get(p)
        # Reported per project because "did it even have an address" is the
        # first question asked about any message that did not arrive.
        d['callback'] = a['url'] if a else None
        d['callback_note'] = (
            'collect-only — %s has not registered a callback, so nothing is '
            'pushed and nothing is expected to be' % p) if not a else (
            'last ok %s; %d failures' % (a['last_ok'] or 'never', a['failures'] or 0))

    return {
        'generated': _now(),
        'messages': rows,
        'counts': counts,
        'never_collected': sum(1 for r in rows if not r['collected_at']),
        'by_project': [by_project[k] for k in sorted(by_project)],
        # A project in the registry with no outbox row has been told nothing.
        # Naming them is the point: an empty board is not the same as a fleet
        # that has been messaged.
        'never_messaged': [p for p in known if p not in by_project],
        'worker': worker_state(),
        'db': _ctl.CONTROL_DB,
    }


# ── The address a project registers for itself ───────────────────────────────

_URL_OK = re.compile(r'^https?://[A-Za-z0-9._~%:\[\]@!$&\'()*+,;=-]+(/[^\s]*)?$')
# Refused outright, and this is the isolation rule showing up as code. A
# callback pointed at loopback is the hub POSTing to a host port on this
# machine -- which is reaching into a container by another name, and would also
# let a project aim the hub at the hub's own API.
#
# HONEST LIMIT: this is a string check on the host, not a resolver. A hostname
# that RESOLVES to 127.0.0.1 is not caught here, and DNS can change after the
# check anyway. It stops the obvious case and it is not a security boundary.
_REFUSED_HOSTS = ('localhost', '127.0.0.1', '0.0.0.0', '::1', '[::1]')


# 20200507  register_address — a project hands over its own doorbell
def register_address(project, url, by=''):
    """OPTIONAL, and the default of not having one is the safe default.

    The hub NEVER derives this. It is not read from `docker ps`, not guessed
    from a published port, not inferred from a claim. If it is not in this
    table, the project collects and that is the end of it.

    WHAT THIS CANNOT PROVE, stated plainly: there is no per-project credential
    on this server today, so the hub cannot verify that the caller registering
    an address for `fksinv` is fksinv. `registered_by` records the session that
    POSTed it and the board shows the URL, which makes a wrong address visible
    to the operator. Visible is what is available; proof is not, and calling it
    proof would be the lie.
    """
    project = (project or '').strip().lower()
    url = (url or '').strip()
    if not project:
        return None, 'project required'
    if url in ('', 'none', 'remove'):
        ensure_outbox()
        c = _conn()
        c.execute('DELETE FROM outbox_addresses WHERE project=?', (project,))
        c.commit()
        c.close()
        return project, 'callback removed — %s is collect-only again' % project
    if not _URL_OK.match(url):
        return None, 'url must be http:// or https:// — got %r' % url[:60]
    host = url.split('//', 1)[1].split('/')[0].split('@')[-1].lower()
    if host.split(':')[0] in _REFUSED_HOSTS or host in _REFUSED_HOSTS:
        return None, ('refused: %s is on this machine. The hub does not POST '
                      'into a host port — that is reaching into a container, '
                      'which is the one thing isolation forbids. Register an '
                      'address the project answers on from outside, or stay '
                      'collect-only.' % host)
    ensure_outbox()
    c = _conn()
    c.execute("""INSERT INTO outbox_addresses (project,url,registered_at,
                 registered_by,failures) VALUES (?,?,?,?,0)
                 ON CONFLICT(project) DO UPDATE SET url=excluded.url,
                 registered_at=excluded.registered_at,
                 registered_by=excluded.registered_by,
                 last_error=NULL, failures=0""",
              (project, url, _now(), by or 'unattributed'))
    c.commit()
    c.close()
    return project, 'callback registered — staged messages will also be pushed ' \
                    'there once the worker is running'


# 20200508  addresses — who has registered a callback, and who has not
def addresses():
    ensure_outbox()
    c = _conn()
    out = [dict(r) for r in c.execute(
        'SELECT * FROM outbox_addresses ORDER BY project')]
    c.close()
    return out


def address(project):
    ensure_outbox()
    c = _conn()
    r = c.execute('SELECT * FROM outbox_addresses WHERE project=?',
                  ((project or '').strip().lower(),)).fetchone()
    c.close()
    return dict(r) if r else None


# ── The payload that actually travels ────────────────────────────────────────

# 20200512  payload_from_intake — the message text, read from hub/INTAKE.md
def payload_from_intake(kind='intake'):
    """The intake wording lives in ONE place and it is not this file.

    Copying that text into Python would make two versions of the thing every
    project is judged against, and the copy would win by being the one that
    runs. So it is read from the file at stage time, and if the file cannot be
    read the caller gets None and REFUSES -- staging an empty intake would show
    on the board as a project owing a reply to a blank message.

    Returns (text, source) or (None, why).
    """
    try:
        with open(INTAKE_PATH, encoding='utf-8') as f:
            text = f.read()
    except Exception as e:
        return None, 'cannot read %s: %s' % (INTAKE_PATH, type(e).__name__)

    if kind == 'intake':
        # From "## The message" to the horizontal rule that closes the section.
        # The block has a NESTED ```yaml fence inside it -- the template the
        # project fills in -- so the outer fence is the LAST ``` in the
        # section, not the second one. Taking the second would ship half a
        # template, which is worse than shipping none.
        part = text.split('## The message', 1)
        if len(part) < 2:
            return None, 'INTAKE.md has no "## The message" section'
        section = part[1].split('\n---\n', 1)[0]
        lines = section.strip('\n').splitlines()
        while lines and not lines[0].strip():
            lines.pop(0)
        if lines and lines[0].strip().startswith('```'):
            lines.pop(0)
        close = max((i for i, l in enumerate(lines) if l.strip() == '```'),
                    default=-1)
        if close < 0:
            return None, 'the message block in INTAKE.md is not closed'
        body = '\n'.join(lines[:close]).strip()
        return (body, 'hub/INTAKE.md ## The message') if body else (
            None, 'the message block in INTAKE.md is empty')

    if kind == 'reply':
        part = text.split('# The reply', 1)
        if len(part) < 2:
            return None, 'INTAKE.md has no "# The reply" section'
        section = part[1].split('## One project, one home server', 1)[0]
        lines = section.splitlines()
        try:
            start = next(i for i, l in enumerate(lines) if l.strip() == '```')
            end = next(i for i in range(start + 1, len(lines))
                       if lines[i].strip() == '```')
        except StopIteration:
            return None, 'the reply block in INTAKE.md is not closed'
        body = '\n'.join(lines[start + 1:end]).strip()
        return (body, 'hub/INTAKE.md # The reply') if body else (
            None, 'the reply block in INTAKE.md is empty')

    return None, 'no stored payload for kind=%s — send a body' % kind


# ── The push leg. Optional. Loud when it fails. ──────────────────────────────

_worker = {'started': False, 'last_run': None, 'attempts': 0, 'pushed': 0,
           'failed': 0, 'last_error': None}
_wlock = threading.Lock()


# 20200516  worker_state — whether anything is actually running
def worker_state():
    """Reported on the board. A push leg that was never started looks exactly
    like one that is running and delivering nothing, and the board must not let
    those two read the same -- that is the ntfy failure in kernel/log.py,
    repeated one layer out.
    """
    with _wlock:
        d = dict(_worker)
    d['note'] = ('running' if d['started'] else
                 'NOT STARTED — nothing is being pushed. Messages are still '
                 'staged and still collectable; the pull path does not need '
                 'this worker. Call kernel.outbox.start() to run it.')
    return d


# 20200513  push_once — one attempt, at one address, recorded either way
def push_once(msg_id):
    """One HTTP POST to the URL the project registered. Returns (ok, detail).

    Never raises at the caller. Every outcome -- 2xx, non-2xx, timeout, DNS,
    refused -- is written to outbox_events and onto the message row. The
    failure mode this is written against is the silent one: a push path that
    swallows its errors makes a project that has heard nothing indistinguishable
    from one that has heard everything.

    A 2xx from the address the project itself registered IS collection: the
    project said "post here" and the thing posted there was accepted. It is
    recorded as collected_via='push' so the board can tell the two routes
    apart. It is NOT an ack -- accepting bytes is not saying what you will do.
    """
    ensure_outbox()
    c = _conn()
    r = c.execute('SELECT * FROM outbox WHERE id=?', (msg_id,)).fetchone()
    if not r:
        c.close()
        return False, 'no message %s' % msg_id
    a = c.execute('SELECT * FROM outbox_addresses WHERE project=?',
                  (r['project'],)).fetchone()
    if not a:
        c.close()
        return False, 'no callback registered for %s — collect-only' % r['project']
    url = a['url']
    payload = json.dumps({
        'from': 'serverhub', 'message': r['id'], 'project': r['project'],
        'kind': r['kind'], 'subject': r['subject'], 'body': r['body'],
        'expects': r['expects'], 'staged_at': r['staged_at'],
        'acknowledge': 'POST /api/outbox-ack/%d {"project":"%s","answer":"..."}'
                       % (r['id'], r['project']),
    }).encode()
    c.close()

    ok, detail = False, ''
    try:
        req = urllib.request.Request(
            url, data=payload, method='POST',
            headers={'Content-Type': 'application/json',
                     'X-Flare-Outbox': str(msg_id)})
        with urllib.request.urlopen(req, timeout=PUSH_TIMEOUT) as resp:
            ok = 200 <= resp.status < 300
            detail = 'HTTP %s' % resp.status
    except urllib.error.HTTPError as e:
        detail = 'HTTP %s' % e.code
    except urllib.error.URLError as e:
        detail = 'unreachable: %s' % (getattr(e, 'reason', '') or type(e).__name__)
    except Exception as e:
        detail = type(e).__name__

    c = _conn()
    c.execute('UPDATE outbox SET push_attempts=push_attempts+1 WHERE id=?', (msg_id,))
    if ok:
        c.execute('UPDATE outbox_addresses SET last_ok=?, last_error=NULL, '
                  'failures=0 WHERE project=?', (_now(), r['project']))
        c.execute('UPDATE outbox SET push_error=NULL WHERE id=?', (msg_id,))
        if not r['collected_at']:
            c.execute("""UPDATE outbox SET collected_at=?, collected_via='push',
                         collect_count=collect_count+1 WHERE id=?""",
                      (_now(), msg_id))
        _event(c, msg_id, 'pushed', '%s -> %s' % (url, detail))
    else:
        c.execute('UPDATE outbox SET push_error=? WHERE id=?', (detail, msg_id))
        c.execute('UPDATE outbox_addresses SET last_error=?, '
                  'failures=failures+1 WHERE project=?', (detail, r['project']))
        _event(c, msg_id, 'push_failed', '%s -> %s' % (url, detail))
    c.commit()
    c.close()

    with _wlock:
        _worker['attempts'] += 1
        if ok:
            _worker['pushed'] += 1
        else:
            _worker['failed'] += 1
            _worker['last_error'] = '%s: %s' % (r['project'], detail)
    return ok, detail


# 20200514  loop — the worker body
def loop(log_fn=None):
    """Pushes ONLY messages that are already staged, and only to projects that
    registered an address. It originates nothing. There is no path in this file
    by which a message exists without someone having POSTed it.

    Gives up after PUSH_MAX_ATTEMPTS and says so once, in the log and in the
    events table. Giving up on the PUSH does not touch the message: it stays
    staged and collectable, which is the leg that was never optional.
    """
    while True:
        try:
            ensure_outbox()
            c = _conn()
            due = [dict(r) for r in c.execute(
                """SELECT o.id, o.project, o.push_attempts FROM outbox o
                   JOIN outbox_addresses a ON a.project = o.project
                   WHERE o.collected_at IS NULL
                     AND o.push_attempts < ? ORDER BY o.id""",
                (PUSH_MAX_ATTEMPTS,))]
            c.close()
            for m in due:
                ok, detail = push_once(m['id'])
                if log_fn:
                    if ok:
                        log_fn('outbox: pushed %s to %s (%s)'
                               % (m['id'], m['project'], detail))
                    else:
                        left = PUSH_MAX_ATTEMPTS - (m['push_attempts'] + 1)
                        log_fn('outbox: push %s to %s FAILED (%s) — %s'
                               % (m['id'], m['project'], detail,
                                  '%d attempts left' % left if left > 0 else
                                  'giving up on the push; it is still staged '
                                  'and still collectable'))
            with _wlock:
                _worker['last_run'] = _now()
        except Exception as e:
            # The worker never dies quietly. A dead worker and a worker with
            # nothing to do look identical from the outside, so the error is
            # kept where worker_state() will report it.
            with _wlock:
                _worker['last_error'] = 'loop: %s' % type(e).__name__
            if log_fn:
                log_fn('outbox: worker error %s' % type(e).__name__)
        time.sleep(WORKER_INTERVAL)


# 20200515  start — explicit. Nothing starts on import.
def start(log_fn=None):
    """Called from server.py's __main__ block, beside the heartbeat and the
    docker watcher. NOT on import: importing a module must never begin sending
    anything, and a handler import is exactly how a message would go out that
    nobody asked for.

    Safe to call when no project has registered an address — the worker finds
    nothing due and idles.
    """
    with _wlock:
        if _worker['started']:
            return None
        _worker['started'] = True
    t = threading.Thread(target=loop, args=(log_fn,), daemon=True)
    t.start()
    return t
