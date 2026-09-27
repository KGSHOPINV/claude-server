#!/usr/bin/env python3
"""
# 20404717  tools.atlas — the whole thing: planes, engines, topology, phase-out.

    python3 hub/tools/atlas.py              # everything
    python3 hub/tools/atlas.py --planes     # just the planes + installer parallel
    python3 hub/tools/atlas.py --topology   # just the two servers
    python3 hub/tools/atlas.py --local      # no ssh, no curl (source only)

THE PROBLEM THIS EXISTS FOR. There is a roadmap, and it lived in 48 markdown
files that went stale the day after they were written, including the ones that
described the roadmap. Asking "what plane are we on, what is a module, what is
an engine, what is installed, and what only exists BECAUSE IT WAS TYPED ON TWO
BOXES BY HAND" got answered from memory. Memory was wrong twice in one hour:

  - Reported: ksgcohub has NO backups. Truth: it runs one nightly, four days
    retained, 107M, hub database included. The report had looked at
    /srv/backups (an empty directory from September 7) instead of /backups,
    where the unit actually writes.
  - Reported: fks-services is the healthy one. Truth: it has no backup unit at
    all, and no ~/.flare/node.json, while its hostname answers at the edge.

Both mistakes were the same mistake: describing a machine instead of asking it.

THE RULE THIS ENFORCES — THE INSTALLER PARALLEL.

    A plane is NOT DONE until the installer produces it.

Something that works on both servers because a human configured both servers is
not built, it is APPLIED. The third server is what proves which one it was, and
by then whoever typed it has forgotten. So every plane below is scored twice:

    BUILT      the code exists in this repo
    INSTALLED  bootstrap.sh / enroll.sh put it on a fresh box, unattended

BUILT and not INSTALLED prints HAND-BUILT. That is not a minor gap. It is the
difference between a product and two pets.

WHAT THIS IS NOT. It does not fix anything, it does not write anything, and it
holds no opinion it cannot check. Where it cannot see, it says so under WHAT I
COULD NOT SEE — because the dangerous output is not a FAIL, it is a clean
report with a hole in it.
"""
import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
HUB = os.path.join(ROOT, 'hub')
LOCAL = '--local' in sys.argv
BLIND = []


def src(rel):
    try:
        with open(os.path.join(ROOT, rel), encoding='utf-8', errors='ignore') as f:
            return f.read()
    except Exception:
        return ''


def sh(cmd, timeout=25):
    """Run and return (ok, stdout). Never raises — a probe that dies is a blind
    spot to be reported, not a crash."""
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return p.returncode == 0, (p.stdout or '').strip()
    except Exception as e:
        return False, str(e)[:80]


def pyfiles(sub):
    d = os.path.join(HUB, sub)
    if not os.path.isdir(d):
        return []
    return sorted(os.path.join(sub, f) for f in os.listdir(d) if f.endswith('.py'))


# ── ENGINE vs MODULE vs INSTRUMENT ───────────────────────────────────────────
# Not a label anyone typed. Derived from what the code DOES:
#
#   ENGINE      runs without being asked — owns a thread, a loop, or a timer.
#               When one is wrong it is wrong continuously and in the
#               background, which is how changewatch published twenty bulletins
#               in a day before anyone noticed.
#   module      answers when asked and is otherwise inert. A bug is visible at
#               the call site.
#   INSTRUMENT  reports and never repairs. Everything under tools/.
#
# The distinction is operational: engines need a kill switch, modules need a
# caller, instruments need neither.
ENGINE_MARKS = (r'\bthreading\b', r'while True', r'def loop\(', r'Timer\(')


def classify(rel):
    body = src(os.path.join('hub', rel))
    if rel.startswith('tools/'):
        return 'INSTRUMENT'
    for m in ENGINE_MARKS:
        if re.search(m, body):
            return 'ENGINE'
    return 'module'


def code_of(rel):
    m = re.search(r'^#\s+(\d{8})\s+(\S+)', src(os.path.join('hub', rel)), re.M)
    return (m.group(1), m.group(2)) if m else ('--------', rel)


