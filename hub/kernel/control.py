#!/usr/bin/env python3
"""
# 20200014  kernel.control — the registry projects actually talk to

Everything about this was written as markdown first, which was the mistake. A
project cannot POST to a document, cannot be told its master moved, and cannot
acknowledge anything. This is the same design as a running thing.

Three tables, and the split between them is the whole discipline:

    projects      what a project CLAIMED       not derivable -> stored, backed up
    acks          which master it confirmed    not derivable -> stored, backed up
    releases      what was staged/promoted     not derivable -> stored, backed up

Nothing here stores what the machine can answer. Containers, ports, disks and
labels are NOT in this database -- they are read live from Docker and the
filesystem every time. A stored copy of those is a second source of truth, and
this project has spent a fortnight deleting those.

The rule, stated once: if `docker ps` can tell you, this file must not.

SEPARATE FILE from server.db on purpose. You need the release history readable
when the hub is broken -- if a bad promote wrecked it, the record of what to
roll back to cannot live inside the wreck.
"""
import json
import os
import re
import sqlite3
import time
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONTROL_DB = os.environ.get(
    'HUB_CONTROL_DB', os.path.join(os.path.dirname(BASE_DIR), 'db', 'control.db'))


def _conn():
    os.makedirs(os.path.dirname(CONTROL_DB), exist_ok=True)
    c = sqlite3.connect(CONTROL_DB, timeout=5)
    c.row_factory = sqlite3.Row
    return c


def _now():
    return datetime.now().isoformat(timespec='seconds')


# 20200361  ensure_tables — one schema owner, same rule as kernel/db.py
def ensure_tables():
    c = _conn()
    c.execute("""CREATE TABLE IF NOT EXISTS projects (
        name TEXT PRIMARY KEY,
        owner TEXT,
        status TEXT DEFAULT 'dev',        -- dev | staging | production
        purpose TEXT,
        claim TEXT,                       -- the raw YAML/JSON, verbatim, never edited
        claimed_at TEXT,
        verified_at TEXT,
        state TEXT DEFAULT 'awaiting',    -- awaiting|claimed|verified|reconciled
        home TEXT                         -- the server_id this is true for
    )""")
    # A project's acknowledgement of the master its server runs. Append-only:
    # the history of what a project was told is evidence, not state to update.
    c.execute("""CREATE TABLE IF NOT EXISTS acks (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        project TEXT NOT NULL,
        ref TEXT NOT NULL,                -- the server master acknowledged
        answer TEXT,                      -- what it will DO about pending
        at TEXT
    )""")
    # One row per thing that HAPPENED to a ref, never a row describing where a
    # ref stands. Where it stands is the rows read in order -- see weight().
    c.execute("""CREATE TABLE IF NOT EXISTS releases (
        ref TEXT NOT NULL,
        state TEXT NOT NULL,              -- staged | checked | promoted | rolled_back
        preflight TEXT,                   -- that state's gate result, e.g. "8 of 10"
        note TEXT,
        at TEXT,
        PRIMARY KEY (ref, state, at)
    )""")
    # Differences found at verification. Stored because a DISPOSITION is a
    # decision and decisions are not re-derivable; the difference itself is,
    # and is re-checked every verify.
    c.execute("""CREATE TABLE IF NOT EXISTS diffs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        project TEXT NOT NULL,
        claimed TEXT,
        machine TEXT,
        why TEXT,
        disposition TEXT DEFAULT '',      -- fix|accept|defer|hub-wrong
        at TEXT
    )""")
    c.commit()
    c.close()


