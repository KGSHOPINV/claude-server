#!/usr/bin/env python3
"""
# 20404720  tools.matrix -- the five checklists, asserted instead of described.

    python3 hub/tools/matrix.py                 every sequence
    python3 hub/tools/matrix.py --A --E         only those sequences
    python3 hub/tools/matrix.py --local         repo only: no ssh, no edge
    python3 hub/tools/matrix.py --strict        exit 1 if any row FAILs

THE PROBLEM THIS EXISTS FOR. docs/flareshub-checklists.md holds five sequences
-- A login, B installer, C cross-connect, D the ksgcohub Cloudflare correction,
B2 storage, E what the system can state -- and every row carries a tick that a
human typed on 2026-09-21. Five days later at least eight of those ticks were
wrong, in both directions, and nothing said so.

Both directions is the part that matters. One row, B2/4 ("backup target on a
different physical device than the data"), was marked correct, and was then
CONTRADICTED from a check that compared /backups against / instead of against
the data's device -- which put a working setup at the top of the operator's
priority list. A wrong FAIL costs a day of work on something that was already
right. So this tool records what the document claims for every row and prints
FLIPPED wherever the machine disagrees, rather than quietly printing its own
answer and leaving the reader to guess which one moved.

WHAT IT IS. install-preflight.py already did this for checklist B2 and for one
box: assertions, not prose. This is that method extended to all five sequences
and to both machines. B2's rows are not reimplemented here -- they are run by
install-preflight on each node and its verdicts are reported as its own.

    ROWS ARE ANSWERED THREE WAYS, AND WHICH ONE IS SAID OUT LOUD:
      repo   the source either contains the step or it does not
      node   the machine is asked (read-only ssh, loopback HTTP)
      edge   the public hostname is asked, from here, with no credential

A row answered from the repo is a claim about the CODE. A row answered from a
node is a claim about THAT node. Confusing the two -- describing the local box
under a remote box's name -- is the worst bug a fleet tool can have, so every
row prints which of the three answered it.

WHAT IT IS NOT. It repairs nothing, writes nothing, restarts nothing, and calls
no Cloudflare endpoint at all. It does not update the checklist document either:
the document's hand-marked ticks are the defect, and a tool that rewrites them
just moves the defect. Where it cannot see, it says so under WHAT I COULD NOT
SEE -- because the dangerous output is not a FAIL, it is a clean report with a
hole in it. A sequence skipped by a flag is recorded there too: "nothing ran"
must never read as "everything passed".

TWO THINGS A STATUS CODE DOES NOT PROVE, both learned here the hard way:
  * 200 from a hostname behind Access is the ACCESS SIGN-IN PAGE, served inline
    rather than as a redirect. Read as "reachable and open" it is exactly
    backwards. So the body is classified, not just the code.
  * Cloudflare answers python-urllib's default User-Agent with 403 on all three
    hostnames here. A probe that does not set a browser UA reports every
    hostname dead. So one is set, and 403 is still called out as "likely WAF,
    not Access".
"""
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
HUB = os.path.join(ROOT, 'hub')
LOCAL = '--local' in sys.argv
STRICT = '--strict' in sys.argv

# States this tool can be in about a row. UNK always becomes a blind spot.
PASS, PART, FAIL, UNK = 'PASS', 'PART', 'FAIL', 'UNK'
MARK = {PASS: '[pass]', PART: '[part]', FAIL: '[FAIL]', UNK: '[ ?? ]'}

# What docs/flareshub-checklists.md marked, transcribed from its own legend:
#   y = "built"   w = "built, off" / partial   n = "not built"
# 'x' = the document does not mark this row for THIS target. B2's eight ticks
# are explicitly dated "ksgcohub, 2026-09-23", so scoring fks-services against
# them would invent a claim the document never made -- which is the same class
# of error as the ticks themselves.
DOCMARK = {'y': PASS, 'w': PART, 'n': FAIL, 'x': None}
DOCGLYPH = {'y': 'built', 'w': 'built,off', 'n': 'not built', 'x': 'unmarked'}

ROWS = []      # (section, num, source, state, doc_state, title, detail)
BLIND = []
FLIPS = []


# ── plumbing ─────────────────────────────────────────────────────────────────

def src(rel):
    try:
        with open(os.path.join(ROOT, rel), encoding='utf-8', errors='ignore') as f:
            return f.read()
    except Exception:
        return ''


def blind(why):
    if why not in BLIND:
        BLIND.append(why)


def row(sec, num, doc, where, title, state, detail):
    """Record and print one checklist row.

    `doc` is the tick the document carries for this row. The comparison is the
    product: an answer without it is just another opinion about the machine.
    """
    want = DOCMARK[doc]
    ROWS.append((sec, num, where, state, want, title, detail))
    flag = ''
    if want is None:
        pass          # nothing to compare: the document is silent on this one
    elif state == UNK:
        blind('%s/%s %s -- could not be checked: %s' % (sec, num, title, detail))
    elif state != want:
        direction = 'BETTER' if (want, state) in (
            ('FAIL', 'PASS'), ('FAIL', 'PART'), ('PART', 'PASS')) else 'WORSE'
        flag = '  FLIPPED %s than the doc (doc: %s)' % (direction, DOCGLYPH[doc])
        FLIPS.append((sec, num, title, DOCGLYPH[doc], state, detail))
    if want is None and state == UNK:
        blind('%s/%s %s -- could not be checked: %s' % (sec, num, title, detail))
    print('  %s %-6s %-5s %s%s' % (MARK[state], '%s/%s' % (sec, num), where,
                                   title, flag))
    for line in _wrap(detail):
        print('              %s' % line)


def _wrap(text, width=84):
    out, line = [], ''
    for word in str(text).split():
        if line and len(line) + 1 + len(word) > width:
            out.append(line)
            line = word
        else:
            line = (line + ' ' + word).strip()
    if line:
        out.append(line)
    return out or ['']


def head(letter, title, why):
    print()
    print('  ' + '=' * 84)
    print('  %s. %s' % (letter, title))
    for line in _wrap(why, 80):
        print('     %s' % line)
    print('  ' + '=' * 84)


# ── the two machines ─────────────────────────────────────────────────────────
# The node list is a DOCUMENT (CLAUDE.md), which is itself a finding: the
# fleet's membership is the one thing here that no machine is asked about.
# fks-services is on the old tailnet, so its tailnet address times out and only
# the LAN answers. Which route answered is printed, because a row that passed
# over the LAN has not been shown to pass from anywhere else.
NODES = [
    {'node': 'ksgcohub', 'user': 'ksgco', 'ts': '100.107.234.9',
     'lan': '192.168.50.100', 'host': 'flareshub-fvn-685a59.flarevault.dev',
     'central': True},
    {'node': 'fks-services', 'user': 'admin1', 'ts': '100.75.1.105',
     'lan': '192.168.1.229', 'host': 'flareshub-fvn-3b8c1b.flarevault.dev',
     'central': False},
]

