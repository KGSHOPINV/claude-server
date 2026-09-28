#!/usr/bin/env python3
"""
# 20200013  kernel.storage — the storage landscape, derived from the machine

Written after ksgcohub was found carrying 40GB of dead Docker build cache on a
98GB OS disk while a 458GB data disk sat 99% empty. Nothing was broken. Nobody
was told. It was simply never checked, for two weeks.

That is the failure this module exists to prevent, and the fix is the project's
standing rule: DERIVE, DO NOT MAINTAIN. A hardcoded data path is a guess about
hardware, and hardware varies — one disk, two disks, a large empty mount, none
at all. So the hub reads the machine and answers from what is actually there.

Everything here is read-only. Nothing in this module changes a byte on disk: it
reports, and the caller decides. Findings carry the command that would fix them
rather than running it, because "the monitor quietly repartitioned your server"
is a worse outcome than a full disk.
"""
import datetime as dt
import json
import os
import re
import subprocess
import threading
import time

GB = 1024 ** 3

# Disks do not change between heartbeats, but /api/node is polled every 30s and
# each landscape() shells out three times. Cache the derivation rather than the
# conclusion: still derived, just not re-derived on every poll.
CACHE_TTL = 120
_cache = {'at': 0.0, 'value': None}
_lock = threading.Lock()

# A mount must be at least this large to serve as a data root, and this much
# bigger than the OS disk before relocating onto it is worth suggesting.
MIN_DATA_GB = 50
DATA_MULTIPLE = 2

# Thresholds, deliberately generous. A finding that fires constantly gets
# ignored, which is the same as not having it.
CACHE_BLOAT_GB = 5
DISK_PRESSURE_PCT = 85
UNUSED_DISK_PCT = 5

REAL_FS = ('ext4', 'ext3', 'xfs', 'btrfs', 'zfs')

# A mount NAMED for backups is a declaration of intent, and intent beats size.
# Found the hard way: fks-services has a 4.4TB disk at /backup and a 1TB OS
# disk, so "largest non-OS mount wins" confidently nominated the backup drive
# as the place to put live project data. The operator already answered this
# question when they chose the mount point; the code should read the answer
# rather than re-decide it.
BACKUP_HINTS = ('backup', 'backups', 'archive', 'snapshots')


def _named_for_backup(target):
    leaf = (target or '').rstrip('/').rsplit('/', 1)[-1].lower()
    return any(h in leaf for h in BACKUP_HINTS)


def _run(cmd, timeout=10):
    try:
        r = subprocess.run(cmd, shell=True, capture_output=True,
                           text=True, timeout=timeout)
        return r.stdout.strip() if r.returncode == 0 else ''
    except Exception:
        return ''


def _say(cmd, timeout=10):
    """Stdout whatever the exit code. `systemctl is-active` exits non-zero for
    BOTH "inactive" and "not-found", and _run would flatten the two to ''. The
    difference between a timer that exists and one that was never installed is
    the entire finding on a node where the backup step never ran, so the word
    has to survive the exit code."""
    try:
        r = subprocess.run(cmd, shell=True, capture_output=True,
                           text=True, timeout=timeout)
        return r.stdout.strip()
    except Exception:
        return ''


def _to_gb(s):
    """Docker prints '40.29GB', '6.598MB', '1.2GB (100%)'. Parse loosely."""
    s = (s or '').split('(')[0].strip().upper()
    for unit, mult in (('TB', 1024.0), ('GB', 1.0),
                       ('MB', 1 / 1024.0), ('KB', 1 / 1048576.0)):
        if s.endswith(unit):
            try:
                return round(float(s[:-len(unit)].strip()) * mult, 2)
            except Exception:
                return 0.0
    return 0.0


def _int(s):
    digits = ''.join(c for c in (s or '') if c.isdigit())
    return int(digits) if digits else 0