# ── THE PLANES ───────────────────────────────────────────────────────────────
# Each plane names the markers that prove the INSTALLER produces it. They are
# deliberately things a file merely existing in the repo cannot fake: a systemd
# unit, an env assignment, an API call.
PLANES = [
    {
        'id': 'P0', 'name': 'IDENTITY & EDGE',
        'what': 'who this box is, and how the outside reaches it',
        'built': ['hub/kernel/identity.py', 'hub/kernel/svctoken.py', 'enroll.sh'],
        'install_marks': ['enroll.sh', 'machine-id', 'cfargotunnel', 'access/apps'],
        'retires': [],
    },
    {
        'id': 'P1', 'name': 'KERNEL (engines)',
        'what': 'db, log, auth, router, collect, fleet, heartbeat, storage, control',
        'built': ['hub/kernel/db.py', 'hub/kernel/router.py', 'hub/kernel/collect.py'],
        'install_marks': ['hub.service', 'db_ensure_tables', 'requirements.txt'],
        'retires': [],
    },
    {
        'id': 'P2', 'name': 'DOORS (handlers)',
        'what': 'every /api route — the only way in or out of the kernel',
        'built': ['hub/handlers/node.py', 'hub/handlers/status.py'],
        'install_marks': ['HUB_PORT', 'hub.service'],
        'retires': ['8 overlapping "what is this server" shapes -> 1'],
    },
    {
        'id': 'P3', 'name': 'SURFACE (UI)',
        'what': 'app.html today, ui-next tomorrow, one lobby outside both',
        'built': ['hub/app.html', 'hub/lobby.html'],
        'install_marks': ['app.html', 'ui/sw.js'],
        'retires': ['mobile.html (implements 0 of 28 views)', 'app.html -> ui-next'],
    },
    {
        'id': 'P4', 'name': 'EXCHANGE (server <-> project)',
        'what': 'outbox, bulletins, tickets, registry — what ends the human '
                'being the transport',
        'built': ['hub/kernel/outbox.py', 'hub/handlers/exchange.py',
                  'hub/kernel/changewatch.py'],
        'install_marks': ['outbox', 'bulletin'],
        'retires': ['the operator pasting values between sessions'],
    },
    {
        'id': 'P5', 'name': 'ENTRY CHAIN (the lobby)',
        'what': 'flarevault.dev -> login -> FlareSHub -> pick a server -> in',
        'built': ['hub/handlers/lobby.py', 'hub/handlers/lobbyhost.py',
                  'hub/handlers/door.py'],
        'install_marks': ['HUB_SPLASH_HOSTS', 'HUB_CANONICAL_HOST', 'HUB_DOOR_HOST'],
        'retires': ["the hub's own second login"],
    },
    {
        'id': 'P6', 'name': 'INSTRUMENTS',
        'what': 'tools/ — report, never repair. These replace the documents.',
        'built': ['hub/tools/step.py', 'hub/tools/situation.py', 'hub/tools/tracks.py'],
        'install_marks': [],          # nothing to install; they run from the checkout
        # CAPABILITIES.md is gone and TASKS.md is drained to the record of why
        # it failed, so naming them as things this plane WILL retire is itself
        # a stale fact in the tool that hunts stale facts. What is left is the
        # standing rule, which cannot go out of date.
        'retires': ['any document that states a fact a command can answer'],
    },
]

INSTALLERS = ('bootstrap.sh', 'enroll.sh')


# A marker that NAMES A FILE has to be a file that exists, not a string the
# installer happens to contain. P1 scored DONE on 'requirements.txt' purely
# because bootstrap.sh mentions it -- and hub/requirements.txt does not exist
# anywhere in the repo, so that pip3 line is dead code and the plane's DONE was
# a lie of exactly the kind this tool is supposed to catch. Mentioning a thing
# is not installing it.
FILE_MARK = ('.txt', '.sh', '.py', '.service', '.timer', '.json', '.html', '.js')


def _marker_hit(mark, blob):
    if mark not in blob:
        return False, 'not mentioned by the installer'
    if mark.endswith(FILE_MARK) and '/' not in mark:
        for base in ('', 'hub'):
            if os.path.exists(os.path.join(ROOT, base, mark)):
                return True, 'mentioned, and the file exists'
        return False, 'MENTIONED BUT THE FILE DOES NOT EXIST — dead installer line'
    return True, 'mentioned'