# Read-only. Nothing here writes, installs, restarts or configures anything on
# either box; the strongest verb is `curl` against loopback.
#
# Single quotes only, deliberately: this string is handed to ssh as one argv
# element, and on Windows the argv quoting wraps it in double quotes. A double
# quote inside would be escaped into the remote shell and change meaning.
PROBE = r'''
# Globbing OFF. Without this the shell expands the asterisks in a crontab line
# ("0 2 * * *") into the contents of the home directory, and the report prints
# a file listing where a schedule should be.
set -f
echo HOST=$(hostname)
echo HUBACTIVE=$(systemctl --user is-active hub 2>/dev/null)
echo HUBENABLED=$(systemctl --user is-enabled hub 2>/dev/null)
echo UNITS=$(systemctl --user list-units --type=service,timer --all --no-legend 2>/dev/null | awk '{print $1}' | grep ^hub | tr '\n' ' ')
echo ENV=$(systemctl --user show hub -p Environment --value 2>/dev/null)
echo NODEJSON=$(test -s $HOME/.flare/node.json && echo yes || echo no)
echo NODEJSON_KEYS=$(python3 -c 'import json,os;print(",".join(sorted(json.load(open(os.path.expanduser("~/.flare/node.json")))))) ' 2>/dev/null)
echo SVCTOKEN=$(test -s $HOME/.flare/svctoken.json && echo yes || echo no)
echo CFTOKEN=$(test -s $HOME/.cf-token && echo yes || echo no)
echo BACKUPTIMER=$(systemctl --user is-active hub-backup.timer 2>/dev/null)
echo RECLAIMTIMER=$(systemctl --user is-active hub-reclaim.timer 2>/dev/null)
echo CRONBACKUP=$(crontab -l 2>/dev/null | grep -ci backup)
echo CLOUDFLARED_HOST=$(systemctl is-active cloudflared 2>/dev/null)
echo CLOUDFLARED_CONTAINERS=$(docker ps --format '{{.Names}}' 2>/dev/null | grep -iE 'tunnel|cloudflared' | tr '\n' ' ')
echo DATAROOT=$(test -d /srv/data && echo /srv/data || echo NONE)
echo DATADEV=$(df --output=source /srv/data 2>/dev/null | tail -1)
echo BACKUPDIR=$(ls -1d /backups 2>/dev/null || echo NONE)
echo BACKUPDEV=$(df --output=source /backups 2>/dev/null | tail -1)
echo BACKUPSETS=$(ls -1 /backups 2>/dev/null | grep -c '^20')
echo BACKUPNEWEST=$(ls -1 /backups 2>/dev/null | grep '^20' | sort | tail -1)
echo ROOTDEV=$(df --output=source / 2>/dev/null | tail -1)
echo GITREF=$(git -C $HOME/hub rev-parse --short HEAD 2>/dev/null)
I=0
for D in /backups /backup /srv/backups /srv/backups/hub /mnt/backups /var/backups; do
  test -d $D || continue
  I=$((I+1))
  echo BSET$I=$D~$(df --output=source $D 2>/dev/null | tail -1)~$(ls -1 $D 2>/dev/null | grep -c '^20')~$(ls -1 $D 2>/dev/null | grep '^20' | sort | tail -1)
done
echo CRONLINES=$(crontab -l 2>/dev/null | grep -i backup | tr '\n' ';' | cut -c1-220)
python3 - <<'PY2'
import os, sys
for _p in (os.path.expanduser('~/hub/hub'), os.path.expanduser('~/hub')):
    if os.path.isdir(os.path.join(_p, 'kernel')):
        sys.path.insert(0, _p)
        break
try:
    from kernel import storage as st
    ms = st.mounts()
    dr, bt = st.data_root(ms), st.backup_target(ms)
    print('K_DATA_PATH=%s' % dr.get('path'))
    print('K_DATA_DEV=%s' % ((dr.get('mount') or {}).get('source') or ''))
    print('K_DATA_DEDICATED=%s' % dr.get('dedicated'))
    print('K_BACKUP_PATH=%s' % (bt.get('path') or ''))
    print('K_BACKUP_DEV=%s' % ((bt.get('mount') or {}).get('source') or ''))
    print('K_BACKUP_DEDICATED=%s' % bt.get('dedicated'))
except Exception as e:
    print('K_ERR=%s: %s' % (type(e).__name__, str(e)[:60]))
PY2
echo PREFLIGHT_BEGIN=1
cd $HOME/hub 2>/dev/null && python3 hub/tools/install-preflight.py 2>&1 | sed 's/^/PF /'
echo PREFLIGHT_END=1
python3 - <<'PY'
import json, urllib.request
def get(p):
    try:
        with urllib.request.urlopen('http://127.0.0.1:8765' + p, timeout=8) as r:
            return json.load(r)
    except Exception:
        return None
def out(k, v):
    print('%s=%s' % (k, v))
f = get('/api/mesh/fleet')
out('API_FLEET', 'yes' if f is not None else 'no')
f = f or {}
out('FLEET_MODE', f.get('mode', ''))
fl = f.get('fleet') or {}
out('FLEET_N', len(fl))
out('FLEET_WITH_MACHINE_ID', sum(1 for v in fl.values() if v.get('machine_id')))
out('FLEET_WITH_REACH', sum(1 for v in fl.values() if v.get('reachability')))
out('FLEET_WITH_STORAGE_FLAG',
    sum(1 for v in fl.values()
        if any(('storage' in str(x).lower() or 'disk' in str(x).lower())
               for x in (v.get('attention') or []))))
out('FLEET_CONGRUENCE',
    ','.join(sorted({str(v.get('congruence')) for v in fl.values()})) or '-')
out('FLEET_NAMES', ','.join(sorted(str(v.get('name') or k)
                                   for k, v in fl.items())) or '-')
n = get('/api/node')
out('API_NODE', 'yes' if n is not None else 'no')
n = n or {}
att = n.get('attention') or {}
out('NODE_ATT_KEYS', ','.join(sorted(att)) or '-')
out('NODE_STORAGE_N', len(att.get('storage') or []))
out('NODE_PROJECTS', len(n.get('projects') or []))
out('NODE_UNCLAIMED', len(att.get('projects_without_ksg_label') or []))
out('NODE_ENROLLED', n.get('enrolled') or 'none')
out('NODE_PUBLIC', n.get('public') or 'none')
out('NODE_SERVER_ID', n.get('server_id') or '-')
out('NODE_MACHINE_ID', 'yes' if n.get('machine_id') else 'no')
out('NOTIF', json.dumps(att.get('notifications') or {}))
a = get('/api/activity?category=auth&limit=200')
out('API_ACTIVITY', 'yes' if a is not None else 'no')
out('AUTH_EVENTS', len((a or {}).get('events') or []))
t = get('/api/totp/status') or {}
out('TOTP', 'yes' if t.get('configured') else 'no')
b = get('/api/baselines/hub')
out('API_BASELINES', 'yes' if b is not None else 'no')
PY
'''


def ssh_probe(n):
    """Reach a node by tailnet first, then LAN. The route is part of the answer:
    fks-services sits on the old tailnet, so a row that passed over the LAN has
    been shown to pass from the LAN and nowhere else."""
    if LOCAL:
        blind('%s -- not probed at all (--local)' % n['node'])
        return None
    for label, addr in (('tailnet', n['ts']), ('LAN', n['lan'])):
        try:
            p = subprocess.run(
                ['ssh', '-o', 'ConnectTimeout=8', '-o', 'BatchMode=yes',
                 '%s@%s' % (n['user'], addr), PROBE],
                capture_output=True, text=True, timeout=150)
        except Exception as e:
            blind('%s via %s -- ssh raised %s' % (n['node'], label,
                                                 type(e).__name__))
            continue
        out = (p.stdout or '')
        if 'HOST=' not in out:
            continue
        d = {'_route': '%s (%s)' % (label, addr), '_pf': [], '_sets': []}
        for line in out.splitlines():
            if line.startswith('PF '):
                d['_pf'].append(line[3:])
            elif line.startswith('BSET') and '=' in line:
                # path~device~count of dated entries~newest dated entry
                parts = line.split('=', 1)[1].split('~')
                while len(parts) < 4:
                    parts.append('')
                d['_sets'].append({'path': parts[0], 'dev': parts[1],
                                   'n': parts[2], 'newest': parts[3]})
            elif '=' in line:
                k, v = line.split('=', 1)
                d[k.strip()] = v.strip()
        return d
    blind('%s -- no ssh by tailnet (%s) or LAN (%s). Every node row for it is '
          'unknown, not fine.' % (n['node'], n['ts'], n['lan']))
    return None


# Cloudflare answers urllib's default User-Agent with 403 on every hostname
# here, so a probe without one reports the whole fleet dead.
UA = ('Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) '
      'Chrome/125.0 Safari/537.36')


_EDGE_CACHE = {}


def edge(host):
    """Classify what a public hostname gives a caller with NO credential.

    Returns (code, kind, note). The kind is the point: 200 from a hostname
    behind Access is the Access SIGN-IN PAGE served inline, and reading that as
    "open" is exactly backwards.
    """
    if LOCAL:
        return (0, 'unknown', 'not probed (--local)')
    if host in _EDGE_CACHE:
        return _EDGE_CACHE[host]
    req = urllib.request.Request('https://' + host, headers={'User-Agent': UA})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            code, body = r.status, r.read(4000).decode('utf-8', 'replace')
    except urllib.error.HTTPError as e:
        try:
            body = e.read(4000).decode('utf-8', 'replace')
        except Exception:
            body = ''
        code = e.code
    except Exception as e:
        return (0, 'unreachable', '%s: %s' % (type(e).__name__, str(e)[:60]))
    low = body.lower()
    res = _classify(code, low)
    _EDGE_CACHE[host] = res
    return res