# 20200351  mounts — every real filesystem, as the kernel sees it
def mounts():
    """Only real on-disk filesystems.

    snap/squashfs/tmpfs/overlay are excluded: they are not places data can
    live, and including them makes the largest mount a read-only snap image.
    """
    out = _run('findmnt -J -b -o TARGET,SOURCE,FSTYPE,SIZE,USED,AVAIL')
    if not out:
        return []
    try:
        tree = json.loads(out)
    except Exception:
        return []

    found = []

    def walk(nodes):
        for n in nodes or []:
            if n.get('fstype') in REAL_FS:
                size = int(n.get('size') or 0)
                used = int(n.get('used') or 0)
                found.append({
                    'target':   n.get('target', ''),
                    'source':   n.get('source', ''),
                    'fstype':   n.get('fstype', ''),
                    'size_gb':  round(size / GB, 1),
                    'used_gb':  round(used / GB, 1),
                    'avail_gb': round(int(n.get('avail') or 0) / GB, 1),
                    'used_pct': round(100 * used / size) if size else 0,
                })
            walk(n.get('children'))

    walk(tree.get('filesystems'))

    # One device bind-mounted twice is still one filesystem. Counting it twice
    # would overstate the capacity of the machine.
    seen, uniq = set(), []
    for m in found:
        if m['source'] in seen:
            continue
        seen.add(m['source'])
        uniq.append(m)
    return uniq


# 20200352  docker_storage — where Docker actually keeps things
def docker_storage():
    """Docker Root Dir holds images; the build cache may live elsewhere.

    That distinction is the whole incident: 40GB hid in /var/lib/containerd
    while /var/lib/docker reported a harmless 1.6GB.
    """
    info = _run("docker info 2>/dev/null | grep -i 'docker root dir'")
    root = info.split(':', 1)[1].strip() if ':' in info else ''

    cache = {'size_gb': 0.0, 'reclaimable_gb': 0.0, 'active': 0}
    out = _run("docker system df "
               "--format '{{.Type}}|{{.Size}}|{{.Reclaimable}}|{{.Active}}'")
    for line in out.splitlines():
        p = line.split('|')
        if len(p) >= 4 and p[0].strip().lower().startswith('build'):
            cache = {'size_gb': _to_gb(p[1]),
                     'reclaimable_gb': _to_gb(p[2]),
                     'active': _int(p[3])}
    return {'root': root, 'build_cache': cache}


# 20200353  data_root — where project data SHOULD live on this machine
def data_root(ms=None):
    """The largest real mount that is not the OS disk, if one is big enough;
    otherwise the OS disk, labelled honestly as the fallback rather than
    pretending a second disk exists.

    This is the answer /api/admit gives a new project, so it has to describe
    THIS machine rather than a convention that happened to fit another one.
    """
    ms = ms if ms is not None else mounts()
    root = next((m for m in ms if m['target'] == '/'), None)
    others = [m for m in ms
              if m['target'] not in ('/', '/boot', '/boot/efi')
              and m['size_gb'] >= MIN_DATA_GB]
    # Mounts declared for backups are excluded, however large. A 4.4TB drive
    # called /backup is not an invitation to put live data on it.
    candidates = [m for m in others if not _named_for_backup(m['target'])]
    if candidates:
        best = max(candidates, key=lambda m: m['size_gb'])
        return {'path': best['target'], 'mount': best, 'dedicated': True}
    return {'path': '/srv/docker', 'mount': root, 'dedicated': False,
            'note': ('the only large mounts are named for backups — live data '
                     'stays on the OS disk') if others else ''}


# 20200356  backup_target — where backups go, never the disk holding the data
def backup_target(ms=None):
    """A copy on the same physical device as the data survives a bad rm and
    nothing else. findmnt reports the source device, so this is checked rather
    than assumed.

    Preference order: a mount the operator NAMED for backups, then any other
    device by free space. Returns dedicated=False when nothing qualifies, which
    is the honest answer on a single-disk box.
    """
    ms = ms if ms is not None else mounts()
    dr = data_root(ms)
    data_dev = (dr.get('mount') or {}).get('source', '')
    usable = [m for m in ms
              if m['source'] != data_dev and m['target'] not in ('/boot', '/boot/efi')]
    if not usable:
        return {'path': '', 'mount': None, 'dedicated': False,
                'note': 'no second device — a backup here would not survive '
                        'losing the disk'}
    named = [m for m in usable if _named_for_backup(m['target'])]
    best = max(named or usable, key=lambda m: m['avail_gb'])
    return {'path': best['target'].rstrip('/') + '/backups' if not _named_for_backup(best['target'])
                    else best['target'],
            'mount': best, 'dedicated': True,
            'declared': bool(named)}


