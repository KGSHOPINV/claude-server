#!/usr/bin/env python3
"""
# 20404707  tools.install-preflight — is this node actually finished?

MASTER.md documents an 11-step install order. bootstrap.sh is 241 lines and
implements five of them. Step 7 reads "Backup — set up before adding data" and
was never written, so ksgcohub has run since install with no backups at all.

Nobody noticed for one reason: a checklist item is prose, and prose has no
failure mode. "7. Backup" cannot be wrong, because nothing executes it. It sits
there looking correct while the machine disagrees.

This is that checklist as assertions. Each one asks the machine rather than a
document. Run it on any node, any time:

    python3 tools/install-preflight.py            report, exit 0
    python3 tools/install-preflight.py --strict   exit 1 if anything is missing
    python3 tools/install-preflight.py --offline  skip the one outbound probe

The point is not that it passes. The point is that "are we done" becomes a
command instead of a memory.

READS ONLY. Nothing here writes, installs, schedules or configures anything.
The strongest verb in the file is one HTTPS GET against this node's own public
hostname, which --offline removes.

Three checks used to over-report, and all three failed the same way: they
asserted something ADJACENT to the row instead of the row. Presence of a binary
instead of a backup running; availability of a disk instead of a copy landing on
it; a local record instead of a public name. Each one is now the question the
row actually asks, and each one carries the wrong verdict it replaces so nobody
re-derives it. See check_backups_running, check_backup_target, check_enrolled.
"""
import datetime as dt
import os
import re
import socket
import subprocess
import sys
import urllib.error
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from kernel import storage as st        # noqa: E402

try:
    from kernel import identity as ident
except Exception:                       # identity is optional on a bare box
    ident = None

OK, MISSING, WARN = 'ok', 'missing', 'warn'
MARK = {OK: '[x]', MISSING: '[ ]', WARN: '[~]'}

OFFLINE = '--offline' in sys.argv

# A daily timer (bootstrap.sh:815, OnCalendar 03:00 with a 15min jitter) means
# yesterday's set is normal and the day before that is a missed run. Two days.
BACKUP_STALE_DAYS = 2

# The unit bootstrap.sh:811 writes. Named exactly, NOT matched by the word
# "backup": this box also carries dpkg-db-backup.timer, which is Debian's
# package-database dump and would pass a word match while backing up none of
# this hub's data.
HUB_BACKUP_UNIT = 'hub-backup.timer'

# What counts as an invocation of THIS hub's backup, by path. bootstrap.sh:799
# installs hub/tools/backup.sh as ~/.local/bin/hub-backup.sh, so this is
# knowable rather than guessable.
HUB_BACKUP_CMDS = ('hub-backup.sh', 'hub/tools/backup.sh', 'server-backup')

# Backup tools that, if a schedule invokes one, are doing the job. Listed so the
# note can say what is installed -- never so that presence can pass a row.
BACKUP_TOOLS = ('server-backup', 'restic', 'borg', 'rsnapshot')

# A dated set as backup.sh names it: "$DEST_ROOT/$(date +%F)".
SET_RE = re.compile(r'^\d{4}-\d{2}-\d{2}$')

# Where a dated set can be. The DERIVED target is asked first, because that is
# what backup.sh gets from kernel.storage. The conventional roots follow because
# the copies that actually exist on fks-services are at /srv/backups/hub --
# written before the target was derived, and therefore invisible to a check that
# looks only where backups are supposed to go.
CONVENTIONAL_ROOTS = ('/backups', '/backup', '/srv/backups', '/srv/backups/hub',
                      '/mnt/backups', '/var/backups')

# Cloudflare answers urllib's default Python-urllib/3.x with 403 "error code:
# 1010" on every flareshub-* hostname, so a probe without a browser UA reports
# the whole fleet dead -- under-reporting in exactly the direction of the bug
# check_enrolled is here to fix.
UA = ('Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) '
      'Chrome/125.0 Safari/537.36')

# The zone of last resort. This is the door this build already serves, declared
# at hub/handlers/door.py:49 and overridable by the same variable, so the two
# agree by construction rather than by coincidence. Not imported: a handler
# pulls in kernel.auth and kernel.db, and a read-only preflight should not open
# a database to find out what it is called.
DOOR_HOST = os.environ.get('HUB_DOOR_HOST', 'flarevault.dev')