# 20200362  register — a project files or refiles its claim
def register(name, claim, home=''):
    """The claim is stored VERBATIM and never corrected. A claim that turns out
    wrong is evidence of the distance between intent and reality, which is the
    entire product here."""
    if not name:
        return None, 'name required'
    ensure_tables()
    c = _conn()
    row = c.execute('SELECT name FROM projects WHERE name=?', (name,)).fetchone()
    body = claim if isinstance(claim, str) else json.dumps(claim, indent=2)
    fields = claim if isinstance(claim, dict) else {}
    if row:
        c.execute("""UPDATE projects SET claim=?, claimed_at=?, state='claimed',
                     owner=COALESCE(NULLIF(?,''),owner),
                     status=COALESCE(NULLIF(?,''),status),
                     purpose=COALESCE(NULLIF(?,''),purpose)
                     WHERE name=?""",
                  (body, _now(), fields.get('owner', ''), fields.get('status', ''),
                   fields.get('purpose', ''), name))
        note = 're-filed'
    else:
        c.execute("""INSERT INTO projects (name,owner,status,purpose,claim,
                     claimed_at,state,home) VALUES (?,?,?,?,?,?,'claimed',?)""",
                  (name, fields.get('owner', ''), fields.get('status', 'dev'),
                   fields.get('purpose', ''), body, _now(), home))
        note = 'first claim'
    c.commit()
    c.close()
    return name, note


# 20200363  acknowledge — the project confirms which master it has been told
def acknowledge(project, ref, answer=''):
    """`answer` is what the project will DO about pending changes. Recorded even
    when it is "nothing, does not affect me" -- an unanswered pending change is
    how a project ends up bound to a port that moved underneath it."""
    if not project or not ref:
        return None, 'project and ref required'
    ensure_tables()
    c = _conn()
    c.execute('INSERT INTO acks (project,ref,answer,at) VALUES (?,?,?,?)',
              (project, ref, answer, _now()))
    c.commit()
    c.close()
    return project, 'acknowledged %s' % ref[:7]


# 20200364  stale — which projects have not acknowledged the current master
def stale(current_ref):
    """Stale is NOT failure. It means this project has not been told, so do not
    assume it knows. Silence stops being mistaken for agreement."""
    ensure_tables()
    c = _conn()
    out = []
    for p in c.execute('SELECT name FROM projects ORDER BY name'):
        last = c.execute("""SELECT ref, at FROM acks WHERE project=?
                            ORDER BY id DESC LIMIT 1""", (p['name'],)).fetchone()
        out.append({
            'project': p['name'],
            'acknowledged': last['ref'] if last else None,
            'at': last['at'] if last else None,
            'stale': (not last) or last['ref'] != current_ref,
        })
    c.close()
    return out


# 20200374  fleet_stale — who has not been told, worst consequence first
def fleet_stale(current_ref):
    """stale() lists everyone in name order, which buries the one row that
    matters. A production project that does not know what its server is running
    is a different sentence from a dev one that does not, so the order is the
    finding: production, staging, dev.

    A status this vocabulary does not recognise sorts LAST. Ranking an unknown
    word as production would be the hub inventing urgency it cannot evidence --
    the raw status rides along in the row so a human can see what it actually is.
    """
    ensure_tables()
    c = _conn()
    rows = c.execute("""SELECT p.name, p.owner, p.status, p.state,
        (SELECT ref FROM acks a WHERE a.project=p.name
                    ORDER BY a.id DESC LIMIT 1) ack,
        (SELECT at  FROM acks a WHERE a.project=p.name
                    ORDER BY a.id DESC LIMIT 1) ack_at
        FROM projects p
        ORDER BY CASE p.status WHEN 'production' THEN 0 WHEN 'staging' THEN 1
                               WHEN 'dev' THEN 2 ELSE 3 END, p.name""").fetchall()
    c.close()
    out = []
    for r in rows:
        if current_ref and r['ack'] == current_ref:
            continue
        if not current_ref:
            # Not "nothing is stale". This server cannot name what it runs, so
            # no acknowledgement can be checked against it, and reporting an
            # empty list here would read as agreement.
            why = 'this server cannot name the master it runs, so no ack can be checked'
        elif not r['ack']:
            why = 'has never acknowledged anything'
        else:
            why = 'last acknowledged %s, which is not what this server runs' % r['ack'][:7]
        out.append({
            'project': r['name'], 'owner': r['owner'], 'status': r['status'],
            'state': r['state'], 'acknowledged': r['ack'], 'at': r['ack_at'],
            'why': why,
            'tell': 'POST /api/ack/%s {"ref": "%s"}' % (r['name'], current_ref),
        })
    return out