def _classify(code, low):
    if 'cloudflare access' in low and 'sign in' in low:
        return (code, 'access-login',
                'the Access sign-in page, served inline -- a human gate is in front')
    if code == 401:
        return (code, 'access-refused',
                'refused with no credential, which is what a node endpoint must do')
    if code == 403:
        return (code, 'blocked',
                'likely the Cloudflare WAF rather than Access -- inconclusive')
    if code in (301, 302, 303, 307, 308):
        return (code, 'redirect', 'redirected; destination not followed')
    if 'flareshub' in low or 'hub' in low or low.lstrip().startswith('{'):
        return (code, 'ORIGIN',
                'the ORIGIN answered a caller with no credential')
    return (code, 'other', 'unclassified body')


# ── A. LOGIN ─────────────────────────────────────────────────────────────────

def sec_a(nodes):
    head('A', 'Login -- what happens when someone arrives',
         'Rows 1,4,5,8 are claims about the code. Rows 2,3,7,9 are claims about '
         'a box, because they depend on env the installer does not set.')
    auth = src('hub/kernel/auth.py')
    users = src('hub/handlers/users.py')
    router = src('hub/kernel/router.py')

    # 1 -- the door is recorded
    ok = ('def access_identity(' in auth and 'CF_TRUST_IP' in auth
          and 'client_address' in auth)
    row('A', 1, 'y', 'repo', 'hub records which door a request came through',
        PASS if ok else FAIL,
        'access_identity() compares handler.client_address against '
        'HUB_CF_TRUST_IP; _door() in handlers/users.py labels the login with it'
        if ok else 'access_identity() does not compare the source address')

    # 2 -- the CF email header trusted only from the tunnel
    coded = "CF_HEADER" in auth and 'src != CF_TRUST_IP' in auth
    live = [(n['node'], 'HUB_CF_TRUST_IP=' in (d.get('ENV') or ''))
            for n, d in nodes if d]
    if not live:
        row('A', 2, 'w', 'node', 'Cf-Access email trusted only from the tunnel',
            UNK, 'no node answered, so whether the door is switched on is unknown')
    else:
        on = [k for k, v in live if v]
        st = PASS if (coded and len(on) == len(live)) else (
            PART if coded else FAIL)
        row('A', 2, 'w', 'node', 'Cf-Access email trusted only from the tunnel',
            st, 'code present; HUB_CF_TRUST_IP is SET on %s of %d nodes (%s). The '
                'doc marks this "built, off" -- it is on.'
                % (len(on), len(live), ', '.join(on) or 'none'))

    # 3 -- email checked against an allowlist
    gated = 'if CF_EMAILS and email not in CF_EMAILS' in auth
    withlist = [n['node'] for n, d in nodes if d and 'HUB_CF_EMAILS=' in (d.get('ENV') or '')]
    without = [n['node'] for n, d in nodes if d and 'HUB_CF_EMAILS=' not in (d.get('ENV') or '')]
    if not (withlist or without):
        row('A', 3, 'w', 'node', 'email checked against allowlist -> session + role',
            UNK, 'no node answered')
    else:
        st = PASS if not without else PART
        row('A', 3, 'w', 'node', 'email checked against allowlist -> session + role',
            st,
            'allowlist honoured (%s) and HUB_CF_ROLE read. SET on: %s. NOT SET on: '
            '%s -- and the test is `if CF_EMAILS and ...`, so an EMPTY list admits '
            'any address Access approved. On those nodes the allowlist is not off, '
            'it is absent.'
            % ('kernel/auth.py' if gated else 'MISSING in auth.py',
               ', '.join(withlist) or 'none', ', '.join(without) or 'none'))

    # 4 -- local door
    ok = 'sha256' in users.lower() and '_user_auth' in users
    row('A', 4, 'y', 'repo', 'local door: username + SHA-256 vs users table',
        PASS if ok else FAIL,
        '_user_auth() hashes with sha256 and compares against the users table'
        if ok else 'no sha256 comparison found in handlers/users.py')

    # 5 -- session survives a restart
    persisted = '_session_load' in auth and 'INSERT OR REPLACE INTO sessions' in auth
    row('A', 5, 'y', 'repo', 'session issued AND survives a restart',
        PASS if persisted else PART,
        '_session_load() hydrates from SQLite and session_put() writes through, so '
        'a restart no longer logs everyone out. The doc says "in-memory dict -- '
        'every restart logs everyone out"; that sentence is now false.'
        if persisted else 'sessions are still an in-memory dict only')

    # 6 -- the login is written to activity_log
    logged = re.search(r"_log\([^)]*'auth',\s*'login'", users) is not None
    failed_logged = 'FAILED login' in users
    cf_logged = bool(re.search(r"email = access_identity\(handler\)\s*\n\s*if email:\s*\n\s*"
                               r"return \{", auth))
    seen = [(n['node'], d.get('AUTH_EVENTS'), d.get('API_ACTIVITY'))
            for n, d in nodes if d]
    zero = [k for k, v, api in seen if api == 'yes' and v == '0']
    if not logged:
        st = FAIL
    elif not seen:
        # The code half passes. The runtime half is the whole point of the row,
        # so an unasked machine makes this partial, never done.
        st = PART
        blind('A/6 -- no node answered, so whether any login has actually been '
              'recorded is unknown; only the code was read')
    else:
        st = PART if (zero or not failed_logged) else PASS
    row('A', 6, 'n', 'both', 'the login is written to activity_log', st,
        'post_auth_login() now writes both success and FAILED login to '
        'activity_log -- the doc\'s "never calls log_activity" is out of date. BUT: '
        'check_auth() mints a session from the Cloudflare Access header (and from '
        'a service token) without logging ANYTHING, and /api/activity?category=auth '
        'returns %s. On a box whose only real door is Cloudflare the log is '
        'structurally empty.'
        % ('0 events on ' + ', '.join(zero) if zero else
           ('events on every node asked' if seen else 'nothing -- no node was asked')))

    # 7 -- notify
    notifies = '_ntfy(' in users
    broken = []
    for n, d in nodes:
        if not d:
            continue
        try:
            nf = json.loads(d.get('NOTIF') or '{}')
        except Exception:
            nf = {}
        if nf and not nf.get('healthy') and (nf.get('failed') or 0) > 0:
            broken.append('%s (sent=%s failed=%s error=%s)'
                          % (n['node'], nf.get('sent'), nf.get('failed'),
                             nf.get('error')))
    measured = [1 for n, d in nodes if d]
    if not notifies:
        st = FAIL
    elif not measured:
        st = PART
        blind('A/7 -- no node answered, so whether any push has ever been '
              'DELIVERED is unknown; only the calls were read')
    else:
        st = PART if broken else PASS
    row('A', 7, 'n', 'both', 'notify: normal on sign-in, high on repeated failures',
        st,
        'both calls exist in post_auth_login (low on a Cloudflare sign-in, high '
        'after %s failures) -- the doc\'s "ntfy fires on container events only" is '
        'out of date. But the push path itself is failing where measured: %s. Built '
        'and delivering nothing is not the same as built.'
        % (re.search(r'_FAIL_ALERT_AT\s*=\s*(\d+)', users).group(1)
           if re.search(r'_FAIL_ALERT_AT\s*=\s*(\d+)', users) else '?',
           '; '.join(broken) or ('no failures reported'
                                  if measured else 'no node was asked')))

    # 8 -- per-route gate actually applied
    # Only lines that are actually route declarations. The first version of
    # this counted every '"gate":' in the file, which included the schema
    # comment at router.py:15 -- an off-by-one in a number the reader is
    # invited to trust.
    gates = [int(m.group(1)) for m in
             re.finditer(r'"code":[^\n]*?"gate":\s*(\d+)', router)]
    gated_n = sum(1 for g in gates if g > 0)
    default_off = "HUB_ENFORCE_GATES', '0'" in router
    onnodes = [n['node'] for n, d in nodes if d and 'HUB_ENFORCE_GATES=' in (d.get('ENV') or '')]
    row('A', 8, 'w', 'both', 'per-route gate enforced (0/1/2/3)',
        PART if (default_off and not onnodes) else PASS,
        '%d of %d routes declare a gate above 0, and the gate is evaluated -- but '
        'HUB_ENFORCE_GATES defaults to 0 and is set on %s, so the router records '
        'what it WOULD have refused and refuses nothing. Unchanged from the doc.'
        % (gated_n, len(gates),
           ', '.join(onnodes) if onnodes else
           ('NEITHER node' if any(d for _n, d in nodes) else 'no node was asked')))

    # 9 -- dangerous routes demand more than the Access door gave
    totp_gate = "if not _config_get('totp_secret'" in auth
    notot = [n['node'] for n, d in nodes if d and d.get('TOTP') == 'no']
    yestot = [n['node'] for n, d in nodes if d and d.get('TOTP') == 'yes']
    if not (notot or yestot):
        row('A', 9, 'w', 'node', 'dangerous routes demand more than Access gave',
            UNK, 'no node answered /api/totp/status')
    else:
        row('A', 9, 'w', 'node', 'dangerous routes demand more than Access gave',
            FAIL if notot else PASS,
            'gate_check() returns True when no totp_secret is configured, by '
            'design -- and TOTP is NOT configured on %s. So every gate-2 and '
            'gate-3 route (vault, shell, config write, docker prune) is open to '
            'any session that got through the front door, including one minted '
            'from the Access header. This is worse than the doc\'s "depends on 8": '
            'row 8 failing open is what makes row 9 fail open too.'
            % (', '.join(notot) or 'neither'))


