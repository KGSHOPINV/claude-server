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

The point is not that it passes. The point is that "are we done" becomes a
command instead of a memory.
"""
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from kernel import storage as st        # noqa: E402

try:
    from kernel import identity as ident
except Exception:                       # identity is optional on a bare box
    ident = None

OK, MISSING, WARN = 'ok', 'missing', 'warn'
MARK = {OK: '[x]', MISSING: '[ ]', WARN: '[~]'}


def sh(cmd):
    try:
        r = subprocess.run(cmd, shell=True, capture_output=True,
                           text=True, timeout=10)
        return r.returncode, r.stdout.strip()
    except Exception:
        return 1, ''


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
    """A backup target on the same physical device as the data is not a backup.
    findmnt reports the source device, so this is checkable rather than assumed.
    """
    ms = st.mounts()
    dr = st.data_root(ms)
    data_dev = (dr.get('mount') or {}).get('source', '')
    others = [m for m in ms
              if m['source'] != data_dev and m['target'] not in ('/boot', '/boot/efi')]
    if not others:
        return MISSING, ('no second device — a backup target must not share a '
                         'disk with the data it protects')
    best = max(others, key=lambda m: m['avail_gb'])
    return OK, ('%s has %sGB free on a different device (%s)'
                % (best['target'], best['avail_gb'], best['source']))


def check_backups_running():
    for cmd in ('server-backup', 'restic', 'borg', 'rsnapshot'):
        rc, _ = sh('command -v %s' % cmd)
        if rc == 0:
            return OK, 'backup tool present: %s' % cmd
    rc, out = sh('systemctl --user list-timers --all --no-pager 2>/dev/null | '
                 'grep -ci backup')
    if out.isdigit() and int(out) > 0:
        return OK, 'a backup timer is registered'
    rc, out = sh('crontab -l 2>/dev/null | grep -ci backup')
    if out.isdigit() and int(out) > 0:
        return OK, 'a backup cron entry exists'
    return MISSING, 'no backup tool, timer or cron entry — nothing is being backed up'


def check_reclamation():
    rc, out = sh('systemctl list-timers --all --no-pager 2>/dev/null | '
                 'grep -ciE "prune|docker-clean"')
    if out.isdigit() and int(out) > 0:
        return OK, 'a reclamation timer is registered'
    rc, out = sh('crontab -l 2>/dev/null | grep -ciE "prune|docker system"')
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


def check_enrolled():
    if os.path.exists(os.path.expanduser('~/.flare/node.json')):
        return OK, 'enrolled — ~/.flare/node.json present'
    return MISSING, 'not enrolled — no public hostname (run enroll.sh)'


CHECKS = [
    ('hub service',      check_hub_service),
    ('identity',         check_identity),
    ('data root',        check_data_root),
    ('backup target',    check_backup_target),
    ('backups running',  check_backups_running),
    ('cache reclamation', check_reclamation),
    ('storage sound',    check_storage_sound),
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