# 20200365  release — record a stage, check, promote or rollback
def release(ref, state, preflight='', note=''):
    """The one writer into releases. stage/routes_diffed/promote are named doors
    onto this, so every row in the ladder is written in one format by one
    function and weight() never has to guess at prose it did not produce."""
    if state not in ('staged', 'checked', 'promoted', 'rolled_back'):
        return None, 'state must be staged|checked|promoted|rolled_back'
    ensure_tables()
    c = _conn()
    c.execute('INSERT OR REPLACE INTO releases (ref,state,preflight,note,at) '
              'VALUES (?,?,?,?,?)', (ref, state, preflight, note, _now()))
    c.commit()
    c.close()
    return ref, state


def last_promoted():
    """What to roll back TO. The reason this database is a separate file."""
    ensure_tables()
    c = _conn()
    r = c.execute("""SELECT ref, at, preflight FROM releases
                     WHERE state='promoted' ORDER BY at DESC LIMIT 1""").fetchone()
    c.close()
    return dict(r) if r else None


# The rungs a ref climbs before it is safe to promote, as numbers, because
# "should I promote this" asked as a feeling is answered differently by the same
# person on two days. Gapped on purpose: other emitters (storage findings, fleet
# status) have to land on this scale eventually, and they need room between the
# rungs without every number being rewritten. Only comparison is ever asked of
# these, never arithmetic.
WEIGHT_ZERO = 0          # promoted and it held
WEIGHT_LOW = 10          # everything checkable has been checked
WEIGHT_MEDIUM = 40       # the gate passed, the routes were never compared
WEIGHT_HIGH = 80         # nothing ran, or something ran and failed
PROMOTE_CLEAN_HOURS = 24  # a promote is not proven by exiting zero, only by lasting


def _hours_since(at):
    try:
        return (datetime.now() - datetime.fromisoformat(at)).total_seconds() / 3600.0
    except Exception:
        return None


def _preflight_passed(text):
    """"8 of 10" is stored rather than a boolean, so passing is 8==10, not
    "a preflight was recorded". A recorded FAILURE is the case that matters: it
    must not read as progress just because the field is non-empty."""
    t = (text or '').strip().lower()
    if not t:
        return False
    m = re.search(r'(\d+)\s*of\s*(\d+)', t)
    if m:
        return m.group(1) == m.group(2)
    return t in ('pass', 'passed', 'ok', 'clean')


def _drift(text):
    """The count routes_diffed wrote, or None when the row predates that format.
    None is not zero -- unreadable evidence is not clean evidence."""
    m = re.search(r'routes:\s*(\d+)\s*drift', (text or '').lower())
    return int(m.group(1)) if m else None


def _rolled_back_after(c, ref, at):
    return c.execute("SELECT 1 FROM releases WHERE ref=? AND state='rolled_back'"
                     " AND at>=? LIMIT 1", (ref, at)).fetchone() is not None


# 20200368  stage — a ref becomes a candidate
def stage(ref, preflight='', note=''):
    """`preflight` is the gate result verbatim. Which two of the ten failed is
    the thing wanted at 2am, and a boolean has already thrown it away."""
    if not ref:
        return None, 'ref required'
    return release(ref, 'staged', preflight, note)


# 20200369  routes_diffed — this ref's routes, compared against the running server
def routes_diffed(ref, drift, note=''):
    """Stored, and the exception proves Law I rather than bending it: a diff is a
    comparison made at a moment against a tree that is no longer checked out.
    Running it again later answers a different question, so the answer is not
    re-derivable -- which is the only test that admits anything to this file.

    Produced by `python3 tools/check-views.py` (exit 0 clean, 1 on drift).
    """
    if not ref:
        return None, 'ref required'
    try:
        n = int(drift)
    except (TypeError, ValueError):
        return None, 'drift must be a count'
    return release(ref, 'checked', 'routes: %d drift' % n, note)