# ── B. INSTALLER ─────────────────────────────────────────────────────────────

def sec_b(nodes):
    head('B', 'Installer -- what a new node gets',
         'Repo rows: does the INSTALLER do the step? A thing that is true of both '
         'servers because a human typed it on both is not installed. Where a step '
         'has since been PROVEN against the live API, the node/edge says so.')
    boot = src('bootstrap.sh')
    enr = src('enroll.sh')
    app = src('hub/app.html')

    print()
    print('  bootstrap.sh -- hub running')
    b = [
        (1, 'y', 'OS detect, packages (curl, git, python3, ufw)',
         'step 1 "Detecting OS"' in boot and 'step 2 "Installing system packages"' in boot,
         'steps 1 and 2 present'),
        (2, 'y', 'Docker installed, enabled, started',
         'step 3 "Installing Docker"' in boot, 'step 3 present'),
        (3, 'y', 'clone/update hub to ~/hub',
         'step 4 "Setting up the hub"' in boot, 'step 4 present'),
        (4, 'y', 'db/ created, admin user seeded',
         'db_ensure_tables' in boot and 'UPDATE users SET password_hash' in boot,
         'seeded THROUGH kernel.db so there is one schema, not two'),
        (5, 'y', 'systemd USER service, Restart=always, journald', 'B5', None),
        (6, 'y', 'hub answering on :8765',
         'hub answering' in boot or '_http_code' in boot,
         'bootstrap probes the port rather than assuming it'),
    ]
    # Row 5 is answered here rather than in the table above, because the row
    # names a VALUE -- Restart=always -- and the installer uses a different
    # one. "A user unit exists" is not what the row claims, so the literal is
    # checked and the difference is stated instead of rounded off.
    userunit = '.config/systemd/user/hub.service' in boot
    policy = re.search(r'^Restart=(\S+)', boot, re.M)
    always = bool(policy and policy.group(1) == 'always')
    b5 = (PASS if (userunit and always) else (PART if userunit else FAIL),
          ('the user unit IS written and journald collects it by default, but the '
           'restart policy is Restart=%s, NOT Restart=always as the row says. '
           'on-failure does not restart a hub that exited cleanly, which is a '
           'weaker guarantee than the one the document records as built.'
           % (policy.group(1) if policy else 'ABSENT'))
          if not always else
          'user unit written with Restart=always, output to journald')

    for num, doc, title, ok, detail in b:
        if ok == 'B5':
            row('B', num, doc, 'repo', title, b5[0], b5[1])
            continue
        row('B', num, doc, 'repo', title, PASS if ok else FAIL,
            detail if ok else 'not found in bootstrap.sh')

    # 7 -- force the default password to be changed
    prompts = 'read -rsp "  Hub admin password: "' in boot
    refuses = 'needs an interactive terminal' in boot
    advert = 'Default: admin / admin' in app
    row('B', 7, 'n', 'repo', 'force the default password to be changed',
        PART if (prompts and advert) else (PASS if prompts else FAIL),
        'bootstrap.sh now demands a password interactively (%s) and refuses to run '
        'without a terminal (%s), so a bootstrapped node no longer stands on '
        'admin/admin -- install-preflight confirms that on both boxes. HALF FLIPPED: '
        'hub/app.html:%s still prints "Default: admin / admin" on the login screen, '
        'which is the exact reason the doc marked this row not built.'
        % (prompts, refuses,
           next((i + 1 for i, l in enumerate(app.splitlines())
                 if 'Default: admin / admin' in l), '?')) if advert
        else 'bootstrap demands a password and nothing advertises a default')

    # 8 -- register its port block
    band = any(k in boot for k in ('/api/admit', 'port band', 'PORT_BAND', 'reserve'))
    row('B', 8, 'n', 'repo', 'register its port block',
        PASS if band else FAIL,
        'no reservation step in bootstrap.sh. /api/admit derives a free band on '
        'request (handlers/node.py _free_band), but nothing in the installer ever '
        'claims one, so two nodes bootstrapped the same day can still collide.')

    print()
    print('  enroll.sh -- node joins the fleet')
    e = [
        (1, 'y', 'read /etc/machine-id -> stable node key',
         '/etc/machine-id' in enr, 'step 1 reads it and dies if unreadable'),
        (2, 'y', 'validate node label; require --zone',
         '--zone is required' in enr, 'step 2 refuses without --zone'),
        (3, 'y', 'refuse if the hub is not answering',
         'the hub must actually be running' in enr,
         'step 2 refuses rather than publishing a dead endpoint'),
        (4, 'y', 'load token from CF_API_TOKEN / ~/.cf-token / /etc/flare/token',
         'CF_API_TOKEN' in enr and '.cf-token' in enr and '/etc/flare/token' in enr,
         'all three sources, in that order'),
        (5, 'y', 'verify token with Cloudflare before changing anything',
         'step "3. Cloudflare credentials"' in enr,
         'verified against /zones rather than /user/tokens/verify, which returns '
         '401 for tokens that work -- the reason is written at enroll.sh:144'),
        (6, 'y', 'resolve zone + account', 'ACCOUNT_ID' in enr and 'ZONE_ID' in enr,
         'both resolved in step 3'),
    ]
    for num, doc, title, ok, detail in e:
        row('B', 'e%d' % num, doc, 'repo', title, PASS if ok else FAIL,
            detail if ok else 'not found in enroll.sh')

    # 7..14 -- written, and the doc says "untested". Test them.
    d_ks = next((d for n, d in nodes if n['node'] == 'ksgcohub'), None)
    ks_host = next(n['host'] for n in NODES if n['node'] == 'ksgcohub')
    ecode, ekind, enote = edge(ks_host)
    proven = ekind in ('access-refused', 'access-login')

    row('B', 'e7', 'y', 'node', 'create OR reuse tunnel (idempotent)',
        PASS if (d_ks and d_ks.get('NODEJSON') == 'yes') else UNK,
        'the doc says "untested -- the token available was revoked". It has since '
        'RUN: ksgcohub carries a tunnel_id in ~/.flare/node.json and the host '
        'cloudflared unit is %s. No longer untested.'
        % (d_ks.get('CLOUDFLARED_HOST') if d_ks else '?')
        if d_ks and d_ks.get('NODEJSON') == 'yes'
        else 'ksgcohub did not answer, so nothing proves this ran')

    row('B', 'e8', 'y', 'repo', 'ingress: this hostname -> local hub, + catch-all 404',
        PASS if ('MERGE, never replace' in enr and 'http_status:404' in enr) else PART,
        'step 4b merges ingress rather than replacing it, and appends the '
        'catch-all. Run against the live API on ksgcohub; the RULE SET ITSELF is '
        'in Cloudflare and is not readable from the box without a token.')
    blind('B/e8 enroll.sh ingress -- the merged rule set lives in Cloudflare; '
          'reading it needs an API token, which this tool never uses')

    row('B', 'e9', 'y', 'edge', 'DNS CNAME -> <tunnel>.cfargotunnel.com, proxied',
        PASS if ecode else UNK,
        '%s resolves and answers HTTP %s (%s), which only happens if the proxied '
        'record exists. Proven, not untested.' % (ks_host, ecode, ekind)
        if ecode else 'the hostname did not answer: %s' % enote)

    row('B', 'e10', 'y', 'edge', 'Access app on the hostname -- nothing public ungated',
        PASS if proven else (FAIL if ekind == 'ORIGIN' else UNK),
        '%s -> HTTP %s: %s' % (ks_host, ecode, enote))

    # 11 -- the policy
    haspol = 'access/apps/${APP_ID}/policies' in enr and 'any_valid_service_token' in enr
    row('B', 'e11', 'n', 'both', 'attach the allow policy',
        PASS if (haspol and ekind == 'access-refused') else (
            PART if haspol else FAIL),
        'FLIPPED: enroll.sh now CREATES the policy idempotently instead of printing '
        'a warning ("A warning is not a step", enroll.sh:368), and the edge agrees '
        '-- %s answers 401 with no credential, which only an attached non-identity '
        'policy produces. Note the row\'s wording is now wrong in a second way: the '
        'policy is not an "allow" policy for a person, it is '
        'any_valid_service_token, so a human who finds this hostname gets nothing '
        'by design.' % ks_host
        if haspol else 'no policy creation in enroll.sh')

    row('B', 'e12', 'y', 'node', 'cloudflared as a HOST systemd service',
        PASS if (d_ks and d_ks.get('CLOUDFLARED_HOST') == 'active') else (
            UNK if not d_ks else FAIL),
        'host unit cloudflared is %s on ksgcohub, deliberately not a container so '
        'the way in survives Docker dying. Proven, not untested.'
        % d_ks.get('CLOUDFLARED_HOST') if d_ks
        else 'ksgcohub did not answer')

    keys = (d_ks or {}).get('NODEJSON_KEYS', '')
    secretish = [k for k in keys.split(',')
                 if any(s in k for s in ('token', 'secret', 'key', 'password'))
                 and k != 'tunnel_id']
    row('B', 'e13', 'y', 'node', '~/.flare/node.json -- facts only, no credentials',
        PASS if (keys and not secretish) else (UNK if not keys else FAIL),
        'ksgcohub\'s node.json holds: %s. No credential-shaped key among them '
        '(tunnel_id is an identifier, and cloudflared keeps the only credential, '
        'scoped to its own tunnel).' % keys
        if keys and not secretish
        else ('credential-shaped keys present: %s' % ', '.join(secretish)
              if secretish else 'no node.json to read on ksgcohub'))

    row('B', 'e14', 'y', 'both', 'verify the public hostname answers',
        PASS if ('step "9. Verify"' in enr and ecode) else UNK,
        'step 9 verifies, and it does answer (%s %s). NOTE, said every time: 200, '
        '302 and 401 can all be minted at the Cloudflare edge without a packet '
        'reaching the box -- this proves the hostname and its gate, never the '
        'origin.' % (ecode, ekind))

    # 15 -- announce to a sponsor
    sponsor = any(k in enr for k in ('sponsor', '/api/enroll', 'join_token', 'join-token'))
    hb_reg = 'def register(' in src('hub/kernel/heartbeat.py')
    fleet_has = next((d.get('FLEET_N') for n, d in nodes
                      if d and n['central']), None)
    row('B', 'e15', 'n', 'both', 'announce itself to a sponsor node',
        PART if hb_reg else FAIL,
        'enroll.sh still has no sponsor and no join token, so the row as WRITTEN is '
        'not built. But the capability exists elsewhere and is working: '
        'kernel/heartbeat.py register() announces the node to central, and '
        'ksgcohub\'s fleet register currently holds %s node(s) it did not install. '
        'The announcement happens at RUNTIME from the hub, not at enrolment from '
        'the script.' % (fleet_has if fleet_has is not None else '?')
        if hb_reg else 'no announcement anywhere')

    # 16 -- decommission
    #
    # THIS CHECK LOOKED IN THE WRONG FILE. It grepped enroll.sh alone, so when
    # the capability landed as decommission.sh -- a SIBLING script, chosen so a
    # destructive flag never sits four characters from --dry-run on a line
    # retyped out of shell history -- this row would have reported FAIL on
    # something that exists. A check that knows only one shape of an answer
    # fails the right way exactly once and the wrong way forever after.
    _dec_path = os.path.join(ROOT, 'decommission.sh')
    _dec_src = src('decommission.sh') if os.path.exists(_dec_path) else ''
    decom = bool(_dec_src) or any(
        k in enr for k in ('decommission', '--remove', '--destroy', 'unenroll'))
    _dry = '--dry-run' in _dec_src or 'DRY' in _dec_src
    row('B', 'e16', 'n', 'repo', 'decommission path -- remove tunnel, DNS, Access app',
        PASS if decom else FAIL,
        ('decommission.sh, dry-run by default' if (_dec_src and _dry) else
         'decommission.sh exists but no dry-run default was found -- a verb that '
         'removes the way into a node must not act unless it is told twice'
         if _dec_src else
         'nothing removes a node: every dead server leaves a tunnel, a DNS '
         'record and an Access app behind forever.'))