def sh(cmd):
    try:
        r = subprocess.run(cmd, shell=True, capture_output=True,
                           text=True, timeout=10)
        return r.returncode, r.stdout.strip()
    except Exception:
        return 1, ''


# ── backup facts, gathered once and shared by two checks ─────────────────────
# check_backup_target and check_backups_running both need to know what copies
# exist. They read it from here rather than each deciding for itself, because
# two answers to "what has been backed up" is how a report ends up disagreeing
# with itself on one page.

def _device_for(path, ms):
    """Which device holds this path: the longest mount point containing it.

    Resolved against kernel.storage's own mount list so this answer comes from
    the same place data_root() and backup_target() get theirs. Asking `df` here
    instead would be a second source of truth for the one comparison this file
    has already been burned by twice.
    """
    rp = os.path.realpath(path)
    best, best_len = None, -1
    for m in ms:
        t = m.get('target') or ''
        stem = '' if t == '/' else t.rstrip('/')
        if rp == (stem or '/') or rp.startswith(stem + '/'):
            if len(stem) > best_len:
                best, best_len = m, len(stem)
    return (best or {}).get('source', '')


def _manifest(path):
    """backup.sh writes MANIFEST.txt into every set it completes, carrying the
    machine_id of the box it copied. That makes "is this set mine" a fact on
    disk instead of an inference from a directory name -- which matters here:
    /srv/backups on fks-services has a metaforge/ sibling, and a check that
    trusted the path would have counted another project's dumps as the hub's.
    """
    out = {}
    try:
        with open(path, encoding='utf-8', errors='ignore') as f:
            for line in f:
                if not line.strip():
                    break               # the manifest header ends at the blank
                parts = line.split(None, 1)
                if len(parts) == 2:
                    out[parts[0]] = parts[1].strip()
    except Exception:
        return {}
    return out


def _age_days(name):
    try:
        y, m, d = (int(x) for x in name.split('-'))
        return (dt.date.today() - dt.date(y, m, d)).days
    except Exception:
        return None


def _sets_in(root):
    """Dated sets under one root, split by whether they belong to this machine.

    An unattributed directory (no MANIFEST.txt) is neither counted nor
    discarded silently -- it is reported, because a dated directory nothing
    claims is its own kind of unfinished.
    """
    mine, foreign, unclaimed = [], [], []
    try:
        names = sorted(os.listdir(root))
    except Exception:
        return mine, foreign, unclaimed
    mid = (ident.machine_id() if ident else '') or ''
    for n in names:
        p = os.path.join(root, n)
        if not SET_RE.match(n) or not os.path.isdir(p):
            continue
        man = _manifest(os.path.join(p, 'MANIFEST.txt'))
        if not man:
            unclaimed.append(n)
        elif not mid or not man.get('machine_id') or man['machine_id'] == mid:
            mine.append(n)
        else:
            foreign.append('%s (%s)' % (n, man.get('host') or man['machine_id'][:8]))
    return mine, foreign, unclaimed


def backup_sets(bt, ms):
    """Every root that holds at least one dated set belonging to this machine,
    newest first. Empty means nothing on this box has ever been backed up by
    this hub, whatever binaries are installed and whatever disks are free."""
    cands = []
    if bt.get('path'):
        cands.append(bt['path'])
    if os.environ.get('BACKUP_DEST'):
        cands.append(os.environ['BACKUP_DEST'])
    cands.extend(CONVENTIONAL_ROOTS)

    roots, seen = [], set()
    for r in cands:
        rp = os.path.realpath(r)
        if rp in seen or not os.path.isdir(rp):
            continue
        seen.add(rp)
        mine, foreign, unclaimed = _sets_in(rp)
        if not mine:
            continue
        newest = max(mine)
        roots.append({'path': r, 'dev': _device_for(r, ms), 'n': len(mine),
                      'newest': newest, 'age': _age_days(newest),
                      'foreign': foreign, 'unclaimed': unclaimed})
    roots.sort(key=lambda r: r['newest'], reverse=True)
    return roots


def _describe(roots):
    return '; '.join('%d set(s) in %s on %s, newest %s'
                     % (r['n'], r['path'], r['dev'] or '?', r['newest'])
                     for r in roots)