# 20200370  promote — this ref is what the server runs now
def promote(ref, note=''):
    """The previous promoted ref becomes the rollback target by BEING previous.
    Nothing writes a rollback_to field: a pointer beside an ordering the rows
    already carry is a second source of truth about the same fact, and this
    project has spent a fortnight deleting those.

    Promoting a ref that was never staged is RECORDED, not refused -- a hotfix
    that skipped the ladder is exactly the thing the history must still show.
    """
    if not ref:
        return None, 'ref required'
    ensure_tables()
    c = _conn()
    staged = c.execute("SELECT at FROM releases WHERE ref=? AND state='staged'"
                       " ORDER BY at DESC LIMIT 1", (ref,)).fetchone()
    c.close()
    r, err = release(ref, 'promoted', '', note)
    if not r:
        return None, err
    back = rollback_target()
    return ref, 'promoted%s; rollback target %s' % (
        '' if staged else ' (never staged)',
        back['ref'][:7] if back else 'none -- this is the first that held')


# 20200371  rollback_target — where back actually is
def rollback_target():
    """The last ref that was promoted AND STAYED promoted. Two exclusions, and
    both are the reason this is computed rather than remembered:

      the ref running now      going back to where you are is not going back
      a ref rolled back after  it already failed once; it is not a floor

    Returns None when there is nowhere to go, which is information -- a first
    promote has no floor under it, and pretending otherwise is how a rollback
    lands somewhere nobody chose.
    """
    ensure_tables()
    c = _conn()
    rows = c.execute("SELECT ref,at,preflight,note FROM releases WHERE "
                     "state='promoted' ORDER BY at DESC, rowid DESC").fetchall()
    current = rows[0]['ref'] if rows else None
    back = None
    for r in rows:
        if r['ref'] == current:
            continue
        if _rolled_back_after(c, r['ref'], r['at']):
            continue
        back = dict(r)
        break
    c.close()
    if not back:
        return None
    back['from'] = current        # what a rollback would be leaving
    back['held_for_hours'] = _hours_since(back['at'])
    return back


# 20200372  release_history — the ladder in order, for a human
def release_history(limit=20):
    """Newest first, every state, nothing collapsed. A history that showed only
    the latest row per ref would hide the two facts anyone reads this for: that a
    ref was promoted twice, and that one of those promotes did not survive."""
    ensure_tables()
    c = _conn()
    rows = [dict(r) for r in c.execute(
        "SELECT ref,state,preflight,note,at FROM releases "
        "ORDER BY at DESC, rowid DESC LIMIT ?", (int(limit),))]
    c.close()
    return rows