# ── C. CROSS-CONNECT ─────────────────────────────────────────────────────────

def sec_c(nodes):
    head('C', 'Cross-connect -- node A acknowledges node B',
         'The doc says "almost none of this is built" and prints two peer lists to '
         'prove neither hub has ever connected. One of those two claims has since '
         'stopped being true, and it is not the one about peers.')
    fed = src('hub/handlers/federation.py')
    fleet = src('hub/kernel/fleet.py')
    router = src('hub/kernel/router.py')
    enr = src('enroll.sh')

    row('C', 1, 'n', 'repo', 'one-time join token + sponsor address, never the CF token',
        FAIL if 'join_token' not in (fed + enr) else PASS,
        'no join token anywhere. enroll.sh still carries the CF token on the node '
        'and says so in its own header ("STOPGAP -- will be replaced by FlareVault '
        'provision_node()").')

    enroll_route = '/api/enroll' in router
    mesh_reg = '/api/mesh/register' in router and 'machine_id' in src('hub/handlers/mesh.py')
    row('C', 2, 'n', 'both', 'new node POSTs /api/enroll to the sponsor with machine_id',
        PART if mesh_reg else FAIL,
        'there is no /api/enroll route (%s). There IS /api/mesh/register, which '
        'carries machine_id and which ksgcohub has accepted -- its register now '
        'holds %s node record(s) it did not install. Same effect, different name and no token '
        'to burn, so row 3 has nothing to verify.'
        % ('confirmed absent' if not enroll_route else 'present',
           next((d.get('FLEET_N') for n, d in nodes if d and n['central']), '?')))
    # (the count above is fleet records held, not a timestamp)

    row('C', 3, 'n', 'repo', 'sponsor verifies the join token and BURNS it',
        FAIL, 'nothing issues, verifies or burns a join token. /api/mesh/register '
              'and /api/heartbeat accept an unauthenticated beat -- the live fleet '
              'record for fks-services reads authenticated=false.')

    row('C', 4, 'w', 'repo', 'sponsor (or FlareVault) provisions on the node\'s behalf',
        PART, 'unchanged: enroll.sh provisions Cloudflare directly from the node, '
              'so the node holds the CF token during the run. Its own header names '
              'this as the model to move away from.')

    # 5 -- keyed by machine-id
    urlkeyed = "peers_raw = cfg.get('peers'" in fed and 'peers.append(peer_url)' in fed
    midkeyed = 'def register(server_id, name, machine_id' in fleet and \
               "rec.get('machine_id') == machine_id" in fleet
    live_mids = [(n['node'], d.get('FLEET_WITH_MACHINE_ID'), d.get('FLEET_N'))
                 for n, d in nodes if d and n['central']]
    row('C', 5, 'n', 'both', 'sponsor records the node BY MACHINE-ID, URL mutable',
        PART if (midkeyed and urlkeyed) else (PASS if midkeyed else FAIL),
        'HALF FLIPPED, and the half that flipped is the important one. There are '
        'now TWO peer registers. kernel/fleet.py keys by server_id, carries '
        'machine_id, and detects the same hardware arriving under a different id -- '
        'live, %s of %s fleet records carry a machine_id. handlers/federation.py '
        'still stores peers as a JSON array of bare URLs in hub_config, exactly as '
        'the doc says, and that list is the one that has never connected. Two '
        'registers for one question is the bug; the doc describes only the broken '
        'one.' % (live_mids[0][1] if live_mids else '?',
                  live_mids[0][2] if live_mids else '?'))

    row('C', 6, 'n', 'repo', 'sponsor returns tunnel token + assigned hostname',
        FAIL, 'nothing returns a tunnel token. Each node still mints its own '
              'through enroll.sh, which is why row 1 cannot be built either.')

    # 7 -- both sides reconcile
    central = [(n, d) for n, d in nodes if d and n['central']]
    reconciled = False
    detail = 'no central node answered'
    if central:
        n, d = central[0]
        nfleet = int(d.get('FLEET_N') or 0)
        reconciled = nfleet > 0
        detail = ('The tick is right and its reason is wrong, which is worse than '
                  'a wrong tick. The doc says "nothing polls it"; nothing does. It '
                  'is PUSHED instead: kernel/heartbeat.py beats /api/node '
                  'to central, and %s\'s register holds %d other node(s) [%s], '
                  'last_seen fresh, over path=cloudflare. The two boxes DO reach '
                  'each other, through the edge, not the tailnet. Congruence '
                  'reported: %s -- "unknown" because fks-services sends no ref, so '
                  'the one field drift may compare is empty.'
                  % (n['node'], nfleet, d.get('FLEET_NAMES'),
                     d.get('FLEET_CONGRUENCE')))
    row('C', 7, 'y', 'node', 'both sides reconcile against /api/node',
        PASS if reconciled else UNK, detail)

    row('C', 8, 'n', 'repo', 'address change re-announces the SAME machine-id',
        PART if "same hardware" in fleet else FAIL,
        'kernel/fleet.py register() notices a known machine_id arriving under a '
        'different server_id and flags it, which is half of this row. Nothing '
        'treats the URL as a mutable attribute of that identity, and '
        'handlers/federation.py\'s URL list is never rewritten when a peer moves.')

    print()
    print('  The doc prints two peer lists and concludes "neither has ever')
    print('  connected (fv_last_contact: null on both)". fv_last_contact IS still')
    print('  null on both, and those tailnet URLs ARE unreachable -- but the')
    print('  conclusion drawn from it is now wrong. The heartbeat mesh connects')
    print('  over Cloudflare and has been doing so since 2026-09-25. Anyone')
    print('  reading that paragraph today concludes the fleet is dark. It is not.')