def plane_state(p):
    built = all(os.path.exists(os.path.join(ROOT, b)) for b in p['built'])
    if not p['install_marks']:
        return built, None                      # n/a — runs from the checkout
    blob = ''.join(src(i) for i in INSTALLERS)
    hits, dead = [], []
    for m in p['install_marks']:
        ok, why = _marker_hit(m, blob)
        (hits if ok else dead).append(m if ok else '%s (%s)' % (m, why))
    return built, (len(hits), len(p['install_marks']), hits, dead)


def show_planes():
    print()
    print('  PLANES — and whether the INSTALLER produces them')
    print('  ' + '-' * 74)
    hand = []
    for p in PLANES:
        built, inst = plane_state(p)
        if inst is None:
            mark = 'built' if built else 'PARTIAL'
            note = 'n/a — runs from the checkout'
        else:
            got, need, hits, dead = inst
            if not built:
                mark, note = 'PARTIAL', 'code incomplete'
            elif got == need:
                mark = 'DONE'
                note = 'installer produces it (%d/%d markers)' % (got, need)
            elif got == 0:
                mark = 'HAND-BUILT'
                note = ('installer produces NONE of it — it exists because it '
                        'was typed')
                hand.append(p)
            else:
                mark = 'HAND-BUILT'
                note = 'installer produces %d of %d markers: %s' % (
                    got, need, ', '.join(hits))
                hand.append(p)
        print('  [%-10s] %s  %s' % (mark, p['id'], p['name']))
        print('               %s' % p['what'])
        print('               %s' % note)
        for dm in (inst[3] if inst else []):
            print('               marker: %s' % dm)
        for r in p['retires']:
            print('               phases out: %s' % r)
    print()
    if hand:
        print('  %d plane(s) are HAND-BUILT: %s'
              % (len(hand), ', '.join(p['id'] for p in hand)))
        print('  A third server arrives without them. That is the gap, not a detail.')
    else:
        print('  Every plane the installer is responsible for, it produces.')
    return hand


# ── PARTS ────────────────────────────────────────────────────────────────────
def show_parts():
    rels = pyfiles('kernel') + pyfiles('handlers') + pyfiles('tools')
    rows = []
    for rel in rels:
        if rel.endswith('__init__.py'):
            continue
        code, name = code_of(rel)
        rows.append((classify(rel), code, name, rel))
    order = {'ENGINE': 0, 'module': 1, 'INSTRUMENT': 2}
    rows.sort(key=lambda r: (order[r[0]], r[1]))
    heads = {
        'ENGINE': 'ENGINES — run unasked. Wrong here means wrong continuously.',
        'module': 'MODULES — answer when called. Inert otherwise.',
        'INSTRUMENT': 'INSTRUMENTS — report, never repair.',
    }
    print()
    print('  PARTS — classified by what the code does, not by where it sits')
    print('  ' + '-' * 74)
    last = None
    for kind, code, name, rel in rows:
        if kind != last:
            n = sum(1 for r in rows if r[0] == kind)
            print()
            print('  %s  (%d)' % (heads[kind], n))
            last = kind
        print('    %s  %-26s %s' % (code, name, rel))
    return rows


# ── CONFIG SURFACE ───────────────────────────────────────────────────────────
# Every env key the code reads, against what the installer sets. A key the code
# honours and nothing ever sets is not configuration — it is a code default
# wearing a costume, and it reads as adjustable to the next person.
def show_config():
    keys = set()
    for base, _dirs, files in os.walk(HUB):
        for f in files:
            if not f.endswith('.py'):
                continue
            try:
                with open(os.path.join(base, f), encoding='utf-8',
                          errors='ignore') as fh:
                    keys |= set(re.findall(r"environ\.get\('([A-Z_]+)'", fh.read()))
            except Exception:
                pass
    blob = ''.join(src(i) for i in INSTALLERS)
    setk = sorted(k for k in keys if re.search(r'\b%s=' % k, blob))
    unset = sorted(keys - set(setk))
    print()
    print('  CONFIG SURFACE — %d keys read, %d set by the installer'
          % (len(keys), len(setk)))
    print('  ' + '-' * 74)
    print('    installer sets : %s' % (', '.join(setk) or 'none'))
    print()
    print('    never set anywhere (%d) — code defaults, not settings:' % len(unset))
    for i in range(0, len(unset), 3):
        print('      ' + '  '.join('%-24s' % k for k in unset[i:i + 3]).rstrip())
    return setk, unset