def _hub_backup_timer():
    """Is the hub's OWN backup timer active, in either scope? The unit is named
    rather than pattern-matched -- see HUB_BACKUP_UNIT."""
    for scope, label in (('--user ', 'user'), ('', 'system')):
        rc, out = sh('systemctl %sis-active %s 2>/dev/null'
                     % (scope, HUB_BACKUP_UNIT))
        if out == 'active':
            return 'active', label
        if out and out != 'inactive':
            # "not-found" is a different answer from "inactive" and the
            # difference is the whole finding on a node where bootstrap.sh's
            # step 7 never ran.
            return out, label
    return 'not-found', ''


def _cron_backup_lines():
    """Crontab lines that run something backup-shaped, split into this hub's
    and another project's. Attribution is by the command PATH.

    A grep for the word cannot tell /srv/backups/metaforge/backup.sh from
    ~/.local/bin/hub-backup.sh, and on fks-services only the first one exists
    -- so counting the word reported metaforge's nightly pg_dump as evidence
    that this hub was being backed up.
    """
    rc, out = sh('crontab -l 2>/dev/null')
    mine, foreign = [], []
    for raw in out.splitlines():
        line = raw.strip()
        if not line or line.startswith('#'):
            continue
        low = line.lower()
        if not any(w in low for w in ('backup', 'restic', 'borg', 'rsnapshot')):
            continue
        (mine if any(c in line for c in HUB_BACKUP_CMDS) else foreign).append(line)
    return mine, foreign


def _tools_present():
    return [c for c in BACKUP_TOOLS if sh('command -v %s' % c)[0] == 0]


# ── the checks ───────────────────────────────────────────────────────────────

def check_hub_service():
    rc, out = sh('systemctl --user is-enabled hub 2>/dev/null')
    if out == 'enabled':
        return OK, 'hub enabled as a systemd user service'
    rc, out = sh('systemctl --user is-active hub 2>/dev/null')
    if out == 'active':
        return WARN, 'hub running but not enabled — it will not survive a reboot'
    return MISSING, 'hub is not a systemd user service'


def check_identity():
    if ident is None:
        return MISSING, 'kernel.identity not importable'
    try:
        sid = ident.server_id()
        mid = ident.machine_id()
    except Exception as e:
        return MISSING, 'identity unreadable: %s' % e
    if not mid:
        return MISSING, 'no /etc/machine-id — the node has no stable key'
    if not sid:
        return MISSING, 'no server_id'
    return OK, '%s  (issuer: %s)' % (sid, ident.jwt_issuer())


def check_data_root():
    dr = st.data_root()
    if dr['dedicated']:
        m = dr['mount']
        return OK, '%s  (%sGB, %s%% used)' % (dr['path'], m['size_gb'], m['used_pct'])
    return WARN, 'no dedicated data disk — falling back to %s on the OS disk' % dr['path']


def check_backup_target():
    """Where the copy LANDS, which is what this row asks.

    The previous version answered a neighbouring question -- "is a second device
    available" -- and on fks-services passed with

        [x] backup target   /backup has 4211.2GB free on a different device (/dev/sdb1)

    while /backup held nothing but lost+found, and every copy that exists sat at
    /srv/backups/hub on /dev/mapper/ubuntu--vg-ubuntu--lv, THE SAME DEVICE as
    the data root. A free disk is not a landing site. An intended target nothing
    writes to protects nothing.

    The derived target comes from kernel.storage.backup_target(), the same
    function hub/tools/backup.sh asks for its destination, rather than from a
    directory name chosen here. Guessing the directory is how this row got
    contradicted twice: by a check that compared /backups against / instead of
    against the data's device. Intention and fact are both reported, and they
    are not conflated -- the derived target says where copies SHOULD go, and the
    dated sets say where any have actually gone.
    """
    ms = st.mounts()
    dr, bt = st.data_root(ms), st.backup_target(ms)
    data_dev = (dr.get('mount') or {}).get('source', '')
    tgt, tgt_dev = bt.get('path') or '', (bt.get('mount') or {}).get('source', '')
    roots = backup_sets(bt, ms)
    on_data = [r for r in roots if r['dev'] and r['dev'] == data_dev]
    off_data = [r for r in roots if r['dev'] and r['dev'] != data_dev]
    where = ('data at %s on %s' % (dr.get('path'), data_dev or '?'))

    if not bt.get('dedicated') or not tgt_dev:
        return MISSING, ('no second device — every mount shares a disk with the '
                         '%s, so a copy here survives a bad rm and nothing '
                         'else%s' % (where, '. ' + bt['note'] if bt.get('note') else ''))
    if tgt_dev == data_dev:
        return MISSING, ('the derived target %s shares device %s with the %s — '
                         'one disk failure takes both'
                         % (tgt, tgt_dev, where))
    if on_data and off_data:
        return WARN, ('%s, and some copies land on the data\'s own device: %s. '
                      'Safe copies: %s. Derived target is %s on %s.'
                      % (where, _describe(on_data), _describe(off_data),
                         tgt, tgt_dev))
    if on_data:
        return MISSING, ('%s, and EVERY copy that exists is on that same '
                         'device: %s. kernel.storage derives %s on %s, a '
                         'different device, and nothing has ever written there '
                         '— an intended target nothing writes to protects '
                         'nothing.'
                         % (where, _describe(on_data), tgt, tgt_dev))
    if off_data:
        return OK, ('copies land off the data\'s device: %s (%s). Derived '
                    'target: %s on %s.'
                    % (_describe(off_data), where, tgt, tgt_dev))
    return WARN, ('%s on %s is a different device from the %s, so the row is '
                  'satisfiable — but no dated set attributed to this machine '
                  'exists anywhere. The target is derived and has never been '
                  'written to.' % (tgt, tgt_dev, where))