# 20200373  weight — "should I promote this" as a number
def weight(ref):
    """Returns {ref, weight, rung, why, next}. The number is for comparing; the
    other three are why it is not just a number -- a risk you cannot act on is a
    mood. `next` is the command that lowers it, and nothing here runs it.

        never started        WEIGHT_HIGH     nothing has been asserted at all
        preflight passed     WEIGHT_MEDIUM   the gate ran, routes never compared
        routes diffed clean  WEIGHT_LOW      everything checkable has been checked
        promoted 24h clean   WEIGHT_ZERO     it held, which is the only real proof

    Read from the rows, never from a status column, so a ref that was promoted
    and rolled back reads HIGH again on its own -- no second write to forget.
    """
    out = {'ref': ref, 'weight': WEIGHT_HIGH, 'rung': 'unknown', 'why': '',
           'next': ''}
    if not ref:
        out['why'] = 'no ref given'
        return out
    ensure_tables()
    c = _conn()
    rows = [dict(r) for r in c.execute(
        "SELECT ref,state,preflight,note,at FROM releases WHERE ref=? "
        "ORDER BY at DESC, rowid DESC", (ref,))]
    c.close()
    if not rows:
        out['rung'] = 'unrecorded'
        out['why'] = 'no release record for this ref; nothing about it is known'
        out['next'] = 'python3 tools/install-preflight.py, then stage(ref, "<n of m>")'
        return out

    promoted = next((r for r in rows if r['state'] == 'promoted'), None)
    back = next((r for r in rows if r['state'] == 'rolled_back'), None)
    checked = next((r for r in rows if r['state'] == 'checked'), None)
    staged = next((r for r in rows if r['state'] == 'staged'), None)

    if back and (not promoted or back['at'] >= promoted['at']):
        out['rung'] = 'rolled back'
        out['why'] = 'rolled back at %s; whatever caused that is not recorded as fixed' % back['at']
        out['next'] = 'stage(ref, ...) again once the cause is addressed'
        return out

    if promoted:
        hours = _hours_since(promoted['at'])
        if hours is None:
            out['weight'] = WEIGHT_LOW
            out['rung'] = 'promoted'
            out['why'] = 'promoted at %r, which this cannot read as a time' % promoted['at']
            return out
        if hours >= PROMOTE_CLEAN_HOURS:
            out['weight'] = WEIGHT_ZERO
            out['rung'] = 'promoted, held'
            out['why'] = 'promoted %.0fh ago and never rolled back' % hours
            return out
        out['weight'] = WEIGHT_LOW
        out['rung'] = 'promoted, young'
        out['why'] = ('promoted %.1fh ago; %.1fh short of the %dh that makes a '
                      'promote proof rather than a hope'
                      % (hours, PROMOTE_CLEAN_HOURS - hours, PROMOTE_CLEAN_HOURS))
        return out

    passed = _preflight_passed(staged['preflight'] if staged else '')

    if checked:
        d = _drift(checked['preflight'])
        if d is None:
            out['weight'] = WEIGHT_MEDIUM
            out['rung'] = 'diffed, unreadable'
            out['why'] = 'a route diff was recorded as %r, which is not a count' % checked['preflight']
            out['next'] = 'python3 tools/check-views.py, then routes_diffed(ref, <drift>)'
            return out
        if d > 0:
            out['rung'] = 'routes drifted'
            out['why'] = ('%d routes disagree with the registry; promoting ships '
                          'a server whose nav cannot reach part of itself' % d)
            out['next'] = 'python3 tools/check-views.py and fix the drift it names'
            return out
        if not passed:
            # Rungs do not skip. Clean routes with no passing gate says the
            # cheaper check ran and the expensive one did not.
            out['weight'] = WEIGHT_MEDIUM
            out['rung'] = 'routes clean, gate not passed'
            out['why'] = 'routes diffed clean, but the preflight has not passed'
            out['next'] = 'python3 tools/install-preflight.py, then stage(ref, "<n of m>")'
            return out
        out['weight'] = WEIGHT_LOW
        out['rung'] = 'routes diffed clean'
        out['why'] = 'preflight passed (%s) and routes diffed clean' % staged['preflight']
        out['next'] = 'promote(ref) -- nothing checkable is left unchecked'
        return out

    if staged and passed:
        out['weight'] = WEIGHT_MEDIUM
        out['rung'] = 'preflight passed'
        out['why'] = 'preflight %s, routes never compared against the running server' % staged['preflight']
        out['next'] = 'python3 tools/check-views.py, then routes_diffed(ref, <drift>)'
        return out
    if staged and (staged['preflight'] or '').strip():
        out['rung'] = 'preflight failed'
        out['why'] = 'preflight recorded as %r, which is not a pass' % staged['preflight']
        out['next'] = 'fix what it named, then stage(ref, "<n of m>") again'
        return out
    out['rung'] = 'never started'
    out['why'] = 'staged with no preflight result; nothing has been asserted about it'
    out['next'] = 'python3 tools/install-preflight.py, then stage(ref, "<n of m>")'
    return out