# ── TELESCOPE CODES ──────────────────────────────────────────────────────────
# Every function is supposed to carry a unique 8-digit address. The rule was
# "grep for the next free number", and that is not an allocator -- it is a
# guess with a race in it. Four agents working in parallel on 2026-09-26 each
# grepped before the others had written, and three of them chose 20404718. I
# then moved one to 20404803, which situation.py had already taken, because I
# assumed a band was free instead of computing it.
#
# So: this section computes. It reports every duplicate and the next genuinely
# free code in a band, which is the thing that should have existed before any
# code was ever hand-picked.
# THE COMMENT FORMS THIS MUST MATCH, AND WHY THE LIST IS NOT OPTIONAL.
#
# This pattern used to be `(?:#|//)`, which misses `/* ... */`. Every JS file in
# hub/ui/ opens with one, so six codes were INVISIBLE to the allocator --
# including 20404701 (ui/registry.js) and 20404801 (ui/views/issues.js), which
# are exactly the two numbers it then offered as "next free" in those bands.
#
# An allocator that is blind to part of the address space does not merely
# under-report: it actively hands out numbers that are already taken, which is
# the precise collision it exists to prevent. An agent following its advice
# would have collided twice; the one that caught this checked by grep and
# reported the tool instead, which is the only reason it did not happen.
#
# So a new comment style anywhere in this repo must be added here on the same
# day, or this section starts lying again.
CODE_RE = re.compile(r'^\s*(?:#|//|/\*|\*)\s+(\d{8})\s', re.M)
CODE_EXT = ('.py', '.sh', '.html', '.js', '.css')


def _codes():
    used = {}
    for base, dirs, files in os.walk(ROOT):
        # Skip .git AND the background tasks' worktrees. Each worktree is a
        # full checkout, so walking them reported every code in the repo as
        # duplicated four times over -- 403 "collisions" that were one file
        # seen from four sessions. Pruning `dirs` in place stops os.walk from
        # descending rather than merely filtering what it yields.
        dirs[:] = [d for d in dirs if d not in ('.git', 'worktrees', 'node_modules',
                                                '__pycache__', '.venv')]
        if '.git' in base or 'worktrees' in base.replace('\\', '/').split('/'):
            continue
        for f in files:
            if not f.endswith(CODE_EXT):
                continue
            p = os.path.join(base, f)
            try:
                with open(p, encoding='utf-8', errors='ignore') as fh:
                    body = fh.read()
            except Exception:
                continue
            for m in CODE_RE.finditer(body):
                used.setdefault(m.group(1), []).append(
                    os.path.relpath(p, ROOT).replace('\\', '/'))
    return used


def show_codes():
    used = _codes()
    dupes = {k: v for k, v in used.items() if len(v) > 1}
    print()
    print('  TELESCOPE CODES — %d distinct, %d duplicated' % (len(used), len(dupes)))
    print('  ' + '-' * 74)
    if not dupes:
        print('    Every code is unique. The address space holds.')
    for code, where in sorted(dupes.items()):
        print('    %s  %s' % (code, ' · '.join(where)))
    if dupes:
        print()
        print('    A duplicated code means "go to this function" has two answers,')
        print('    which is the one thing the scheme exists to prevent.')
    # Next free in each band that is already in use, so a new function can be
    # numbered by reading rather than by guessing.
    bands = sorted({c[:6] for c in used})
    print()
    print('    next free per band in use:')
    for b in bands:
        nxt = next((b + '%02d' % i for i in range(1, 100)
                    if b + '%02d' % i not in used), None)
        print('      %s..  %s' % (b, nxt or 'band full'))
    return dupes