def check_backups_running():
    """Two facts, and the previous version asserted neither.

    It returned OK on the PRESENCE of a server-backup / restic / borg /
    rsnapshot binary anywhere on PATH, so on fks-services it printed

        [x] backups running   backup tool present: server-backup

    while server-backup was merely shipped by server-kit, nothing scheduled it,
    hub-backup.timer did not exist, and the newest set on the box was three days
    stale. A binary nothing invokes has never copied anything.

    It also counted any crontab line containing the word "backup", which on
    fks-services matches

        0 2 * * * /srv/backups/metaforge/backup.sh

    -- metaforge's backup, not this hub's. A word is not an attribution; the
    path is. Same failure as the /backups-versus-/ comparison this tool was
    already burned by: the check matched something adjacent to the question.

    So the row now requires both halves of "running": a schedule that is ACTIVE,
    and a dated set on disk that is RECENT and carries this machine's id.
    Installed binaries are reported as a note and can never carry the row.
    """
    ms = st.mounts()
    bt = st.backup_target(ms)
    roots = backup_sets(bt, ms)
    timer, scope = _hub_backup_timer()
    cron_mine, cron_foreign = _cron_backup_lines()
    scheduled = timer == 'active' or bool(cron_mine)

    newest = roots[0] if roots else None
    age = newest['age'] if newest else None
    fresh = age is not None and age <= BACKUP_STALE_DAYS

    sched_txt = ('%s is active (%s scope)' % (HUB_BACKUP_UNIT, scope)
                 if timer == 'active'
                 else '%s is %s' % (HUB_BACKUP_UNIT, timer))
    if cron_mine:
        sched_txt += '; cron runs this hub\'s backup (%s)' % cron_mine[0]
    sets_txt = (_describe(roots) + (', %d day(s) old' % age if age is not None else '')
                if roots else 'no dated set attributed to this machine anywhere')

    # Notes, never verdicts. Each one names a thing that LOOKS like evidence
    # that backups run and is not.
    notes = []
    tools = _tools_present()
    if tools and not scheduled:
        notes.append('%s on PATH but nothing invokes it — presence is not a '
                     'schedule' % ', '.join('`%s`' % t for t in tools))
    if cron_foreign:
        notes.append('%d crontab line(s) mention backup and belong to another '
                     'project, read the path not the word: %s'
                     % (len(cron_foreign), '; '.join(cron_foreign)))
    for r in roots:
        if r['foreign']:
            notes.append('sets in %s belong to another machine: %s'
                         % (r['path'], ', '.join(r['foreign'])))
        if r['unclaimed']:
            notes.append('dated dirs in %s carry no MANIFEST.txt, so nothing '
                         'claims them: %s' % (r['path'], ', '.join(r['unclaimed'])))
    tail = ('. ' + '. '.join(notes)) if notes else ''

    if scheduled and fresh:
        return OK, '%s; %s%s' % (sched_txt, sets_txt, tail)
    if scheduled:
        return WARN, ('%s, but nothing recent has landed: %s. A schedule that '
                      'produces no copy is not a backup%s'
                      % (sched_txt, sets_txt, tail))
    if fresh:
        return WARN, ('a set from %s exists (%s), but no active schedule: %s '
                      'and no crontab line runs this hub\'s backup. Nothing '
                      'will make the next copy%s'
                      % (newest['newest'], _describe([newest]), sched_txt, tail))
    return MISSING, ('nothing is being backed up: %s, and %s%s'
                     % (sched_txt, sets_txt, tail))