# 20200366  record_diffs — replace this project's differences after a verify
def record_diffs(project, diffs):
    """Differences are re-derived every verify, so they are replaced -- but any
    disposition already given is carried forward by (claimed, machine) identity.
    A decision survives re-verification; the observation does not."""
    ensure_tables()
    c = _conn()
    prior = {(r['claimed'], r['machine']): r['disposition']
             for r in c.execute('SELECT claimed,machine,disposition FROM diffs '
                                'WHERE project=?', (project,))}
    c.execute('DELETE FROM diffs WHERE project=?', (project,))
    for d in diffs or []:
        key = (d.get('claimed', ''), d.get('machine', ''))
        c.execute("""INSERT INTO diffs (project,claimed,machine,why,disposition,at)
                     VALUES (?,?,?,?,?,?)""",
                  (project, d.get('claimed', ''), d.get('machine', ''),
                   d.get('why', ''), prior.get(key, ''), _now()))
    c.execute("UPDATE projects SET verified_at=?, state='verified' WHERE name=?",
              (_now(), project))
    c.commit()
    c.close()
    return len(diffs or [])


def dispose(project, diff_id, disposition):
    if disposition not in ('fix', 'accept', 'defer', 'hub-wrong'):
        return None, 'disposition must be fix|accept|defer|hub-wrong'
    ensure_tables()
    c = _conn()
    c.execute('UPDATE diffs SET disposition=? WHERE id=? AND project=?',
              (disposition, diff_id, project))
    open_left = c.execute("SELECT COUNT(*) n FROM diffs WHERE project=? AND "
                          "disposition=''", (project,)).fetchone()['n']
    if open_left == 0:
        # Reconciled means every difference has a DISPOSITION -- not that every
        # difference was fixed. Four accepted deviations is fully reconciled.
        c.execute("UPDATE projects SET state='reconciled' WHERE name=?", (project,))
    c.commit()
    c.close()
    return disposition, open_left


# 20200367  registry — the whole picture for this server
def registry(current_ref=''):
    ensure_tables()
    c = _conn()
    projects = []
    for p in c.execute('SELECT * FROM projects ORDER BY name'):
        d = dict(p)
        d.pop('claim', None)          # the raw claim is fetched per project
        last = c.execute('SELECT ref,at,answer FROM acks WHERE project=? '
                         'ORDER BY id DESC LIMIT 1', (p['name'],)).fetchone()
        d['acknowledged'] = last['ref'] if last else None
        d['stale'] = (not last) or (current_ref and last['ref'] != current_ref)
        d['diffs_open'] = c.execute("SELECT COUNT(*) n FROM diffs WHERE "
                                    "project=? AND disposition=''",
                                    (p['name'],)).fetchone()['n']
        projects.append(d)
    c.close()
    return {'master': current_ref, 'projects': projects,
            'generated': _now(), 'db': CONTROL_DB}


# -----------------------------------------------------------------------------
# Bulletins, tickets, activity and the backup ladder.
#
# The server publishes; projects read and acknowledge. NOTHING HERE BLOCKS
# ANYTHING. A bulletin that stopped a deploy would make reading it a chore to be
# routed around; one that only records who read it makes reading it the cheapest
# way to avoid a surprise.
# -----------------------------------------------------------------------------

def _pin(seed):
    """Four digits derived from the content, so it cannot be guessed from the
    bulletin number and cannot drift from the text it proves was read."""
    import hashlib
    return "%04d" % (int(hashlib.sha256(seed.encode()).hexdigest()[:8], 16) % 10000)


# 20200383  ensure_exchange
def ensure_exchange():
    c = _conn()
    c.execute("""CREATE TABLE IF NOT EXISTS bulletins (
        n INTEGER PRIMARY KEY AUTOINCREMENT,
        scope TEXT DEFAULT 'all',
        rung INTEGER DEFAULT 1,
        title TEXT, body TEXT,
        action TEXT,
        pin TEXT, published TEXT
    )""")
    # A read is recorded against a BULLETIN, not just a code ref: a project can
    # be current on code and still never have been told what is changing.
    c.execute("""CREATE TABLE IF NOT EXISTS reads (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        project TEXT NOT NULL, bulletin INTEGER NOT NULL,
        answer TEXT, at TEXT
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS tickets (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        project TEXT NOT NULL, problem TEXT, what_i_see TEXT,
        diagnosis TEXT DEFAULT '', resolution TEXT DEFAULT '',
        state TEXT DEFAULT 'open', at TEXT, closed_at TEXT
    )""")
    # A project lives in a container; this table does not. A container dying
    # takes its own logs with it, so anything a project wants to still be true
    # after that belongs here, outside Docker, on the server.
    c.execute("""CREATE TABLE IF NOT EXISTS project_activity (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        project TEXT NOT NULL,
        kind TEXT DEFAULT 'note',
        body TEXT NOT NULL,
        at TEXT
    )""")
    # 'saved' is a claim someone made; 'auto' is a week without complaint.
    # A restore must know which it is trusting, so they are never merged.
    c.execute("""CREATE TABLE IF NOT EXISTS baselines (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        project TEXT NOT NULL, kind TEXT NOT NULL, label TEXT,
        pinned INTEGER DEFAULT 0, at TEXT, released_at TEXT
    )""")
    c.commit()
    c.close()