# ── TOPOLOGY ─────────────────────────────────────────────────────────────────
# The node list comes from CLAUDE.md, the only place both servers are written
# down. That is itself a finding: the fleet's membership is a document.
NODES = [
    {'node': 'ksgcohub', 'user': 'ksgco', 'ts': '100.107.234.9',
     'lan': '192.168.50.100', 'host': 'flareshub-fvn-685a59.flarevault.dev',
     'role': 'personal / home — holds control.db and the lobby'},
    {'node': 'fks-services', 'user': 'admin1', 'ts': '100.75.1.105',
     'lan': '192.168.1.229', 'host': 'flareshub-fvn-3b8c1b.flarevault.dev',
     'role': 'work — 216GB, the bigger box'},
]

PROBE = (
    'echo "BUILD:$(git -C ~/hub rev-parse --short HEAD 2>/dev/null)"; '
    'echo "HUB:$(systemctl --user is-active hub 2>/dev/null)"; '
    'echo "NODEJSON:$(test -s ~/.flare/node.json && echo yes || echo MISSING)"; '
    'echo "SVCTOKEN:$(test -s ~/.flare/svctoken.json && echo yes || echo MISSING)"; '
    'echo "UNITS:$(systemctl --user list-units --type=service,timer --no-legend '
    '2>/dev/null | awk "{print \\$1}" | grep ^hub | tr "\\n" " ")"; '
    'echo "BACKUPDIR:$(ls -1d /backups 2>/dev/null || echo NONE)"; '
    'echo "BACKUPS:$(ls -1 /backups 2>/dev/null | grep -c ^20)"; '
    # THE COMPARISON THAT MATTERS, AND THE ONE I GOT WRONG THREE TIMES.
    #
    # A backup is safe when it does not share a device with THE DATA IT
    # BACKS UP. It is not "same device as /" that matters. On ksgcohub the
    # data lives on sdb (/srv/data, 465G) and the backup writes to /backups
    # on sda -- different physical disks, which is exactly what hub-backup.sh
    # chose on purpose and says so at its line 26. Comparing /backups to /
    # instead made a correct setup look like the worst finding on the page,
    # three separate times, in both directions.
    'echo "BACKUPDEV:$(df --output=source /backups 2>/dev/null | tail -1)"; '
    'echo "DATADEV:$(df --output=source /srv/data 2>/dev/null | tail -1)"; '
    'echo "DATAROOT:$(ls -1d /srv/data 2>/dev/null || echo NONE)"; '
    'echo "ROOTDEV:$(df --output=source / 2>/dev/null | tail -1)"; '
    'echo "UP:$(uptime -p 2>/dev/null)"'
)


def probe(n):
    """Reach a node by tailnet, then LAN. Which route worked is itself a
    finding — the two servers are on different tailnets."""
    if LOCAL:
        BLIND.append('%s — not probed (--local)' % n['node'])
        return None
    for label, addr in (('tailnet', n['ts']), ('LAN', n['lan'])):
        ok, out = sh(['ssh', '-o', 'ConnectTimeout=6', '-o', 'BatchMode=yes',
                      '%s@%s' % (n['user'], addr), PROBE], timeout=45)
        if ok and 'BUILD:' in out:
            d = dict(line.split(':', 1) for line in out.splitlines() if ':' in line)
            d['_route'] = '%s (%s)' % (label, addr)
            return d
    BLIND.append('%s — no ssh by tailnet (%s) or LAN (%s)'
                 % (n['node'], n['ts'], n['lan']))
    return None


def edge(host):
    if LOCAL:
        return '--'
    ok, out = sh(['curl', '-s', '-o', os.devnull, '-w', '%{http_code}',
                  '-m', '14', 'https://' + host], timeout=25)
    return out if ok and out else 'unreachable'