def check_reclamation():
    """Checks BOTH scopes. The first version of this looked only at system
    timers and matched only "prune" -- so it reported missing while a user
    timer named hub-reclaim was installed and scheduled. The assertion was
    wrong, not the machine, which is the failure mode assertions are supposed
    to remove. Hence: both scopes, and match the words actually used."""
    pat = 'prune|reclaim|docker-clean'
    for scope in ('--user ', ''):
        rc, out = sh('systemctl %slist-timers --all --no-pager 2>/dev/null | '
                     'grep -ciE "%s"' % (scope, pat))
        if out.isdigit() and int(out) > 0:
            where = 'user' if scope else 'system'
            return OK, 'a reclamation timer is registered (%s scope)' % where
    rc, out = sh('crontab -l 2>/dev/null | grep -ciE "%s|docker system"' % pat)
    if out.isdigit() and int(out) > 0:
        return OK, 'a reclamation cron entry exists'
    cache = st.docker_storage()['build_cache']
    detail = 'nothing reclaims Docker build cache'
    if cache['reclaimable_gb'] >= st.CACHE_BLOAT_GB:
        detail += ' — %sGB is reclaimable right now' % cache['reclaimable_gb']
    return MISSING, detail


def check_storage_sound():
    f = st.findings()
    bad = [i for i in f if i['severity'] in ('high', 'warn')]
    if not bad:
        return OK, 'no storage findings'
    return WARN, '; '.join(i['detail'] for i in bad)


def check_layout():
    """The on-disk layout is a convention, and an undeclared convention is one
    nobody can be wrong about out loud.

    The canonical instance: bootstrap.sh:118 creates ~/db and seeds the admin
    password into ~/db/server.db, while kernel/db.py:15 opens
    <repo>/db/server.db. On a node cloned to ~/hub those are different files,
    so the password the operator typed goes somewhere nothing reads and
    db.py:96 seeds sha256('admin') instead. Every bootstrapped node therefore
    stands on admin/admin, and nothing said so.

    This asserts the one thing that actually matters: the database the hub
    opens is the database that exists, and no rival copy is sitting elsewhere
    pretending to be it.
    """
    try:
        from kernel.db import DB_PATH
    except Exception as e:
        return MISSING, 'cannot resolve the hub database path: %s' % e

    home = os.path.expanduser('~')
    rivals = [p for p in (os.path.join(home, 'db', 'server.db'),
                          os.path.join(home, 'hub', 'db', 'server.db'))
              if os.path.exists(p) and os.path.abspath(p) != os.path.abspath(DB_PATH)]

    if not os.path.exists(DB_PATH):
        return MISSING, 'the hub database does not exist at %s' % DB_PATH
    if rivals:
        return WARN, ('a second database exists at %s — the hub reads %s, so '
                      'anything seeded into the other one is invisible'
                      % (rivals[0], DB_PATH))
    return OK, 'hub database at %s, no rival copy' % DB_PATH


def check_default_password():
    """A node reachable from the internet standing on admin/admin is not a
    configuration preference. Checked by hash so nothing is ever printed."""
    try:
        import hashlib
        import sqlite3
        from kernel.db import DB_PATH
        if not os.path.exists(DB_PATH):
            return MISSING, 'no database to check'
        c = sqlite3.connect('file:%s?mode=ro' % DB_PATH, uri=True)
        rows = c.execute('SELECT username, password_hash FROM users').fetchall()
        c.close()
    except Exception as e:
        return MISSING, 'cannot read users: %s' % e

    weak = hashlib.sha256(b'admin').hexdigest()
    bad = [u for u, h in rows if h == weak]
    if bad:
        return MISSING, ('%s still uses the seeded default password'
                         % ', '.join(bad))
    return OK, '%d user(s), none on the seeded default' % len(rows)