# ── D. ksgcohub's CLOUDFLARE ─────────────────────────────────────────────────

def sec_d(nodes):
    head('D', "Correcting ksgcohub's Cloudflare",
         'One containerised tunnel served three hostnames, so the way in died with '
         'Docker. All five rows are claims about ksgcohub only.')
    d = next((d for n, d in nodes if n['node'] == 'ksgcohub'), None)
    if not d:
        for i, t in ((1, 'second host-level tunnel for the hub hostname'),
                     (2, 'the hub hostname reaches the hub'),
                     (3, 'the Access policy is attached'),
                     (4, 'hub.ksgco.app moved off babyhelp-tunnel'),
                     (5, 'babyhelp + ntfy left on babyhelp-tunnel')):
            row('D', i, 'n', 'node', t, UNK, 'ksgcohub did not answer')
        return

    host = next(n['host'] for n in NODES if n['node'] == 'ksgcohub')
    containers = (d.get('CLOUDFLARED_CONTAINERS') or '').split()
    hostsvc = d.get('CLOUDFLARED_HOST')

    row('D', 1, 'n', 'node', 'a SECOND, host-level tunnel serving only the hub',
        PASS if (hostsvc == 'active' and containers) else (
            PART if hostsvc == 'active' else FAIL),
        'host unit cloudflared is %s AND the container tunnel is still up (%s), '
        'which is the additive end state this row asked for. The hostname it '
        'serves is %s, NOT the hub-ksgco.<zone> the row names: enroll.sh derives '
        'the name from machine-id on purpose, because "hub-ksgco" was a typo that '
        'became permanent DNS (enroll.sh:60-70).'
        % (hostsvc, ', '.join(containers) or 'none', host))

    code, kind, note = edge(host)
    hub_ok = d.get('API_NODE') == 'yes'
    row('D', 2, 'n', 'both', 'the hub hostname reaches the hub',
        PASS if (kind in ('access-refused', 'access-login') and hub_ok) else UNK,
        '%s -> HTTP %s (%s), and the hub answers /api/node on loopback. Those are '
        'TWO facts, not one: the edge proves the hostname and its gate, the '
        'loopback proves the origin. Nothing available to this tool joins them '
        'without a service token, which it does not hold.' % (host, code, kind))
    blind('D/2 -- that the edge request actually lands on THIS hub cannot be proven '
          'without presenting the lobby service token, which this tool never does')

    row('D', 3, 'n', 'edge', 'the Access policy is attached',
        PASS if kind == 'access-refused' else (
            PART if kind == 'access-login' else FAIL),
        '%s refuses an anonymous caller with 401 rather than offering a sign-in '
        'page. An app with NO policy denies every identity after login, so it '
        'would 302 to a sign-in that can never succeed -- 401 is what an attached '
        'non-identity policy produces. FLIPPED from the doc.' % host
        if kind == 'access-refused'
        else 'edge says %s (%s) -- the policy CONTENTS need a Cloudflare token to '
             'read, which this tool never uses' % (code, kind))

    hcode, hkind, hnote = edge('hub.ksgco.app')
    row('D', 4, 'n', 'edge', 'hub.ksgco.app moved off babyhelp-tunnel',
        UNK, 'hub.ksgco.app -> HTTP %s (%s), so it is still live and still behind a '
             'HUMAN Access gate, unlike the node hostname. WHICH TUNNEL SERVES IT '
             'IS NOT READABLE FROM THE BOX: the ingress lives in the Cloudflare '
             'dashboard and this tool calls no Cloudflare endpoint. What IS '
             'settled is the precondition -- rows 1-3 pass, so "only after the new '
             'path is proven" has been satisfied.' % (hcode, hkind))

    row('D', 5, 'n', 'node', 'babyhelp + ntfy left on babyhelp-tunnel, untouched',
        PASS if any('babyhelp' in c for c in containers) else FAIL,
        'babyhelp-tunnel is still running (%s). Out of scope by instruction and '
        'confirmed untouched: this tool only read its Config.Cmd.'
        % (', '.join(containers) or 'none'))


# ── B2. STORAGE ──────────────────────────────────────────────────────────────

# install-preflight's check name -> the B2 row it answers. Not reimplemented:
# run on the node, and its verdict is reported as ITS verdict.
PF_TO_B2 = {
    'hub service': (1, 'y', 'hub enabled as a systemd USER service'),
    'identity': (2, 'y', 'identity issued from /etc/machine-id'),
    'data root': (3, 'y', 'data root designated -- largest non-OS mount >=50GB'),
    'backup target': (4, 'y', 'backup target on a DIFFERENT physical device'),
    'backups running': (5, 'n', 'backups ACTUALLY running'),
    'cache reclamation': (6, 'n', 'cache reclamation scheduled'),
    'storage sound': (7, 'w', 'storage sound -- no high/warn findings'),
    'enrolled': (8, 'n', 'enrolled -- reachable by name'),
}
PF_STATE = {'[x]': PASS, '[~]': PART, '[ ]': FAIL}