def show_topology():
    print()
    print('  TOPOLOGY — asked, not remembered.   node list source: CLAUDE.md')
    print('  ' + '-' * 74)
    seen = []
    for n in NODES:
        d = probe(n)
        code = edge(n['host'])
        print()
        print('  %s   %s' % (n['node'], n['role']))
        print('    edge      https://%s  ->  HTTP %s' % (n['host'], code))
        if not d:
            print('    COULD NOT REACH IT — everything below is unknown, not fine.')
            continue
        print('    route     %s' % d.get('_route'))
        print('    build     %s        hub %s,  %s'
              % (d.get('BUILD', '?'), d.get('HUB', '?'), d.get('UP', '?')))
        nj, st = d.get('NODEJSON'), d.get('SVCTOKEN')
        if nj == 'MISSING' and st == 'yes':
            print('    identity  node.json MISSING while svctoken.json exists and the')
            print('              hostname answers — ENROLLED AT THE EDGE, UNRECORDED')
            print('              LOCALLY. tools/step.py step 4 reads node.json, so it')
            print('              under-reports this node.')
        elif nj == 'MISSING':
            print('    identity  node.json MISSING — this node does not know who it is')
        else:
            print('    identity  node.json ok, svctoken %s' % st)
        print('    units     %s' % ((d.get('UNITS') or '').strip() or 'none'))
        bd, bn = d.get('BACKUPDIR', 'NONE'), (d.get('BACKUPS') or '0')
        if bd == 'NONE' or not bd:
            print('    backups   NONE. No unit, no directory. Nothing is copied anywhere.')
        else:
            print('    backups   %s sets in %s' % (bn, bd))
            bdev, ddev = d.get('BACKUPDEV'), d.get('DATADEV')
            if d.get('DATAROOT') in (None, '', 'NONE'):
                print('              no /srv/data on this box, so there is no separate')
                print('              data device to be clear of — cannot judge this.')
                BLIND.append('%s — backup device vs data device: no /srv/data'
                             % n['node'])
            elif bdev and ddev and bdev == ddev:
                print('              SHARES A DEVICE WITH THE DATA IT BACKS UP (%s).'
                      % bdev)
                print('              One disk failure takes the data and the copy.')
            elif bdev and ddev:
                print('              clear of the data device: data on %s, copy on %s'
                      % (ddev, bdev))
            else:
                BLIND.append('%s — could not read backup/data devices' % n['node'])
        seen.append((n['node'], d))
    return seen


def show_divergence(seen):
    if len(seen) < 2:
        BLIND.append('divergence — needs both nodes probed')
        return
    print()
    print('  DIVERGENCE — one repo, two different machines')
    print('  ' + '-' * 74)
    (an, a), (bn, b) = seen[0], seen[1]
    for field, label in (('BUILD', 'build'), ('UNITS', 'systemd units'),
                         ('NODEJSON', 'node.json'), ('BACKUPDIR', 'backup dir')):
        av = (a.get(field, '') or '').strip()
        bv = (b.get(field, '') or '').strip()
        same = 'same' if av == bv else 'DIFFERENT'
        print('    %-14s %-10s %s: %s' % (label, same, an, av or 'none'))
        if av != bv:
            print('    %-14s %-10s %s: %s' % ('', '', bn, bv or 'none'))
    ua = set((a.get('UNITS') or '').split())
    ub = set((b.get('UNITS') or '').split())
    if ua and ub and ua != ub:
        print()
        print('    The unit sets do not overlap the way one installer would produce.')
        print('    only %s: %s' % (an, ' '.join(sorted(ua - ub)) or '-'))
        print('    only %s: %s' % (bn, ' '.join(sorted(ub - ua)) or '-'))
        print('    bootstrap.sh creates hub.service, hub-backup.timer and')
        print('    hub-reclaim.timer. A box without those was not produced by the')
        print('    installer — it predates it, which means the installer has never')
        print('    been proved against this fleet.')


# ── WHERE WE ARE ─────────────────────────────────────────────────────────────
def show_step():
    print()
    print('  WHERE THE BUILD IS — delegated to tools/step.py, not restated')
    print('  ' + '-' * 74)
    if LOCAL:
        print('    skipped (--local): step.py asks a running hub.')
        BLIND.append('build order — step.py needs a running hub')
        return
    _ok, out = sh([sys.executable, os.path.join(HUB, 'tools', 'step.py')],
                  timeout=150)
    for line in (out or '(no output)').splitlines():
        print(('  ' + line) if line.strip() else '')