def _zone():
    """This node's zone, and which of four places said so.

    enroll.sh:448 writes the zone into ~/.flare/node.json — the very file this
    check used to treat as the ONLY evidence of enrolment — so on a node with no
    node.json the zone has to come from somewhere else or the public hostname
    cannot be derived at all. $FLARE_ZONE and ~/.flare/zone are what
    bootstrap.sh:872-882 reads. DOOR_HOST is the last resort.
    """
    z = (os.environ.get('FLARE_ZONE') or '').strip()
    if z:
        return z, '$FLARE_ZONE'
    try:
        with open(os.path.expanduser('~/.flare/zone'), encoding='utf-8') as f:
            z = f.read().strip()
        if z:
            return z, '~/.flare/zone'
    except Exception:
        pass
    try:
        import json
        with open(os.path.expanduser('~/.flare/node.json'), encoding='utf-8') as f:
            z = (json.load(f).get('zone') or '').strip()
        if z:
            return z, '~/.flare/node.json'
    except Exception:
        pass
    return DOOR_HOST, 'the door host this build serves (handlers/door.py:49)'


def _expected_host():
    """flareshub-<server-id>.<zone>, built with enroll.sh:105's own formula.

    The name is derived from /etc/machine-id, not from what the box is called,
    so it is knowable on a node that has no record of its own enrolment. That
    is the whole reason this check can now ask the edge at all.
    """
    sid = (ident.server_id() if ident else '') or ''
    zone, zsrc = _zone()
    if not sid or not zone:
        return '', zone, zsrc
    return 'flareshub-%s.%s' % (sid.replace('_', '-'), zone), zone, zsrc


def _edge(host):
    """What a caller with NO credential gets from this hostname.

    Returns (code, kind, verdict) where verdict is one of:

        gated        the name exists and a gate refuses an anonymous caller
        ungated      the name exists and served a stranger — the gate is missing
        no-name      DNS does not resolve, so no public name exists
        unclear      the name resolves but the answer settles nothing

    DNS is resolved separately on purpose. Without that, a node with no outbound
    route cannot tell "this hostname does not exist" from "I could not ask", and
    would report the first while meaning the second — the same over-reporting
    this check was written to remove, pointed the other way.

    A gated answer proves the tunnel route, the DNS record and the Access
    application exist. It does NOT prove the connector on this node is up:
    Access refuses at the edge before anything reaches an origin.
    """
    try:
        socket.getaddrinfo(host, 443)
    except socket.gaierror:
        return 0, 'DNS does not resolve', 'no-name'
    except Exception as e:
        return 0, 'DNS lookup failed (%s)' % type(e).__name__, 'unclear'

    req = urllib.request.Request('https://' + host, headers={'User-Agent': UA})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            code, body = r.status, r.read(4000).decode('utf-8', 'replace')
    except urllib.error.HTTPError as e:
        code = e.code
        try:
            body = e.read(4000).decode('utf-8', 'replace')
        except Exception:
            body = ''
    except Exception as e:
        return 0, 'resolves but did not answer (%s)' % type(e).__name__, 'unclear'

    low = body.lower()
    if 'cloudflare access' in low and 'sign in' in low:
        return code, 'the Access sign-in page, served inline', 'gated'
    if code == 401:
        return code, 'refused with no credential, which is what a node '\
                     'endpoint must do', 'gated'
    if code == 403:
        # Could be the WAF rather than Access, and the difference matters, so
        # this settles nothing rather than guessing which.
        return code, 'blocked — likely the WAF rather than Access', 'unclear'
    if code == 200:
        # enroll.sh:107-118 records this happening for about four minutes: a
        # second hostname reached the same origin with no Access application in
        # front of it, and /api/config was readable by a stranger. Reporting
        # this as "enrolled" would be the tool over-reporting again.
        return code, 'answered a stranger — no gate in front of it', 'ungated'
    return code, 'unexpected answer', 'unclear'