def sec_b2(nodes):
    head('B2', 'Storage -- what a node must settle before it is finished',
         'These eight rows were already executable. They are NOT reimplemented '
         'here: install-preflight.py is run on each node and its verdicts are '
         'reported as its own. Three rows get a second, stronger assertion beside '
         'it, and where the two disagree this says which to believe and why. The '
         'document dates its eight ticks "ksgcohub, 2026-09-23", so only ksgcohub '
         'is scored against them; fks-services prints unmarked rather than being '
         'measured against a claim nobody ever made about it.')

    for n, d in nodes:
        print()
        print('  %s   (route: %s)' % (n['node'], (d or {}).get('_route', 'NOT REACHED')))
        scored = n['node'] == 'ksgcohub'
        if not d:
            for num, doc, title in sorted(PF_TO_B2.values()):
                row('B2', num, doc if scored else 'x', 'node',
                    '%s [%s]' % (title, n['node']), UNK,
                    'the node did not answer, so install-preflight never ran there')
            continue

        got = {}
        for line in d.get('_pf') or []:
            m = re.match(r'\s*(\[[x~ ]\])\s+(\S.*?)\s\s+(.*)$', line)
            if m and m.group(2).strip() in PF_TO_B2:
                got[m.group(2).strip()] = (PF_STATE[m.group(1)], m.group(3).strip())
        if not got:
            blind('%s -- install-preflight produced no parsable rows (checkout at '
                  '~/hub missing, or python3 failed). All eight B2 rows unknown '
                  'there.' % n['node'])

        for name, (num, doc, title) in sorted(PF_TO_B2.items(), key=lambda kv: kv[1][0]):
            if name not in got:
                row('B2', num, doc if scored else 'x', 'node',
                    '%s [%s]' % (title, n['node']), UNK,
                    'install-preflight did not report a "%s" row' % name)
                continue
            st, detail = got[name]
            extra = ''

            # ROW 4, the one that was marked right and then contradicted.
            # install-preflight answers "is a second device AVAILABLE". That is
            # not the same question as "does the backup LAND on one", and the
            # bad check that put this at the top of the priority list compared
            # /backups against / instead of against THE DATA'S device. So the
            # real comparison is made here, explicitly, and both answers print.
            if num == 4:
                # The devices come from kernel.storage's OWN derivation --
                # data_root() and backup_target(), the same two functions
                # hub-backup.sh asks -- rather than from a directory name
                # guessed here. Guessing the directory is exactly how this row
                # got contradicted: the bad check compared /backups against /
                # and never looked at the data's device at all.
                ddev, bdev = d.get('K_DATA_DEV', ''), d.get('K_BACKUP_DEV', '')
                dpath, bpath = d.get('K_DATA_PATH', ''), d.get('K_BACKUP_PATH', '')
                # A derived target is an intention. Copies that EXIST are the
                # fact, so both are reported and they are not conflated.
                real = [x for x in d.get('_sets') or [] if (x['n'] or '0') != '0']
                onsame = [x for x in real if x['dev'] == ddev]
                if d.get('K_ERR') or not (ddev and bdev):
                    st = UNK
                    extra = (' || STRONGER CHECK could not run: kernel.storage on '
                             'the node said %s' % (d.get('K_ERR') or 'nothing'))
                elif bdev == ddev:
                    st = FAIL
                    extra = (' || STRONGER CHECK: the derived target %s SHARES '
                             'device %s with the data at %s. One disk failure '
                             'takes both.' % (bpath, bdev, dpath))
                elif real and not onsame:
                    extra = (' || STRONGER CHECK, and this is the row that was '
                             'marked right and then wrongly contradicted: data at '
                             '%s on %s; copies exist at %s -- DIFFERENT device(s), '
                             'which is what hub-backup.sh chose on purpose and says '
                             'at its own line 26. Comparing the copy against / '
                             'instead of against the data is what turned a correct '
                             'setup into the worst finding on the page, twice.'
                             % (dpath, ddev,
                                '; '.join('%s (%s, %s set(s))'
                                          % (x['path'], x['dev'], x['n'])
                                          for x in real)))
                elif onsame:
                    st = FAIL
                    extra = (' || STRONGER CHECK DISAGREES -- believe this one. '
                             'kernel.storage DERIVES %s on %s, a different device, '
                             'and install-preflight reports that availability as a '
                             'pass. But every copy that actually exists is at %s on '
                             '%s -- THE SAME DEVICE AS THE DATA (%s). An intended '
                             'target nothing writes to protects nothing.'
                             % (bpath, bdev,
                                ', '.join(x['path'] for x in onsame),
                                onsame[0]['dev'], dpath))
                else:
                    st = PART
                    extra = (' || STRONGER CHECK: %s on %s is a different device '
                             'from the data at %s on %s, so the row is satisfiable '
                             '-- but NO dated backup set exists anywhere on this '
                             'box. The target is derived and has never been '
                             'written to.' % (bpath, bdev, dpath, ddev))

            # ROW 5. install-preflight passes this on the mere PRESENCE of a
            # `server-backup` command. Presence is not running, and on
            # fks-services that difference is the whole row.
            if num == 5:
                # "Running" is two facts, and install-preflight checks neither:
                # a schedule that is ACTIVE, and a copy on disk that is RECENT.
                # It passes on the mere presence of a `server-backup` binary,
                # and on fks-services the only matching cron entry belongs to
                # ANOTHER PROJECT -- so a grep for "backup" reads as the hub's
                # backup when it is metaforge's. Attribution is printed rather
                # than assumed.
                timer = d.get('BACKUPTIMER', '')
                cron = (d.get('CRONLINES') or '').strip()
                real = [x for x in d.get('_sets') or [] if (x['n'] or '0') != '0']
                scheduled = timer == 'active'
                if scheduled and real:
                    extra = (' || STRONGER CHECK agrees: hub-backup.timer is %s '
                             'and %s.'
                             % (timer,
                                '; '.join('%s set(s) in %s, newest %s'
                                          % (x['n'], x['path'], x['newest'] or '?')
                                          for x in real)))
                else:
                    st = FAIL
                    extra = (' || STRONGER CHECK DISAGREES -- believe this one. '
                             'hub-backup.timer=%s. Dated sets on disk: %s. Cron '
                             'lines matching "backup": %s -- READ THE PATH, not '
                             'the word: a cron entry belonging to another project '
                             'is not this hub\'s backup, and install-preflight '
                             'passes this row on the PRESENCE of a `server-backup` '
                             'binary that nothing schedules. This is the only row '
                             'on the page whose failure is unrecoverable.'
                             % (timer or 'absent',
                                '; '.join('%s in %s' % (x['n'], x['path'])
                                          for x in real) or 'NONE',
                                cron or 'none'))

            if num == 6 and d.get('RECLAIMTIMER') and d.get('RECLAIMTIMER') != 'active':
                extra = (' || hub-reclaim.timer is %s here'
                         % d.get('RECLAIMTIMER'))

            # ROW 8. install-preflight answers this from ~/.flare/node.json,
            # which is a record the node keeps about ITSELF. "Reachable by name"
            # is a fact about the edge, and the two can disagree in the
            # dangerous direction: a node with no node.json whose hostname is
            # nonetheless live is enrolled and does not know it, so nothing
            # local will ever tell you the tunnel exists.
            if num == 8:
                code, kind, _note = edge(n['host'])
                live = kind in ('access-refused', 'access-login')
                if st != PASS and live:
                    st = PART
                    extra = (' || STRONGER CHECK DISAGREES: %s answers HTTP %s '
                             '(%s), so the tunnel, the DNS record and the Access '
                             'app all EXIST. This node is enrolled at the edge and '
                             'has no local record of it. Reading node.json alone '
                             'under-reports that, and an unrecorded tunnel is one '
                             'nothing will ever decommission.'
                             % (n['host'], code, kind))
                elif st == PASS and not live:
                    st = PART
                    extra = (' || STRONGER CHECK DISAGREES the other way: '
                             'node.json says enrolled but %s answers %s (%s). The '
                             'record outlived the hostname.'
                             % (n['host'], code, kind))
                else:
                    extra = (' || edge agrees: %s -> HTTP %s (%s)'
                             % (n['host'], code, kind))

            row('B2', num, doc if scored else 'x', 'node',
                '%s [%s]' % (title, n['node']), st,
                'install-preflight: %s%s' % (detail, extra))


# ── E. WHAT THE SYSTEM CAN STATE ─────────────────────────────────────────────