# ── is anything actually being backed up? ────────────────────────────────────
# backup_target() above answers where a copy SHOULD land. This section answers
# whether one ever DOES, which is a different question and has been answered
# wrongly in two places for the same reason: each asked something adjacent.
#
#   hub/tools/install-preflight.py   passed "backups running" on the PRESENCE
#                                    of a server-backup binary (fixed 2e71992).
#   kernel/collect.py step 09        ticked the install step Backup on the
#                                    PRESENCE of a server-backup binary, and
#                                    fed that tick to the hub's install-steps
#                                    display in app.html.
#
# Both were wrong on fks-services in the same direction, on the same box, on
# the same day: server-backup ships with server-kit, nothing schedules it,
# hub-backup.timer is not-found, and the newest set is stale. A binary nothing
# invokes has never copied anything.
#
# It lives here, in the kernel, rather than in either caller, because a tool
# and a handler disagreeing about whether this machine is backed up is how one
# report ends up contradicting another on the same page. One derivation: the
# tool prints it, the step reads its verdict. Dependencies still flow one way —
# handlers and tools read the kernel, never the reverse.

# A daily timer (bootstrap.sh:815, OnCalendar 03:00 with a 15min jitter) means
# yesterday's set is normal and the day before that is a missed run. Two days.
BACKUP_STALE_DAYS = 2

# The unit bootstrap.sh:811 writes. Named exactly, NOT matched by the word
# "backup": these boxes also carry dpkg-db-backup.timer, which is Debian's
# package-database dump and would pass a word match while backing up none of
# this hub's data.
HUB_BACKUP_UNIT = 'hub-backup.timer'

# What counts as an invocation of THIS hub's backup, by path. bootstrap.sh:799
# installs hub/tools/backup.sh as ~/.local/bin/hub-backup.sh, so this is
# knowable rather than guessable.
HUB_BACKUP_CMDS = ('hub-backup.sh', 'hub/tools/backup.sh', 'server-backup')

# Backup tools that, if a schedule invokes one, are doing the job. Listed so a
# report can say what is installed — never so that presence can pass a row.
BACKUP_TOOLS = ('server-backup', 'restic', 'borg', 'rsnapshot')

# A dated set as backup.sh names it: "$DEST_ROOT/$(date +%F)".
SET_RE = re.compile(r'^\d{4}-\d{2}-\d{2}$')

# Where a dated set can be. The DERIVED target is asked first, because that is
# what backup.sh gets from this module. The conventional roots follow because
# the copies that actually exist on fks-services are at /srv/backups/hub —
# written before the target was derived, and therefore invisible to a check
# that looks only where backups are supposed to go.
CONVENTIONAL_ROOTS = ('/backups', '/backup', '/srv/backups', '/srv/backups/hub',
                      '/mnt/backups', '/var/backups')

_backup_cache = {'at': 0.0, 'value': None}


def _ok(cmd, timeout=5):
    try:
        return subprocess.run(cmd, shell=True, capture_output=True,
                              timeout=timeout).returncode == 0
    except Exception:
        return False


def _machine_id():
    """This node's stable key, for attributing a set to this machine.

    kernel.identity is asked first so the answer matches everything else the
    hub says about itself, and /etc/machine-id is the fallback: identity is
    optional on a bare box, and a module that cannot be imported must not take
    the backup question down with it. Imported inside the function because
    identity is a peer, not a dependency of the storage landscape.
    """
    try:
        from kernel import identity as _ident
        mid = _ident.machine_id()
        if mid:
            return mid
    except Exception:
        pass
    try:
        with open('/etc/machine-id', encoding='utf-8') as f:
            return f.read().strip()
    except Exception:
        return ''


