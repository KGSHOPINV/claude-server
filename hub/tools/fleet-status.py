#!/usr/bin/env python3
"""
# 20404710  tools.fleet-status — two servers, one matrix

The question this answers: while things are being corrected across two servers,
what is true on each one right now, and are they congruent?

Congruence is NOT sameness. The boxes must differ -- ksgcohub derives
/srv/data, fks-services derives /srv/docker plus /backup. Identical values
would mean the derivation is broken. So:

    congruent = same code ref + both pass the same assertions
              ≠ same values

Drift is the `ref` column disagreeing. The `data root` column disagreeing is
the system working.

`projects` and `stale` come from each node's own registry: how many projects
filed a claim there, and how many have not acknowledged the ref that node is
running. Stale is not failure -- it means the project has not been told, so
nothing may assume it knows.

Reads over SSH, derives everything, stores nothing. Run it whenever:

    python3 tools/fleet-status.py
    python3 tools/fleet-status.py --json
"""
import json
import subprocess
import sys

# Hosts come from the fleet file when one exists, else this fallback. Declared
# here rather than discovered because a node cannot enumerate its own fleet --
# that is central's job, and central is not built yet.
HOSTS = [
    ('ksgcohub',     'ksgco@100.107.234.9'),
    ('fks-services', 'admin1@192.168.1.229'),
]

TIMEOUT = 20


def ssh(target, cmd):
    try:
        r = subprocess.run(['ssh', '-n', '-o', 'ConnectTimeout=8', target, cmd],
                           capture_output=True, text=True, timeout=TIMEOUT)
        return r.stdout.strip()
    except Exception:
        return ''


# 20404711  probe — everything about one node, in ONE ssh round trip
def probe(name, target):
    """One connection per host. Several would be slower and could report a
    machine mid-change as though the readings were simultaneous.

    Two things in the payload below are load-bearing and easy to undo:

    `ref` assigns to a variable before echoing. The previous form was
    `echo "ref=$(git rev-parse ...)"`, and `echo` succeeds whether or not git
    printed anything -- so in a checkout that is not a repo (a tarball deploy,
    a copied directory) the `||` branch never ran and the column came back
    BLANK. Blank under a ref column reads as "same as the others", i.e. as no
    drift, when what happened is that nothing was measured.

    `registry` sends the HTTP status back alongside the body. GET /api/registry
    is new and fks-services is on an older ref that does not serve it. A 404
    body still parses as JSON, and a missing "projects" key would have printed
    0 -- a node with an unknown registry claiming nothing was stale.
    """
    script = r'''
cd ~/hub 2>/dev/null && REF=$(git rev-parse --short HEAD 2>/dev/null)
echo "ref=${REF:-?}"
echo "hub=$(systemctl --user is-active hub 2>/dev/null)"
echo "http=$(curl -s -o /dev/null -w '%{http_code}' -m 5 http://127.0.0.1:8765/ 2>/dev/null)"
echo "backup_timer=$(systemctl --user list-timers --all --no-pager 2>/dev/null | grep -c hub-backup)"
echo "reclaim_timer=$(systemctl --user list-timers --all --no-pager 2>/dev/null | grep -c hub-reclaim)"
echo "disk=$(df -h / | awk 'NR==2{print $5}')"
echo "band=$(curl -s -m 5 'http://127.0.0.1:8765/api/admit?project=_probe' 2>/dev/null | python3 -c 'import json,sys; print(json.load(sys.stdin).get("assigned_band"))' 2>/dev/null)"
echo "dataroot=$(curl -s -m 5 'http://127.0.0.1:8765/api/admit?project=_probe' 2>/dev/null | python3 -c 'import json,sys; d=json.load(sys.stdin); s=d.get("storage") or {}; print(s.get("data_root") or "-")' 2>/dev/null)"
if [ -f hub/tools/install-preflight.py ]; then
  echo "preflight=$(python3 hub/tools/install-preflight.py 2>/dev/null | grep -oE '[0-9]+ of [0-9]+' | head -1)"
else
  echo "preflight=not-deployed"
fi
echo "registry=$(curl -s -m 5 -w ' %{http_code}' http://127.0.0.1:8765/api/registry 2>/dev/null | python3 -c '
import json, sys
raw = sys.stdin.read()
body, _, code = raw.rpartition(" ")
d = json.loads(body) if code.strip() == "200" else None
ps = (d or {}).get("projects") or []
print("%d %d" % (len(ps), sum(1 for p in ps if p.get("stale"))) if d is not None else "n/a")
' 2>/dev/null)"
'''
    out = ssh(target, script)
    d = {'node': name, 'target': target, 'reachable': bool(out)}
    for line in out.splitlines():
        if '=' in line:
            k, v = line.split('=', 1)
            d[k] = v.strip()
    # Split here rather than at print time, so --json carries exactly the two
    # numbers the table shows instead of a string a reader has to re-parse.
    d['projects'], d['stale'] = _registry_cells(d.pop('registry', ''))
    return d


