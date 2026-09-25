#!/usr/bin/env python3
"""
# 20404706  tools.storage-preflight — check the disks before trusting the node

Run by the installer, and safe to run any time afterwards.

The case for it: ksgcohub ran for two weeks with 40GB of dead Docker build
cache on a 98GB OS disk while a 458GB disk sat 99% empty. Nothing alarmed,
because nothing was looking. The disk was at 66% and climbing, and the fix
turned out to be one command.

Hardware varies — one disk, two, a big empty mount, none — so this asks the
machine rather than assuming a layout. Every finding prints the command that
would fix it. This script never runs them: an installer that silently
repartitions a server is worse than a full disk.

    python3 tools/storage-preflight.py            report, exit 0
    python3 tools/storage-preflight.py --strict   exit 1 on any warn/high

--strict is for the installer, so a node does not get enrolled onto a disk
that is already in trouble.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from kernel import storage as st   # noqa: E402

SEV = {'high': '!!', 'warn': ' !', 'info': '  '}


def main():
    strict = '--strict' in sys.argv
    land = st.landscape()
    ms = land['mounts']

    if not ms:
        print('could not read any filesystem — is findmnt available?')
        return 1

    print('Filesystems')
    for m in ms:
        bar = '#' * (m['used_pct'] // 5) + '.' * (20 - m['used_pct'] // 5)
        print('  %-14s %8.1fG  [%s] %3d%%  %.1fG free'
              % (m['target'], m['size_gb'], bar, m['used_pct'], m['avail_gb']))

    dr = land['data_root']
    print('\nProject data belongs at')
    print('  %s%s' % (dr['path'],
                      '' if dr['dedicated'] else
                      '   (no dedicated data disk — falling back to the OS disk)'))

    if dr.get('note'):
        print('  %s' % dr['note'])

    bt = land.get('backup') or {}
    print('\nBackups belong at')
    if bt.get('dedicated'):
        print('  %s   on %s%s'
              % (bt['path'], bt['mount']['source'],
                 '   (declared by its mount name)' if bt.get('declared') else ''))
    else:
        print('  %s' % (bt.get('note') or 'no valid target'))

    dk = land['docker']
    c = dk['build_cache']
    print('\nDocker')
    print('  images at    %s' % (dk['root'] or 'unknown'))
    print('  build cache  %sGB  (%sGB reclaimable, %s active)'
          % (c['size_gb'], c['reclaimable_gb'], c['active']))

    f = land['findings']
    print('\nFindings')
    if not f:
        print('  none — storage is set up sensibly for this hardware')
    for item in f:
        print('  %s %s' % (SEV.get(item['severity'], '  '), item['detail']))
        print('       fix: %s' % item['fix'])

    if strict and any(i['severity'] in ('high', 'warn') for i in f):
        print('\n--strict: storage needs attention before enrolling this node')
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