# 20200375  publish
def publish(title, body, action='none', scope='all', rung=1):
    ensure_exchange()
    c = _conn()
    pin = _pin(title + body + action)
    cur = c.execute('INSERT INTO bulletins (scope,rung,title,body,action,pin,published)'
                    ' VALUES (?,?,?,?,?,?,?)',
                    (scope, rung, title, body, action, pin, _now()))
    n = cur.lastrowid
    c.commit()
    c.close()
    return n, pin


# 20200376  bulletins_for
def bulletins_for(project, unread_only=True):
    """Oldest first, because the ladder is ordered: a project cannot judge what
    is changing until it has confirmed what is."""
    ensure_exchange()
    c = _conn()
    seen = set(r['bulletin'] for r in
               c.execute('SELECT bulletin FROM reads WHERE project=?', (project,)))
    out = []
    for b in c.execute("SELECT n,scope,rung,title,action,published FROM bulletins"
                       " WHERE scope='all' OR scope=? ORDER BY n", (project,)):
        d = dict(b)
        d['read'] = b['n'] in seen
        if unread_only and d['read']:
            continue
        out.append(d)
    c.close()
    return out


# 20200377  bulletin
def bulletin(n):
    ensure_exchange()
    c = _conn()
    r = c.execute('SELECT * FROM bulletins WHERE n=?', (n,)).fetchone()
    c.close()
    return dict(r) if r else None


# 20200378  read_bulletin
def read_bulletin(project, n, pin, answer=''):
    """The PIN is proof of reading, so a wrong one is REFUSED rather than
    recorded. Refused, not locked: re-reading is the correct response to getting
    it wrong, and locking would punish the only useful reaction."""
    ensure_exchange()
    b = bulletin(n)
    if not b:
        return None, 'no such bulletin'
    if str(pin).strip() != b['pin']:
        return None, 'pin does not match bulletin %s - read it again' % n
    if not (answer or '').strip():
        return None, 'answer required - "none" is valid, silence is not'
    c = _conn()
    c.execute('INSERT INTO reads (project,bulletin,answer,at) VALUES (?,?,?,?)',
              (project, n, answer, _now()))
    c.commit()
    c.close()
    return n, 'read'


# 20200379  who_read - the matrix, the most useful thing the server knows
def who_read(n):
    ensure_exchange()
    c = _conn()
    read = dict((r['project'], r['at']) for r in
                c.execute('SELECT project,at FROM reads WHERE bulletin=?', (n,)))
    out = [{'project': p['name'], 'read': p['name'] in read,
            'at': read.get(p['name'])}
           for p in c.execute('SELECT name FROM projects ORDER BY name')]
    c.close()
    return out


# 20200380  ticket - filed BEFORE self-fixing
def ticket(project, problem, what_i_see=''):
    ensure_exchange()
    c = _conn()
    cur = c.execute('INSERT INTO tickets (project,problem,what_i_see,at)'
                    ' VALUES (?,?,?,?)', (project, problem, what_i_see, _now()))
    n = cur.lastrowid
    c.commit()
    c.close()
    return n, 'open'


def diagnose(tid, diagnosis):
    ensure_exchange()
    c = _conn()
    c.execute("UPDATE tickets SET diagnosis=?, state='diagnosed' WHERE id=?",
              (diagnosis, tid))
    c.commit()
    c.close()
    return tid, 'diagnosed'


