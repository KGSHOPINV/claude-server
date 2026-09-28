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
import secrets as _secrets
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


# 20200390  now — the server's clock, so a page can compute age without skew
def now():
    """Every timestamp this module writes comes from _now(). A screen that
    renders "2 days ago" has to subtract one of them from something, and if
    that something is the VIEWER's clock the answer carries the difference
    between two machines. So the API returns this alongside the rows: both
    ends of every subtraction then came from the same clock.

    Deliberately not an age. An age is computed once and then rots -- a board
    left open for forty minutes would still say "2 minutes ago". A `now` that
    is forty minutes old visibly lags, and the page can say so.
    """
    return _now()


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
    # band: the project port band the build this row describes SERVES, as
    # floor-ceiling/size. Not derivable after the fact -- a process can read
    # the band it serves itself and nothing else, so what the build before it
    # served is recorded here or it is lost. That is what makes a band move
    # a difference the hub can compute instead of a sentence somebody types.
    #
    # ALTER, not a rewrite: the release ladder is the one table that must
    # survive a schema change, because it is what a rollback reads.
    cols = {r[1] for r in c.execute('PRAGMA table_info(releases)')}
    if 'band' not in cols:
        c.execute('ALTER TABLE releases ADD COLUMN band TEXT')
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


# 20200320  served_band — the project port band THIS build serves, as one string
def served_band():
    """floor-ceiling/size, e.g. "12000-18999/100".

    ONE FORMATTER ON PURPOSE. The bulletin kernel/changewatch publishes and the
    pending item /api/admit carries are read by the same project, and two
    formatters for one fact eventually disagree by a slash -- which reads, to
    the project, as two different bands.

    Returns '' when the constants cannot be read, and '' is NOT a band. A
    caller must not compare it to anything or hand it out; an unknown band is
    the thing _pending() has to report, not paper over.
    """
    try:
        from kernel import collect as _collect          # noqa: PLC0415
        return '%d-%d/%d' % (_collect.PROJECT_BAND_FLOOR,
                             _collect.PROJECT_BAND_CEIL,
                             _collect.PROJECT_BAND_SIZE)
    except Exception:
        return ''


# 20200335  promoted_band — the band the DEPLOYED build serves, read off the record
def promoted_band():
    """{'ref','at','band'} for the most recent promote that recorded a band, or
    None.

    None is an answer callers must HANDLE, never skip. A running process cannot
    introspect what the process before it was serving, so if no promote recorded
    a band then the previous band is unknown -- and unknown is not "the same".
    Treating None as "no change" is how a band move ships with every project
    told nothing is coming.

    Rows written before the band column existed read back NULL and are skipped
    here for the same reason: an absent band is not an empty band.
    """
    ensure_tables()
    c = _conn()
    r = c.execute("SELECT ref, at, band FROM releases WHERE state='promoted' "
                  "AND band IS NOT NULL AND band != '' "
                  "ORDER BY at DESC, rowid DESC LIMIT 1").fetchone()
    c.close()
    return dict(r) if r else None


# 20200365  release — record a stage, check, promote or rollback
def release(ref, state, preflight='', note='', band=None):
    """The one writer into releases. stage/routes_diffed/promote are named doors
    onto this, so every row in the ladder is written in one format by one
    function and weight() never has to guess at prose it did not produce.

    `band` is the project port band the build being recorded serves. It is
    DEFAULTED from the running constants rather than demanded of every caller,
    because it is only ever true of the process writing the row -- a caller
    that had to supply it would be retyping a number it had just read, which is
    how the band came to be written in four places and disagree in two of them.

    Passing band='' records a row that deliberately claims nothing, which
    promoted_band() then skips. Silence and a band are different things.
    """
    if state not in ('staged', 'checked', 'promoted', 'rolled_back'):
        return None, 'state must be staged|checked|promoted|rolled_back'
    ensure_tables()
    c = _conn()
    c.execute('INSERT OR REPLACE INTO releases (ref,state,preflight,note,at,band) '
              'VALUES (?,?,?,?,?,?)',
              (ref, state, preflight, note, _now(),
               served_band() if band is None else band))
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

