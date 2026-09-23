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
import json
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


def _run(cmd, timeout=10):
    try:
        r = subprocess.run(cmd, shell=True, capture_output=True,
                           text=True, timeout=timeout)
        return r.stdout.strip() if r.returncode == 0 else ''
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
    if others:
        best = max(others, key=lambda m: m['size_gb'])
        return {'path': best['target'], 'mount': best, 'dedicated': True}
    return {'path': '/srv/docker', 'mount': root, 'dedicated': False}


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
        'findings':   findings(ms, dk),
        'derived_at': int(now),
    }
    with _lock:
        _cache.update({'at': now, 'value': out})
    return out