# 20404712  _registry_cells — two numbers, or "n/a" and no pretending
def _registry_cells(raw):
    """"n/a" and "0" are different answers and only one of them is information.
    A node whose hub predates /api/registry, whose hub is down, or whose curl
    timed out has an UNKNOWN registry; printing 0 there would manufacture the
    most reassuring reading available from the least evidence."""
    parts = (raw or '').split()
    if len(parts) == 2 and all(x.isdigit() for x in parts):
        return parts[0], parts[1]
    return 'n/a', 'n/a'


def main():
    nodes = [probe(n, t) for n, t in HOSTS]

    if '--json' in sys.argv:
        print(json.dumps(nodes, indent=2))
        return 0

    # projects/stale sit beside preflight because all three answer the same
    # question -- is this node's account of itself current -- while disk, band
    # and dataroot are derived per machine and are SUPPOSED to disagree.
    cols = [('node', 13), ('ref', 9), ('hub', 8), ('http', 5),
            ('preflight', 10), ('projects', 9), ('stale', 6),
            ('disk', 6), ('band', 16), ('dataroot', 14)]
    print('  ' + ''.join(h.ljust(w) for h, w in cols))
    print('  ' + ''.join('-' * (w - 1) + ' ' for _, w in cols))
    for n in nodes:
        if not n.get('reachable'):
            print('  ' + n['node'].ljust(13) + 'UNREACHABLE')
            continue
        timers = []
        if n.get('backup_timer', '0') != '0':
            timers.append('bk')
        if n.get('reclaim_timer', '0') != '0':
            timers.append('rc')
        row = {
            'node': n['node'], 'ref': n.get('ref', '?'),
            'hub': n.get('hub', '?'), 'http': n.get('http', '-'),
            'preflight': n.get('preflight', '?'),
            'projects': n.get('projects', 'n/a'),
            'stale': n.get('stale', 'n/a'),
            'disk': n.get('disk', '?'),
            'band': n.get('band', '-'), 'dataroot': n.get('dataroot', '-'),
        }
        print('  ' + ''.join(str(row[h])[:w - 1].ljust(w) for h, w in cols)
              + ('timers:' + ','.join(timers) if timers else 'NO TIMERS'))

    # ── Congruence ───────────────────────────────────────────────────────────
    live = [n for n in nodes if n.get('reachable')]
    refs = {n.get('ref') for n in live if n.get('ref')}
    print()
    if len(live) < len(nodes):
        print('  congruence: UNKNOWN — not every node answered')
    elif len(refs) == 1:
        print('  congruence: OK — every node on %s' % refs.pop())
    else:
        print('  congruence: DRIFT — refs differ: %s' % ', '.join(sorted(refs)))
        print('              same code is the requirement. Different data roots')
        print('              and bands are CORRECT: they are derived per machine.')

    missing = [n['node'] for n in live
               if n.get('backup_timer', '0') == '0']
    if missing:
        print('  UNPROTECTED: no backup timer on %s' % ', '.join(missing))

    # Two separate statements, never one total. A fleet-wide "3 stale" summed
    # across a node that answered and a node that could not is a number with no
    # meaning, and it reads as though the silent node had been checked.
    behind = ['%s (%s)' % (n['node'], n['stale']) for n in live
              if n.get('stale', 'n/a').isdigit() and n['stale'] != '0']
    if behind:
        print("  STALE: projects not told their node's master on %s"
              % ', '.join(behind))
    silent = [n['node'] for n in live if not n.get('stale', 'n/a').isdigit()]
    if silent:
        print('  registry: no answer from %s — its projects are UNKNOWN, not'
              % ', '.join(silent))
        print('            current. Deploy a ref carrying GET /api/registry.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