# Removed: _pin(seed), four digits from sha256(title + body + action). It made
# ONE pin for every recipient of a bulletin, out of the very text that is
# printed to every recipient — so any recipient could recompute any other's, and
# a pin every holder can derive proves only that the bulletin exists. Its one
# caller was publish(). _recipient_pin replaces it.

# 20200317  _recipient_pin — one pin per (bulletin, project), unguessable by peers
def _recipient_pin(secret, project):
    """The per-recipient confirmation code.

    THE PIN IS THE ONLY PER-PROJECT CREDENTIAL THIS SERVER HAS. There is no
    per-project token — edges.py says so of /api/outbox-address in as many
    words — so the pin has to carry the whole weight of "the caller acking as
    fksinv is fksinv". A pin shared across recipients could not: every
    recipient held the proof every other recipient needed, which is why one
    project could ack a bulletin AS another and land a false row in who_read.

    Keyed on a per-bulletin SECRET that is never published, so a recipient
    cannot derive a peer's code the way it could when the seed was the bulletin
    text it had just been shown. HMAC rather than a plain hash of secret+project
    because the secret is the key here, and hmac is the stdlib function for
    exactly that.
    """
    import hashlib
    import hmac
    mac = hmac.new(str(secret).encode(), str(project).strip().lower().encode(),
                   hashlib.sha256).hexdigest()
    return "%04d" % (int(mac[:8], 16) % 10000)


# 20200318  bulletin_pin — this project's code for this bulletin, or ''
def bulletin_pin(n, project):
    """Public because the READOUT has to render it, and the readout is built in
    handlers/exchange.py. Nothing else should need it: it is not a field in any
    response, by design.

    '' when there is no such bulletin, when the project is not one the registry
    knows, or when the bulletin is not addressed to it. A non-recipient getting a
    valid-looking code back would be the same cross-project leak one layer up —
    and the SAME three conditions read_bulletin refuses on, so a code can never
    be handed out that the ack would then reject.
    """
    b = bulletin(n)
    if not b:
        return ''
    project = (project or '').strip().lower()
    if not project:
        return ''
    # `projects` belongs to ensure_tables, and this is the first bulletin call
    # that reads it. Asked of its owner rather than created here, so the table
    # keeps one schema owner even when a bulletin is the first thing touched on
    # a fresh install.
    ensure_tables()
    c = _conn()
    known = _is_registered(c, project)
    c.close()
    if not known:
        return ''
    scope = (b.get('scope') or 'all').strip().lower()
    if scope != 'all' and scope != project:
        return ''
    secret = (b.get('secret') or '').strip()
    if not secret:
        # Should not happen: ensure_exchange backfills every row. If it does,
        # answer '' rather than falling back to the shared pin — a silent
        # fallback would quietly restore the hole this replaced.
        return ''
    return _recipient_pin(secret, project)