def close_ticket(tid, resolution):
    """resolution is what the project ACTUALLY DID. An unrecorded self-fix is
    indistinguishable from drift six weeks later."""
    ensure_exchange()
    c = _conn()
    c.execute("UPDATE tickets SET resolution=?, state='closed', closed_at=?"
              " WHERE id=?", (resolution, _now(), tid))
    c.commit()
    c.close()
    return tid, 'closed'


def open_tickets(project=None):
    ensure_exchange()
    c = _conn()
    q = "SELECT * FROM tickets WHERE state!='closed'"
    rows = (c.execute(q + ' AND project=? ORDER BY id', (project,)) if project
            else c.execute(q + ' ORDER BY id'))
    out = [dict(r) for r in rows]
    c.close()
    return out


# 20200382  activity - a project's log, kept OUTSIDE its container
def log_project(project, body, kind='note'):
    """A project lives in a container and this table does not. When the
    container is rebuilt or pruned its own logs go with it; anything that must
    still be true afterwards belongs here.

    Deliberately unstructured: a deploy, a decision, a rollback, a note to
    whoever reads this in six months. The server does not interpret it, it
    just keeps it."""
    ensure_exchange()
    c = _conn()
    cur = c.execute('INSERT INTO project_activity (project,kind,body,at)'
                    ' VALUES (?,?,?,?)', (project, kind, body, _now()))
    n = cur.lastrowid
    c.commit()
    c.close()
    return n, kind


def activity(project, limit=50):
    ensure_exchange()
    c = _conn()
    out = [dict(r) for r in c.execute(
        'SELECT * FROM project_activity WHERE project=? ORDER BY id DESC LIMIT ?',
        (project, limit))]
    c.close()
    return out


# 20200381  the backup ladder
def save_baseline(project, label='', kind='saved'):
    ensure_exchange()
    c = _conn()
    cur = c.execute('INSERT INTO baselines (project,kind,label,at) VALUES (?,?,?,?)',
                    (project, kind, label, _now()))
    n = cur.lastrowid
    c.commit()
    c.close()
    return n, kind


def checkpoint(project, label='pre-deploy'):
    """Pinned: exempt from rotation until released. Otherwise the one copy you
    need is the one that ages out."""
    ensure_exchange()
    c = _conn()
    cur = c.execute('INSERT INTO baselines (project,kind,label,pinned,at)'
                    ' VALUES (?,?,?,1,?)', (project, 'checkpoint', label, _now()))
    n = cur.lastrowid
    c.commit()
    c.close()
    return n, 'pinned'


def release_checkpoint(bid):
    ensure_exchange()
    c = _conn()
    c.execute('UPDATE baselines SET pinned=0, released_at=? WHERE id=?',
              (_now(), bid))
    c.commit()
    c.close()
    return bid, 'released'


AUTO_BASELINE_DAYS = 7


def auto_baseline_eligible(project):
    """Seven quiet days promotes a checkpoint to baseline -- UNLESS a ticket is
    open. Silence is not evidence: a week without complaint could mean it works
    or that nobody looked, and an open ticket tells you which."""
    ensure_exchange()
    if open_tickets(project):
        return False, 'ticket open - silence is not evidence'
    c = _conn()
    r = c.execute('SELECT at FROM baselines WHERE project=? ORDER BY id DESC'
                  ' LIMIT 1', (project,)).fetchone()
    c.close()
    if not r:
        return False, 'nothing to promote'
    try:
        from datetime import datetime as _dt
        age = (_dt.now() - _dt.fromisoformat(r['at'])).days
    except Exception:
        return False, 'unparseable timestamp'
    return age >= AUTO_BASELINE_DAYS, 'quiet %d/%d days' % (age, AUTO_BASELINE_DAYS)


def baselines(project):
    ensure_exchange()
    c = _conn()
    out = [dict(r) for r in c.execute(
        'SELECT * FROM baselines WHERE project=? ORDER BY id DESC', (project,))]
    c.close()
    return out