def check_enrolled():
    """Reachable by name, which is a fact about the EDGE.

    ~/.flare/node.json is a record the node keeps about itself, and reading it
    alone was the whole check. The two can disagree in the dangerous direction:
    fks-services has no node.json and reported

        [ ] enrolled   not enrolled — no public hostname (run enroll.sh)

    while https://flareshub-fvn-3b8c1b.flarevault.dev answers HTTP 401, so the
    tunnel, the DNS record and the Access application all exist. That node is
    enrolled at the edge with no local record of it — which is not "not
    enrolled", it is a tunnel nothing will ever decommission. A missing record
    is recoverable by running enroll.sh; an unrecorded tunnel is not, because
    nothing local will ever tell you it is there.

    The hostname is derived rather than read, so the absence of the record does
    not prevent the question being asked. --offline skips the probe.
    """
    local = os.path.exists(os.path.expanduser('~/.flare/node.json'))
    host, zone, zsrc = _expected_host()
    derived = 'derived as %s from server_id + zone %s (%s)' % (host, zone, zsrc)

    if not host:
        return (OK if local else MISSING), (
            'no public hostname could be derived (server_id or zone missing, '
            'zone source: %s) — %s' % (zsrc,
            '~/.flare/node.json is present, so enrolment is unverified at the edge'
            if local else 'not enrolled (run enroll.sh)'))
    if OFFLINE:
        return (OK if local else MISSING), (
            '%s; edge not probed (--offline). %s'
            % ('~/.flare/node.json present' if local else 'no ~/.flare/node.json',
               derived))

    code, kind, verdict = _edge(host)
    answer = '%s answers HTTP %s (%s)' % (host, code, kind)

    # An ungated public hostname is not a finished node under any reading, and
    # the Access application is part of what enroll.sh creates -- so this can
    # never pass, with or without a local record.
    if verdict == 'ungated':
        return MISSING, ('REACHABLE BY NAME AND UNGATED — %s, so a stranger '
                         'reaches this hub with no credential. The name exists; '
                         'the Access application in front of it does not. %s'
                         % (answer, 'Local record present.' if local
                            else 'There is no ~/.flare/node.json either.'))
    # Inconclusive stays inconclusive. Calling an unanswered probe "no public
    # name" would assert the absence of a hostname from the absence of a route
    # to it, which is the same shape of error as the three bugs above.
    if verdict == 'unclear':
        return WARN, ('cannot tell from here — %s, which settles nothing. %s %s'
                      % (answer,
                         '~/.flare/node.json is present.' if local
                         else 'There is no ~/.flare/node.json.', derived))
    if local and verdict == 'gated':
        return OK, 'enrolled — ~/.flare/node.json present and %s' % answer
    if local:
        return WARN, ('~/.flare/node.json says enrolled, but %s. The record '
                      'outlived the hostname.' % answer)
    if verdict == 'gated':
        return WARN, ('ENROLLED AT THE EDGE WITH NO LOCAL RECORD — %s, so '
                      'the tunnel route, the DNS record and the Access '
                      'application all exist, but there is no '
                      '~/.flare/node.json here and nothing on this node knows '
                      'the hostname. This is not "not enrolled": a missing '
                      'record can be rebuilt by re-running enroll.sh, an '
                      'unrecorded tunnel is one nothing will ever '
                      'decommission. Hostname %s.' % (answer, derived))
    return MISSING, ('not enrolled — no ~/.flare/node.json, and %s, so no '
                     'public name exists either (run enroll.sh). The hostname '
                     'would be %s' % (answer, derived))


CHECKS = [
    ('hub service',      check_hub_service),
    ('identity',         check_identity),
    ('data root',        check_data_root),
    ('backup target',    check_backup_target),
    ('backups running',  check_backups_running),
    ('cache reclamation', check_reclamation),
    ('storage sound',    check_storage_sound),
    ('layout',           check_layout),
    ('admin password',   check_default_password),
    ('enrolled',         check_enrolled),
]


def main():
    strict = '--strict' in sys.argv
    print('Install preflight\n')

    results = []
    for name, fn in CHECKS:
        try:
            state, detail = fn()
        except Exception as e:
            state, detail = MISSING, 'check failed: %s' % e
        results.append(state)
        print('  %s %-18s %s' % (MARK[state], name, detail))

    done = results.count(OK)
    print('\n%d of %d complete' % (done, len(CHECKS)))

    if MISSING in results:
        print('\nThis node is not finished. The gaps above are what '
              'bootstrap.sh should have done.')
    if strict and (MISSING in results or WARN in results):
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