# 20200319  _is_registered — is this project one the registry knows
def _is_registered(c, project):
    """control.read_bulletin used to INSERT whatever project string it was
    handed without even asking whether such a project exists. So the matrix
    could name a reader that was never a project at all.

    Takes an open connection because its one caller already holds one, and
    opening a second here would have two connections writing one database for
    a single request.
    """
    row = c.execute('SELECT name FROM projects WHERE name=?',
                    ((project or '').strip().lower(),)).fetchone()
    return row is not None


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
    # The per-bulletin secret the per-recipient pins are derived from. Added
    # rather than replacing `pin`, because an ALTER that drops a column is a
    # rewrite of a live table and the old column is harmless once nothing reads
    # it. Nothing does: read_bulletin compares against _recipient_pin now.
    cols = [r[1] for r in c.execute('PRAGMA table_info(bulletins)')]
    if 'secret' not in cols:
        c.execute('ALTER TABLE bulletins ADD COLUMN secret TEXT')
    # BACKFILLED, which INVALIDATES EVERY PIN ALREADY HANDED OUT for a bulletin
    # published before this change. That is the intended cost and it is small:
    # the pin is rendered into the readout, so re-reading produces the new one,
    # and re-reading is the response this whole mechanism wants anyway. Leaving
    # the old shared pins working would have meant leaving the hole open for
    # every bulletin that already exists — which is all of them.
    for r in c.execute("SELECT n FROM bulletins WHERE secret IS NULL OR secret=''"
                       ).fetchall():
        c.execute('UPDATE bulletins SET secret=? WHERE n=?',
                  (_secrets.token_hex(16), r[0]))
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
    """Returns (n, recipients) — the bulletin number, and how its codes work.

    IT NO LONGER RETURNS A PIN, because there is no longer ONE pin. Each
    recipient gets its own, derived from a per-bulletin secret that is stored
    here and published nowhere; GET /api/bulletin/<n>?project=<p> renders that
    project's code into its readout. The operator therefore cannot paste "the"
    pin into the body, and does not need to: the readout has always carried it.
    """
    ensure_exchange()
    c = _conn()
    cur = c.execute('INSERT INTO bulletins '
                    '(scope,rung,title,body,action,pin,secret,published)'
                    ' VALUES (?,?,?,?,?,?,?,?)',
                    # pin '' rather than NULL: the column is kept for schema
                    # compatibility with an older hub reading this file, and an
                    # empty string is an honest "there is no shared pin" where a
                    # leftover value would be a wrong answer.
                    (scope, rung, title, body, action, '',
                     _secrets.token_hex(16), _now()))
    n = cur.lastrowid
    c.commit()
    c.close()
    return n, 'one code per recipient, rendered into that project\'s readout'


# 20200384  addressed — the one scope rule, asked in both directions
def addressed(scope, project):
    """Does a bulletin with this scope reach this project?

    ONE definition, because there used to be two and only one of them was
    right. bulletins_for asked it of the BULLETINS for a known project, in SQL
    ("scope='all' OR scope=?"). who_read asked it of the PROJECTS for a known
    bulletin -- and did not ask it at all. So a bulletin addressed to one
    project named every other project on the box as not having read something
    that was never sent to them.

    Both directions come through here now, and bulletins_for filters in Python
    rather than in SQL on purpose: a second expression of this rule, even a
    correct one, is a second thing that has to stay correct. There are tens of
    bulletins on a box, not millions.
    """
    s = (scope or 'all').strip().lower()
    return s == 'all' or s == (project or '').strip().lower()


BULLETIN_COLUMNS = 'n,scope,rung,title,action,published'
# NOT `pin` and NOT `secret`. The pin is per (bulletin, project), derived from
# `secret`, and rendered into that recipient's readout text -- never a field,
# never listable. A SELECT * on `bulletins` that reaches a response is a bug.


# 20200376  bulletins_for
def bulletins_for(project, unread_only=True):
    """Oldest first, because the ladder is ordered: a project cannot judge what
    is changing until it has confirmed what is."""
    ensure_exchange()
    project = (project or '').strip().lower()
    c = _conn()
    seen = set(r['bulletin'] for r in
               c.execute('SELECT bulletin FROM reads WHERE project=?', (project,)))
    out = []
    for b in c.execute('SELECT %s FROM bulletins ORDER BY n' % BULLETIN_COLUMNS):
        if not addressed(b['scope'], project):
            continue
        d = dict(b)
        d['read'] = b['n'] in seen
        if unread_only and d['read']:
            continue
        out.append(d)
    c.close()
    return out