# ── PHASE-OUT ────────────────────────────────────────────────────────────────
# Not a wish list. Each item names the ONE condition that makes it next, and
# the condition is checkable. Anything whose condition is not met is not the
# work, however appealing it looks.
PHASES = [
    ('NOW', 'One intake end to end',
     'step 5. Nothing technical blocks it — a project has to be told to walk it.',
     'unblocks: the exchange stops being theory'),
    ('NOW', 'Put the exchange behind glass',
     'outbox/bulletins/tickets have ZERO screen. Until then the operator is '
     'still the transport, which is the one thing P4 was built to end.',
     'unblocks: nothing — it IS the point of P4'),
    ('NEXT', 'Fold the hand-built planes into the installer',
     'Whatever prints HAND-BUILT above. A third server is the only real test.',
     'unblocks: any new node, and the no-central-server premise'),
    ('NEXT', 'fks: record its identity, and give it a backup',
     'node.json missing; no backup unit at all.',
     'unblocks: honest step.py output, and surviving a disk'),
    ('NEXT', 'ksgcohub: move /backups off the data device',
     'Same filesystem as / and /srv today.',
     'unblocks: the unit description becoming true'),
    ('THEN', 'Collapse 8 server-description shapes into 1',
     'status/receipt/context/node/manifest/sync/identity/access all answer '
     '"what is this server".',
     'unblocks: a UI that does not have to choose between them'),
    ('THEN', 'Mockups, then ui-next',
     'Gated on step 5 by tools/tracks.py. Mockups before any build.',
     'retires: app.html and mobile.html'),
    ('LATER', 'Peer backup between nodes',
     'Needs both nodes to have a working local backup first. One does.',
     'unblocks: no-central-server, for real'),
]

DECISIONS = [
    ('D1', 'Access: one app over one prefix',
     'three apps / three sessions has caused four differently-shaped bugs'),
    ('D2', 'HUB_ENFORCE_GATES + TOTP',
     'the LAN answers /api/config and /api/vault with no credential, and '
     'turning gates on closes nothing above 1 until TOTP exists'),
    ('D3', 'VAPID or ntfy for notifications',
     'the service worker is real and has nowhere to be told from'),
    ('D4', 'which project walks step 5 first',
     'the only thing step 5 is actually waiting on'),
]


def show_phases():
    print()
    print('  PHASE-OUT — each with the one condition that makes it next')
    print('  ' + '-' * 74)
    last = None
    for when, title, why, effect in PHASES:
        if when != last:
            print()
            last = when
        print('  %-6s %s' % (when, title))
        print('         %s' % why)
        print('         %s' % effect)
    print()
    print('  OPERATOR DECISIONS — not tasks. Nothing proceeds on these by itself.')
    for c, title, why in DECISIONS:
        print('    %s  %-34s %s' % (c, title, why))


def main():
    only = [a for a in sys.argv[1:] if a.startswith('--') and a != '--local']

    def want(k):
        return (not only) or ('--' + k) in only

    print()
    print('  ATLAS — ServerHub, derived from the repo and the machines')
    print('  repo: %s' % ROOT)
    if LOCAL:
        print('  --local: source only. No machine was asked anything.')
    if want('planes'):
        show_planes()
    if want('parts'):
        show_parts()
    if want('config'):
        show_config()
    if want('topology'):
        show_divergence(show_topology())
    else:
        # A section skipped by a flag is a section nobody looked at. Saying
        # "every probe answered" when no probe ran is the exact failure this
        # tool was written to stop.
        BLIND.append('topology — not run (section filter %s)' % ' '.join(only))
    if want('step'):
        show_step()
    else:
        BLIND.append('build order — not run (section filter %s)' % ' '.join(only))
    if want('codes'):
        show_codes()
    if want('phases'):
        show_phases()
    print()
    print('  WHAT I COULD NOT SEE')
    print('  ' + '-' * 74)
    if BLIND:
        for b in BLIND:
            print('    %s' % b)
        print()
        print('    Everything above is true only of what answered. A hole here is')
        print('    not a pass.')
    else:
        print('    Nothing. Every probe answered.')
    print()
    return 0


if __name__ == '__main__':
    sys.exit(main())