def _device_for(path, ms):
    """Which device holds this path: the longest mount point containing it.

    Resolved against this module's own mount list so the answer comes from the
    same place data_root() and backup_target() get theirs. Asking `df` here
    would be a second source of truth for the one comparison these checks have
    already been burned by twice.
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
    disk instead of an inference from a directory name — which matters here:
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


def _sets_in(root, mid):
    """Dated sets under one root, split by whether they belong to this machine.

    An unattributed directory (no MANIFEST.txt) is neither counted nor
    discarded silently — it is reported, because a dated directory nothing
    claims is its own kind of unfinished.
    """
    mine, foreign, unclaimed = [], [], []
    try:
        names = sorted(os.listdir(root))
    except Exception:
        return mine, foreign, unclaimed
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


def _walk_roots(bt, ms):
    """Every existing candidate root, each with its sets split three ways.

    Separated from backup_sets() because the two callers want different halves
    of this: a verdict needs only the sets that are MINE, while a report must
    also mention the ones that are not. Folding them together is what made a
    root holding nothing but another machine's sets disappear from the report
    entirely -- see backup_state.
    """
    mid = _machine_id()
    cands = []
    if bt.get('path'):
        cands.append(bt['path'])
    if os.environ.get('BACKUP_DEST'):
        cands.append(os.environ['BACKUP_DEST'])
    cands.extend(CONVENTIONAL_ROOTS)

    out, seen = [], set()
    for r in cands:
        rp = os.path.realpath(r)
        if rp in seen or not os.path.isdir(rp):
            continue
        seen.add(rp)
        mine, foreign, unclaimed = _sets_in(rp, mid)
        if not (mine or foreign or unclaimed):
            continue
        out.append({'path': r, 'dev': _device_for(r, ms), 'mine': mine,
                    'foreign': foreign, 'unclaimed': unclaimed})
    return out


# 20200357  backup_sets — every dated set on this box that belongs to this box
def backup_sets(bt=None, ms=None):
    """Every root holding at least one dated set attributed to this machine,
    newest first. Empty means nothing here has ever been backed up by this hub,
    whatever binaries are installed and whatever disks are free.

    Sets belonging to another machine, and dated directories nothing claims,
    are deliberately NOT here: this is the evidence a verdict may rest on. They
    are reported by backup_state() instead, which is where they belong -- a
    directory full of someone else's backups is a fact an operator needs and
    not a fact that can tick a row.
    """
    ms = ms if ms is not None else mounts()
    bt = bt if bt is not None else backup_target(ms)

    roots = []
    for r in _walk_roots(bt, ms):
        if not r['mine']:
            continue
        newest = max(r['mine'])
        roots.append({'path': r['path'], 'dev': r['dev'], 'n': len(r['mine']),
                      'newest': newest, 'age': _age_days(newest),
                      'foreign': r['foreign'], 'unclaimed': r['unclaimed']})
    roots.sort(key=lambda r: r['newest'], reverse=True)
    return roots


def describe_sets(roots):
    return '; '.join('%d set(s) in %s on %s, newest %s'
                     % (r['n'], r['path'], r['dev'] or '?', r['newest'])
                     for r in roots)


def _hub_backup_timer():
    """Is the hub's OWN backup timer active, in either scope? The unit is named
    rather than pattern-matched — see HUB_BACKUP_UNIT."""
    for scope, label in (('--user ', 'user'), ('', 'system')):
        out = _say('systemctl %sis-active %s 2>/dev/null'
                   % (scope, HUB_BACKUP_UNIT))
        if out == 'active':
            return 'active', label
        if out and out != 'inactive':
            # "not-found" is a different answer from "inactive", and the
            # difference is the whole finding on a node where the backup step
            # never ran.
            return out, label
    return 'not-found', ''


def _cron_backup_lines():
    """Crontab lines that run something backup-shaped, split into this hub's
    and another project's. Attribution is by the command PATH.

    A grep for the word cannot tell /srv/backups/metaforge/backup.sh from
    ~/.local/bin/hub-backup.sh, and on fks-services only the first one exists
    — so counting the word reported metaforge's nightly dump as evidence that
    this hub was being backed up.
    """
    out = _say('crontab -l 2>/dev/null')
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


def backup_tools_present():
    """What is INSTALLED. A note for a report, never a verdict: this is the
    exact fact that carried two wrong ticks."""
    return [c for c in BACKUP_TOOLS if _ok('command -v %s' % c)]


# 20200358  backup_state — is this machine's data actually being copied?
def backup_state(ms=None, refresh=False):
    """The two halves of "running", derived once for every caller.

    A backup is running when a schedule is ACTIVE and a dated set attributed to
    this machine is RECENT. Either half alone is a different situation, and
    each gets its own answer rather than being rounded to yes or no:

        scheduled + fresh    running — the row is true
        scheduled, stale     a schedule producing no copy is not a backup
        fresh, unscheduled   a copy exists and nothing will make the next one
        neither              nothing is being backed up

    `running` is the verdict a caller may tick a box with. `state` names which
    of the four this is, and `notes` carries every fact that LOOKS like
    evidence and is not — an installed binary, another project's cron line, a
    dated directory belonging to another machine — so no caller has to
    re-derive why a plausible-looking signal was refused.

    Cached like landscape(): three shell-outs and a directory walk, read by an
    install-steps panel that gets polled.
    """
    now = time.time()
    with _lock:
        if (not refresh and _backup_cache['value'] is not None
                and (now - _backup_cache['at']) < CACHE_TTL):
            return _backup_cache['value']

    ms = ms if ms is not None else mounts()
    bt = backup_target(ms)
    roots = backup_sets(bt, ms)
    seen = _walk_roots(bt, ms)
    timer, scope = _hub_backup_timer()
    cron_mine, cron_foreign = _cron_backup_lines()
    tools = backup_tools_present()

    scheduled = timer == 'active' or bool(cron_mine)
    newest = roots[0] if roots else None
    age = newest['age'] if newest else None
    fresh = age is not None and age <= BACKUP_STALE_DAYS

    schedule = ('%s is active (%s scope)' % (HUB_BACKUP_UNIT, scope)
                if timer == 'active' else '%s is %s' % (HUB_BACKUP_UNIT, timer))
    if cron_mine:
        schedule += "; cron runs this hub's backup (%s)" % cron_mine[0]
    sets = (describe_sets(roots) + (', %d day(s) old' % age if age is not None else '')
            if roots else 'no dated set attributed to this machine anywhere')

    notes = []
    if tools and not scheduled:
        notes.append('%s on PATH but nothing invokes it — presence is not a '
                     'schedule' % ', '.join('`%s`' % t for t in tools))
    if cron_foreign:
        notes.append('%d crontab line(s) mention backup and belong to another '
                     'project, read the path not the word: %s'
                     % (len(cron_foreign), '; '.join(cron_foreign)))
    # Walked over every candidate root rather than over `roots`, which holds
    # only the ones with a set of this machine's. A root containing NOTHING but
    # another box's sets has no entry in `roots`, so looping there reported it
    # as empty -- the report would say "no dated set attributed to this machine
    # anywhere" while /backups sat full of dated directories. That is the same
    # silence this whole check exists to remove, pointing the other way.
    for r in seen:
        if r['foreign']:
            notes.append('sets in %s belong to another machine: %s'
                         % (r['path'], ', '.join(r['foreign'])))
        if r['unclaimed']:
            notes.append('dated dirs in %s carry no MANIFEST.txt, so nothing '
                         'claims them: %s' % (r['path'], ', '.join(r['unclaimed'])))

    state = ('running'     if scheduled and fresh else
             'stale'       if scheduled else
             'unscheduled' if fresh else
             'none')

    out = {
        'running':      scheduled and fresh,
        'state':        state,
        'scheduled':    scheduled,
        'fresh':        fresh,
        'timer':        timer,
        'timer_scope':  scope,
        'schedule':     schedule,
        'cron_mine':    cron_mine,
        'cron_foreign': cron_foreign,
        'roots':        roots,
        'newest':       newest['newest'] if newest else None,
        'age_days':     age,
        'stale_after':  BACKUP_STALE_DAYS,
        'sets':         sets,
        'tools':        tools,
        'notes':        notes,
        'derived_at':   int(now),
    }
    with _lock:
        _backup_cache.update({'at': now, 'value': out})
    return out


# ── Per-project data ─────────────────────────────────────────────────────────
# data_root() answers "where does data go on this machine". It does not answer
# "where does MY data go", and until now nothing did: /api/admit handed a
# project one string and left the shape of what goes inside it to whoever was
# typing that day.
#
# The operator stated the requirement plainly: an application saves documents,
# PDFs, images, audio and video, some internal and some public, and "it's not
# that there IS isolation for a project's storage, but there SHOULD be, because
# you don't want your container cluttered with the data sets it needs to
# regionalize and allocate and distribute cleanly, so when things break or have
# failures those file sets are saved in a different area or a different
# partition." And: commingling on one host is fine — "on its onset it's already
# isolated and segregated even if it's commingled."
#
# So the target is ADDRESSABLE, ISOLATED, SURVIVES THE CONTAINER. Sharing a
# disk is allowed. Being indistinguishable on it is not.
#
# The buckets are named because the backup class has to be derivable from the
# path alone. backup.sh already skips volumes matching *cache*; a bucket called
# cache/ inherits that for free, and a project that puts its regenerable
# thumbnails there is not asking anyone to remember that they are regenerable.
# A flat list of names with one declared purpose each is the whole scheme: no
# per-project config file, nothing to maintain, nothing to drift.
PROJECT_BUCKETS = (
    ('db', 'structured state a database writes',
     'never served', 'nightly'),
    ('media', 'files the app stores for its users — documents, PDFs, images, '
              'audio, video',
     'through the app, session required', 'nightly'),
    ('public', 'the ONLY path a serving layer may expose without a session',
     'open', 'nightly'),
    ('private', 'files the app stores for itself — exports, reports, inbound '
                'drops, anything that must survive but is nobody’s upload',
     'never served', 'nightly'),
    ('cache', 'regenerable. The NAME is load-bearing: backup.sh skips *cache*',
     'never served', 'never'),
    ('releases', 'build artifacts, keep N',
     'never served', 'never'),
)


# 20200350  reserved_elsewhere — large devices held by a name, not by a job
def reserved_elsewhere(ms=None):
    """Mounts data_root() threw away for being NAMED for backups, with the one
    fact that decides whether the name is still true: does a backup of this
    machine actually land there.

    fks-services is the case. /backup is 4.4TB on /dev/sdb1, 0% used, holding
    nothing but lost+found. data_root() correctly refuses to put live data on a
    mount the operator named for backups — intent beats size, see BACKUP_HINTS.
    The result is that the box with the biggest spare disk is the box whose
    projects are told to use the OS disk, and 4.2TB is reserved for a job that
    has no unit, no timer and no set on it.

    Reported, never acted on. A mount point is the operator's declaration and
    the code does not get to overrule it — but a declaration nothing honours is
    a fact they are entitled to have said out loud.
    """
    ms = ms if ms is not None else mounts()
    held = [m for m in ms
            if m['target'] not in ('/', '/boot', '/boot/efi')
            and m['size_gb'] >= MIN_DATA_GB
            and _named_for_backup(m['target'])]
    if not held:
        return []

    # Which of them any dated set of THIS machine lives on. backup_sets() is
    # the existing derivation; asking `df` here would be a second answer to a
    # question this module already answers once.
    devs = set()
    try:
        for r in backup_sets(ms=ms):
            if r.get('dev'):
                devs.add(r['dev'])
    except Exception:
        pass

    out = []
    for m in held:
        out.append({
            'target':     m['target'],
            'source':     m['source'],
            'size_gb':    m['size_gb'],
            'avail_gb':   m['avail_gb'],
            'used_pct':   m['used_pct'],
            'holds_sets': m['source'] in devs,
            'writable':   os.access(m['target'], os.W_OK),
        })
    return out


# 20200397  project_root — the parent every project's data directory hangs from
# Numbered 97 and not 59: a parallel session was landing reclaim_state on
# ...359 in this same file on the same day. Two functions on one address is the single
# thing the scheme exists to prevent. The band is otherwise full — ...340 is
# the only other free code, and it is the one `atlas.py --codes` offers next,
# so taking it would simply re-run the collision with the next agent.
# The codes are written broken here on purpose: a full 8-digit number at the
# head of a comment line IS a declaration to the allocator, so citing one in
# prose declares it a second time. That is how this very comment created the
# duplicate it was written to explain.
def project_root(ms=None):
    """Where per-project directories live on THIS node, and whether that is a
    disk of its own.

    Two shapes, and the difference is not cosmetic:

      dedicated   <root>/<project>/<bucket>
                  a filesystem of its own. A project filling media/ fills that
                  disk and nothing else.

      fallback    /srv/docker/<project>/data/<bucket>
                  no qualifying mount. Data sits under the project directory so
                  the existing rule — do not write outside /srv/docker/<project>
                  — stays true, and so one `rm -rf` of the project directory
                  takes the project and nothing of anyone else's.

    `cost` is filled in only on the fallback, and it says what the absence
    actually costs rather than calling it a default. A project told
    `dedicated: false` with no further comment will read it as a formality.
    """
    ms = ms if ms is not None else mounts()
    dr = data_root(ms)
    m = dr.get('mount') or {}

    if dr['dedicated']:
        return {
            'path':      dr['path'].rstrip('/'),
            'suffix':    '',
            'dedicated': True,
            'device':    m.get('source', ''),
            'size_gb':   m.get('size_gb', 0),
            'avail_gb':  m.get('avail_gb', 0),
            'why':       ('%s is a filesystem of its own on %s, so a project '
                          'filling its buckets cannot fill the OS disk'
                          % (dr['path'], m.get('source') or '?')),
            'cost':      '',
            'reserved':  reserved_elsewhere(ms),
        }

    held = reserved_elsewhere(ms)
    why = ('no mount on this node is both large enough and free of a backup '
           'claim, so project data shares %s with the OS, Docker’s images and '
           'the journal' % (m.get('source') or '/'))
    cost = ('a project that fills its buckets fills /, and a full / stops every '
            'container on this box — not just that project. %sGB free today.'
            % m.get('avail_gb', '?'))
    if held:
        h = held[0]
        cost += (' %s is %sGB and %s%% used, and is excluded because its name '
                 'declares it a backup target%s.'
                 % (h['target'], h['size_gb'], h['used_pct'],
                    '' if h['holds_sets']
                    else ' — but no backup of this machine lands there'))
    return {
        'path':      '/srv/docker',
        'suffix':    '/data',
        'dedicated': False,
        'device':    m.get('source', ''),
        'size_gb':   m.get('size_gb', 0),
        'avail_gb':  m.get('avail_gb', 0),
        'why':       why,
        'cost':      cost,
        'reserved':  held,
    }


# 20200360  project_data — one project's whole data contract, derived
def project_data(project=None, ms=None, pr=None):
    """Everything a project needs to be told about where its data lives, in the
    shape it receives it. Absolute paths, because a project that has to compose
    its own path from a root and a convention will compose it differently on
    the other box.

    `project` may be None, in which case the literal token `<project>` is used
    and the answer is a template rather than an allocation. /api/admit is asked
    without a name often enough that returning nothing there would be worse
    than returning a shape.

    Nothing here creates a directory. The `create` line is text for a human,
    the same way findings() carries a fix it will not run.
    """
    ms = ms if ms is not None else mounts()
    pr = pr if pr is not None else project_root(ms)
    name = (project or '').strip().lower() or '<project>'

    base = '%s/%s%s' % (pr['path'], name, pr['suffix'])
    buckets = {}
    for b, holds, exposure, backup in PROJECT_BUCKETS:
        buckets[b] = {
            'path':     '%s/%s' % (base, b),
            'holds':    holds,
            'exposure': exposure,
            'backup':   backup,
        }
    names = [b[0] for b in PROJECT_BUCKETS]

    return {
        'project':   name,
        'root':      base,
        'dedicated': pr['dedicated'],
        'device':    pr['device'],
        'avail_gb':  pr['avail_gb'],
        'why':       pr['why'],
        'cost':      pr['cost'],
        'buckets':   buckets,
        'order':     names,

        # Bind mounts, not named volumes, and the reason is the requirement
        # itself: a bind mount is a path on the host that a container happens
        # to see, so removing the container removes nothing. A named volume
        # lives under /var/lib/docker/volumes on the OS disk, is invisible to
        # `du` on the data root, needs root or the docker group to read, and
        # `docker compose down -v` deletes it without asking twice.
        'mounts':    'bind',
        'create':    'mkdir -p %s/{%s}' % (base, ','.join(names)),
        'compose':   ['- %s:/data/%s' % (buckets[b]['path'], b) for b in names],
        'label':     base,

        'survives': ('every bucket is a host directory that exists before the '
                     'container starts. `docker compose down`, `docker rm -f` '
                     'and `docker system prune -a` do not touch it. The data '
                     'is readable, tarrable and rsyncable from the host with '
                     'no container running and no docker group.'),
        'acceptance': ('stop and remove every container you own, then `ls %s/db` '
                       '— if it is empty or gone, your data was inside the '
                       'container and you do not have isolation, you have a '
                       'copy that happens to still be running.' % base),
    }


# 20200354  findings — what an operator should be told, with the fix
def findings(ms=None, dk=None):
    """Each finding carries the command that would fix it. This module never
    runs them: a storage tool that acts on its own conclusions is one bad
    heuristic away from deleting something that mattered."""
    ms = ms if ms is not None else mounts()
    dk = dk if dk is not None else docker_storage()
    out = []

    root = next((m for m in ms if m['target'] == '/'), None)
    cache = dk.get('build_cache', {})

    if cache.get('reclaimable_gb', 0) >= CACHE_BLOAT_GB and not cache.get('active'):
        out.append({
            'id': 'build_cache_bloat',
            'severity': 'warn',
            'detail': ('%sGB of Docker build cache is reclaimable and none of '
                       'it is in use' % cache['reclaimable_gb']),
            'fix': 'docker builder prune -af',
        })

    if root and root['used_pct'] >= DISK_PRESSURE_PCT:
        out.append({
            'id': 'os_disk_pressure',
            'severity': 'high',
            'detail': '/ is %s%% full (%sGB free)' % (root['used_pct'], root['avail_gb']),
            'fix': 'docker builder prune -af; journalctl --vacuum-size=200M',
        })

    dr = data_root(ms)
    if dr['dedicated'] and root:
        m = dr['mount']
        big = m['size_gb'] >= root['size_gb'] * DATA_MULTIPLE
        if m['used_pct'] <= UNUSED_DISK_PCT and big:
            out.append({
                'id': 'data_disk_unused',
                'severity': 'warn',
                'detail': ('%s has %sGB free and is %s%% used, while / carries '
                           'the load' % (m['target'], m['avail_gb'], m['used_pct'])),
                'fix': 'put project data under %s/PROJECT' % m['target'],
            })
        # Docker on the small disk while a big one sits idle is the setup that
        # produced the incident: the cache had nowhere else to grow.
        if big and dk.get('root', '').startswith('/var/lib'):
            out.append({
                'id': 'docker_root_on_os_disk',
                'severity': 'info',
                'detail': ('Docker stores images on / while %s (%sGB) is '
                           'available' % (m['target'], m['size_gb'])),
                'fix': ('set data-root to %s/docker in /etc/docker/daemon.json '
                        '(requires a docker restart)' % m['target']),
            })

    # The asymmetry, named. On a node with NO dedicated data disk, a large
    # mount excluded purely because its name says "backup" is only a correct
    # exclusion while a backup actually lands there. fks-services: /backup is
    # 4.4TB, 0% used, holds nothing but lost+found, has no hub-backup unit in
    # either scope, and is not writable by the user the hub runs as — while the
    # sets that do exist sit in /srv/backups on the SAME device as the data.
    #
    # The fix is a mount point, not a code change, and it is deliberately
    # phrased that way: data_root() reads the operator's declaration and must
    # not overrule it. Rename the declaration and every derivation follows on
    # the next poll, with nothing in this repo edited.
    if not dr['dedicated']:
        for h in reserved_elsewhere(ms):
            if h['holds_sets']:
                continue
            out.append({
                'id': 'spare_disk_idle_behind_a_name',
                'severity': 'warn',
                'detail': ('%s is %sGB and %s%% used, excluded from project data '
                           'because its name declares it a backup target — but '
                           'no backup of this machine lands there%s. Projects '
                           'are being told to use the OS disk instead.'
                           % (h['target'], h['size_gb'], h['used_pct'],
                              ', and it is not writable by this user'
                              if not h['writable'] else '')),
                'fix': ('decide what %s is. To make it the data root: remount it '
                        'at /srv/data (edit /etc/fstab, `umount %s && mkdir -p '
                        '/srv/data && mount /srv/data`) — data_root() then '
                        'derives it and backup_target() falls to %s, which is a '
                        'different device, which is the whole point. To keep it '
                        'as the backup target: install the hub-backup timer and '
                        'make it writable, because an empty reservation is not '
                        'a backup.'
                        % (h['target'], h['target'],
                           (root or {}).get('source') or '/')),
            })
    return out


# 20200355  landscape — the whole picture, one call
def landscape(refresh=False):
    """Cached for CACHE_TTL. Pass refresh=True after changing anything on
    disk, so a prune or a mount shows up immediately instead of up to two
    minutes later."""
    now = time.time()
    with _lock:
        if not refresh and _cache['value'] is not None                 and (now - _cache['at']) < CACHE_TTL:
            return _cache['value']

    ms = mounts()
    dk = docker_storage()
    out = {
        'mounts':     ms,
        'docker':     dk,
        'data_root':  data_root(ms),
        # Additive. data_root stays exactly as it was — five callers read it,
        # one of them another agent's file — and project_root sits beside it
        # carrying the shape per project rather than replacing the path.
        'project_root': project_root(ms),
        'backup':     backup_target(ms),
        'findings':   findings(ms, dk),
        'derived_at': int(now),
    }
    with _lock:
        _cache.update({'at': now, 'value': out})
    return out