# 20200386  all_bulletins — every bulletin on this server, addressed or not
def all_bulletins(scope='', limit=0):
    """The listing that did not exist.

    GET /api/bulletins/<project> could only answer "what was addressed to the
    project you thought to name". A bulletin scoped to a project nobody named
    was invisible from every address on the server -- published, stored,
    counted by nothing, and unfindable without opening the database by hand.

    Newest first, which is the opposite of bulletins_for and deliberate: that
    list is a LADDER a project climbs from the bottom; this one is a BOARD an
    operator reads from the top.
    """
    ensure_exchange()
    c = _conn()
    q = 'SELECT %s FROM bulletins' % BULLETIN_COLUMNS
    args = []
    if (scope or '').strip():
        q += ' WHERE scope=?'
        args.append(scope.strip().lower())
    q += ' ORDER BY n DESC'
    if limit and int(limit) > 0:
        q += ' LIMIT ?'
        args.append(int(limit))
    out = [dict(r) for r in c.execute(q, args)]
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
    it wrong, and locking would punish the only useful reaction.

    IT IS ALSO PROOF OF WHO IS READING, which it was not. This function INSERTed
    whatever `project` string it was handed — unchecked, and without even asking
    whether such a project exists — while the pin was shared by every recipient.
    So any project holding a bulletin could acknowledge it AS ANOTHER PROJECT,
    and the forged row landed in who_read: "the matrix, the most useful thing the
    server knows". Not a missing auth check. A FALSE ENTRY IN THE RECORD THE
    OPERATOR READS AS EVIDENCE, which is worse in kind than an absent one.

    Three checks now, in the order that gives the most useful refusal first:

      1. the project is one the registry knows. A reader that was never a
         project cannot be a true row in any matrix.
      2. the bulletin was addressed to it — scope 'all', or scope == project.
      3. the pin matches THIS project's code, which no other recipient holds.

    The refusal is shaped like outbox.acknowledge's: name the record, name what
    it says, name what was presented.
    """
    ensure_exchange()
    ensure_tables()                 # `projects`, whose owner is ensure_tables
    project = (project or '').strip().lower()
    if not project:
        return None, 'name yourself: project required'
    b = bulletin(n)
    if not b:
        return None, 'no such bulletin'
    c = _conn()
    if not _is_registered(c, project):
        c.close()
        return None, ('%s is not a project this server knows, so it cannot be '
                      'recorded as having read bulletin %s' % (project, n))
    c.close()
    scope = (b.get('scope') or 'all').strip().lower()
    if not addressed(scope, project):
        return None, ('bulletin %s is addressed to %s, not %s' % (n, scope, project))
    expected = bulletin_pin(n, project)
    if not expected or str(pin).strip() != expected:
        # Deliberately does NOT say what the right pin was, and deliberately
        # does not distinguish "wrong code" from "someone else's code": both are
        # answered by reading your own copy, and telling the caller which of the
        # two it got would help it hunt for another project's code.
        return None, ('pin does not match bulletin %s for %s - read your copy '
                      'again' % (n, project))
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
    """Who was TOLD, which of them has answered, and what they said.

    TWO WRONG ANSWERS, not two missing features.

    It listed every project in `projects` for any bulletin, with no reference
    to scope. A bulletin addressed to one project therefore reported "0 of 4"
    when the truth was "0 of 1", and named three projects as not having read
    something that was never sent to them. A matrix that counts people who
    were never told is not a matrix, it is an accusation. The denominator
    comes through addressed() now, the same rule bulletins_for uses.

    And it threw the ANSWER away. `reads` stores it and read_bulletin refuses
    an empty one -- "answer required, 'none' is valid, silence is not" -- so
    the server insists on collecting the single most useful fact on the board
    and then no route returned it. What a project said it would do is on the
    row.

    The answer here is the LATEST: a project may read twice, and the second
    answer supersedes the first. Every answer it ever gave, in order, is
    bulletin_trail(n). Neither carries the pin.
    """
    ensure_exchange()
    ensure_tables()                 # `projects`, whose owner is ensure_tables
    c = _conn()
    b = c.execute('SELECT scope FROM bulletins WHERE n=?', (n,)).fetchone()
    scope = b['scope'] if b else 'all'
    # ORDER BY id so the LAST row for a project wins the dict -- the latest
    # answer, not whichever one SQLite happened to hand back first.
    read = dict((r['project'], r) for r in c.execute(
        'SELECT project,answer,at FROM reads WHERE bulletin=? ORDER BY id', (n,)))
    out = []
    for p in c.execute('SELECT name FROM projects ORDER BY name'):
        if not addressed(scope, p['name']):
            continue                # never told, so not a row in this matrix
        r = read.get(p['name'])
        out.append({'project': p['name'], 'read': r is not None,
                    'at': r['at'] if r else None,
                    'answer': r['answer'] if r else None})
    c.close()
    return out


# 20200387  read_matrix — the matrix for many bulletins, in one pass
def read_matrix(ns):
    """who_read(n) is a pair of queries per bulletin. Drawing a board of 24
    bulletins that way costs 24 round trips after the list that named them --
    from a page that by doctrine holds nothing and assembles everything. This
    answers the same question for a whole set in three queries.

    The per-bulletin shape is deliberately identical to who_read's, so a
    caller can take either without branching.
    """
    ensure_exchange()
    ensure_tables()
    ns = [int(x) for x in (ns or [])]
    if not ns:
        return {}
    c = _conn()
    names = [p['name'] for p in c.execute('SELECT name FROM projects ORDER BY name')]
    marks = ','.join('?' * len(ns))
    scopes = dict((r['n'], r['scope']) for r in c.execute(
        'SELECT n,scope FROM bulletins WHERE n IN (%s)' % marks, ns))
    got = {}
    for r in c.execute('SELECT bulletin,project,answer,at FROM reads'
                       ' WHERE bulletin IN (%s) ORDER BY id' % marks, ns):
        got.setdefault(r['bulletin'], {})[r['project']] = r
    c.close()
    out = {}
    for n in ns:
        if n not in scopes:
            continue                # no such bulletin; say nothing about it
        seen = got.get(n, {})
        rows = []
        for name in names:
            if not addressed(scopes[n], name):
                continue
            r = seen.get(name)
            rows.append({'project': name, 'read': r is not None,
                         'at': r['at'] if r else None,
                         'answer': r['answer'] if r else None})
        out[n] = {'read': sum(1 for r in rows if r['read']),
                  'total': len(rows), 'readers': rows}
    return out


# 20200385  bulletin_trail — every acknowledgement of one bulletin, in order
def bulletin_trail(n):
    """The same shape as outbox.trail(message), and for the same reason.

    `reads` is append-only and nothing read it back as a sequence. A project
    that answered "will do Tuesday", read again on Thursday and answered
    "done" showed one row saying "done" -- true, and silent about the fact
    that it slipped. Append-only and never collapsed: two answers are two
    rows here, which is the true story.
    """
    ensure_exchange()
    c = _conn()
    out = [dict(r) for r in c.execute(
        'SELECT id,project,answer,at FROM reads WHERE bulletin=? ORDER BY id',
        (n,))]
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


# 20200388  tickets — the list, at any state, not only the open ones
def tickets(project=None, state='open'):
    """state: 'open' (anything not closed), 'closed', 'all', or one exact state.

    Only the open ones were ever reachable. close_ticket writes `resolution` --
    what the project ACTUALLY DID, and says right there that an unrecorded
    self-fix is indistinguishable from drift six weeks later -- and then
    closing the ticket was the last moment anyone could read it. The system
    could close a ticket and never show why.

    Default stays 'open', because open_tickets() and GET /api/tickets both
    mean that today and changing what they answer would be a different route
    wearing the same name.
    """
    ensure_exchange()
    c = _conn()
    state = (state or 'open').strip().lower()
    where, args = [], []
    if state == 'open':
        where.append("state!='closed'")
    elif state == 'closed':
        where.append("state='closed'")
    elif state != 'all':
        where.append('state=?')
        args.append(state)
    if project:
        where.append('project=?')
        args.append(project)
    q = 'SELECT * FROM tickets'
    if where:
        q += ' WHERE ' + ' AND '.join(where)
    out = [dict(r) for r in c.execute(q + ' ORDER BY id', args)]
    c.close()
    return out


# 20200389  ticket_by_id — one ticket, including how it ended
def ticket_by_id(tid):
    """There was no way to fetch one. A closed ticket's diagnosis and
    resolution existed only in a row that nothing selected."""
    ensure_exchange()
    c = _conn()
    r = c.execute('SELECT * FROM tickets WHERE id=?', (int(tid),)).fetchone()
    c.close()
    return dict(r) if r else None


def open_tickets(project=None):
    """Same answer as before, one implementation underneath it. Every existing
    caller keeps exactly what it had."""
    return tickets(project, state='open')


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