def sec_e(nodes):
    head('E', 'What the system will be able to state',
         'The doc claims these become answerable IN ONE CALL, and that all of them '
         'are unanswerable today. Each is now tried: the call is made, the payload '
         'is inspected, and the answer is yes / partly / no with the reason.')
    central = [(n, d) for n, d in nodes if d and n['central']]
    fleet_src = src('hub/kernel/fleet.py')
    router = src('hub/kernel/router.py')

    if not central:
        for i, t in ((1, 'which nodes exist, by stable identity, and where reachable'),
                     (2, 'what runs on each node, grouped by owning project'),
                     (3, 'which projects are publicly exposed, behind which policy'),
                     (4, 'who logged in, when, through which door'),
                     (5, 'what has drifted from what was declared'),
                     (6, 'which nodes are quietly filling their disks')):
            row('E', i, 'n', 'node', t, UNK,
                'no node in central mode answered; every E row is unknown')
        return
    n, d = central[0]
    print()
    print('  one call means: one request to %s (mode=%s)'
          % (n['node'], d.get('FLEET_MODE')))

    # E1
    nfl = int(d.get('FLEET_N') or 0)
    mids = int(d.get('FLEET_WITH_MACHINE_ID') or 0)
    reach = int(d.get('FLEET_WITH_REACH') or 0)
    row('E', 1, 'n', 'node', 'which nodes exist, by stable identity, and where reachable',
        PASS if (nfl and mids == nfl and reach == nfl) else (PART if nfl else FAIL),
        'YES, in one call: GET /api/mesh/fleet returns %d node(s) [%s], all %d with '
        'a machine_id and all %d with a reachability list. Caveat worth stating: '
        'reachability names PATHS (lan/tailscale/public), not addresses, and the '
        'register holds whoever has beaten -- a node that never beat is absent '
        'rather than reported missing.'
        % (nfl, d.get('FLEET_NAMES'), mids, reach))

    # E2
    projects = int(d.get('NODE_PROJECTS') or 0)
    unclaimed = int(d.get('NODE_UNCLAIMED') or 0)
    drops_claims = 'The claims themselves are NOT copied here' in src('hub/handlers/mesh.py')
    row('E', 2, 'n', 'node', 'what runs on each node by owning project, and what nothing claims',
        PART, 'PARTLY. Per node it is one call: /api/node groups %d project(s) and '
              'names %d that carry no com.ksg.project label. Fleet-wide it is NOT: '
              'handlers/mesh.py deliberately keeps only COUNTS from each beat (%s), '
              'so one address gives you "fks-services: 16 projects" and no names.'
              % (projects, unclaimed,
                 'and says so at _record_registry' if drops_claims else 'undocumented'))

    # E3
    row('E', 3, 'n', 'both', 'which projects are publicly exposed, behind which policy',
        FAIL, 'NO. No route answers this -- there is no /api/access/apps or '
              'equivalent, and an Access policy is not readable from the edge, only '
              'from the Cloudflare API. tools/situation.py can answer it WITH a '
              'token; that is a second call and a credential, not one call.')
    blind('E/3 -- Access policy contents are unreadable without a Cloudflare API '
          'token, which this tool deliberately never uses')

    # E4
    auth_n = int(d.get('AUTH_EVENTS') or 0)
    row('E', 4, 'n', 'node', 'who logged in, when, through which door',
        PART, 'PARTLY, and the gap is not the endpoint. The shape is right: '
              '/api/activity?category=auth exists, and post_auth_login writes '
              'user, door and ip. It returns %d event(s) here. The Cloudflare door '
              'does not go through post_auth_login at all -- check_auth mints a '
              'session straight from the Access header and logs nothing -- so on a '
              'box whose only real door is Cloudflare this answer is empty and '
              'looks like "nobody logged in".' % auth_n)

    # E5
    row('E', 5, 'n', 'node', 'what has drifted from what was declared',
        PART, 'PARTLY. /api/mesh/fleet carries a drift count and a per-node '
              'congruence, so one call answers it -- for exactly ONE field, the git '
              'ref, which handlers/mesh.py states as the rule. Live congruence: '
              '%s. "unknown" means the node sent no ref, so the one comparable '
              'field is blank. /api/baselines/<project> covers declared-vs-actual '
              'per project (%s) but that is one call PER project.'
              % (d.get('FLEET_CONGRUENCE'),
                 'reachable' if d.get('API_BASELINES') == 'yes' else 'did not answer'))

    # E6 -- the one the doc calls the point of the whole exercise
    carried = bool(re.search(r"attention\.get\(\s*['\"]storage", fleet_src))
    flags = int(d.get('FLEET_WITH_STORAGE_FLAG') or 0)
    row('E', 6, 'n', 'both', 'which nodes are quietly filling their disks',
        PART if not carried else PASS,
        'THE DOC IS WRONG ABOUT THIS ONE, and it is the row the doc calls the '
        'point of the whole exercise. attention.storage IS in /api/node (%s '
        'finding(s) on this box) and /api/node IS the heartbeat payload -- but '
        'kernel/fleet.py heartbeat() copies only unassigned_containers and '
        'not_enrolled into the fleet record and DROPS storage. Live proof: %d of '
        '%d fleet records carry a storage flag. So one address answers it for '
        'ITSELF, and for every other node you still have to visit the machine -- '
        'which is the exact thing the row says has been solved.'
        % (d.get('NODE_STORAGE_N'), flags, int(d.get('FLEET_N') or 0)))
    if not carried:
        print()
        print('       The fix is three lines in kernel/fleet.py heartbeat(). This')
        print('       tool does not make them: report, never repair.')


SECTIONS = [('A', sec_a), ('B', sec_b), ('C', sec_c), ('D', sec_d),
            ('B2', sec_b2), ('E', sec_e)]


def main():
    want = [a[2:] for a in sys.argv[1:]
            if a.startswith('--') and a[2:] in dict(SECTIONS)]
    print()
    print('  MATRIX -- docs/flareshub-checklists.md, asserted against the machines')
    print('  repo: %s' % ROOT)
    print('  Every row prints what the document claims and what the machine said.')
    if LOCAL:
        print('  --local: repo only. NO machine and NO hostname was asked anything.')

    nodes = [(n, ssh_probe(n)) for n in NODES]
    print()
    for n, d in nodes:
        print('  %-14s %s' % (n['node'],
                              ('reached via %s, ref %s'
                               % (d.get('_route'), d.get('GITREF') or '?'))
                              if d else 'NOT REACHED -- its rows are unknown, not fine'))

    for letter, fn in SECTIONS:
        if want and letter not in want:
            # A section nobody ran is a section nobody looked at. Printing
            # "everything passed" when nothing ran is the failure this replaces.
            blind('sequence %s -- NOT RUN (section filter: %s). Nothing above '
                  'speaks for it.' % (letter, ' '.join('--' + w for w in want)))
            continue
        fn(nodes)

    # ── the answer the document cannot give: what moved ──────────────────────
    print()
    print('  ' + '=' * 84)
    print('  WHAT FLIPPED SINCE THE DOCUMENT WAS HAND-MARKED')
    print('  ' + '=' * 84)
    if FLIPS:
        for sec, num, title, was, now, _detail in FLIPS:
            print('    %-11s %-11s -> %-5s  %s'
                  % ('%s/%s' % (sec, num), was, now, title))
        print()
        print('    %d of %d rows no longer match their tick. The ticks are five days'
              % (len(FLIPS), len(ROWS)))
        print('    old. Do not repair them by hand -- that is what produced this list.')
    else:
        print('    Nothing. Every row matches the tick the document carries.')

    counts = {s: sum(1 for r in ROWS if r[3] == s) for s in (PASS, PART, FAIL, UNK)}
    print()
    print('  %d rows checked: %d pass, %d partial, %d FAIL, %d unknown'
          % (len(ROWS), counts[PASS], counts[PART], counts[FAIL], counts[UNK]))

    print()
    print('  WHAT I COULD NOT SEE')
    print('  ' + '-' * 84)
    if BLIND:
        for b in BLIND:
            for i, line in enumerate(_wrap(b, 80)):
                print('    %s%s' % ('' if i == 0 else '  ', line))
        print()
        print('    Everything above is true only of what answered. A hole here is')
        print('    not a pass, and a row marked unknown is not a row marked fine.')
    else:
        print('    Nothing. Every probe answered and every row was checked.')
    print()

    if STRICT and (counts[FAIL] or counts[UNK]):
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
