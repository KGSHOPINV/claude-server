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
    c.execute("""CREATE TABLE IF NOT EXISTS releases (
        ref TEXT NOT NULL,
        state TEXT NOT NULL,              -- staged | promoted | rolled_back
        preflight TEXT,                   -- e.g. "8 of 10"
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


# 20200365  release — record a stage, promote or rollback
def release(ref, state, preflight='', note=''):
    if state not in ('staged', 'promoted', 'rolled_back'):
        return None, 'state must be staged|promoted|rolled_back'
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
