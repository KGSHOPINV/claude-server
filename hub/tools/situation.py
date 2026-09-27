#!/usr/bin/env python3
"""
# 20404715  tools.situation — is it serving itself correctly, and to whom?

    python3 hub/tools/situation.py
    python3 hub/tools/situation.py --json
    python3 hub/tools/situation.py --hub http://100.107.234.9:8765   # from elsewhere

THE PROBLEM THIS EXISTS FOR. Three failures in one evening looked IDENTICAL
from outside and were three completely different things. Each cost many rounds
to untangle, and every round was spent arguing about which one it was:

    "ksgcohub is down"          it was serving everything perfectly. The
                               operator's own Tailscale had died.
    "claude.ai is blocked"      real, hours earlier, not reproducible now.
    "Tailscale is connected"    the GUI said yes. The daemon was in NoState
                               with no route.

So the central job of this tool is not to find faults. It is to make
"the thing is broken" and "I cannot see the thing" impossible to confuse.
Everything below is arranged around that one distinction:

  * Every check reports reached / not reached BEFORE it reports any judgement.
    A check that could not run produces "unknown", never "healthy".
  * Group D is the list of things it could not see, and it must never be empty
    when something was unreachable. Silence is not health.
  * Reachability is compared ACROSS PATHS (public edge vs tailnet vs LAN vs
    loopback), because that comparison is the only thing that can tell the
    operator's broken viewer apart from a broken node. See perspective().

THE SECOND JOB. "Serving itself correctly and also not exposing it to the
public." Those are one question asked from two sides, so both sides are here:

    A SERVING     every hostname this node answers for, and whether the status
                  it returns is the EXPECTED one for what that hostname IS.
                  A node hostname answering 401 is CORRECT. The same hostname
                  answering 200 is an EXPOSURE. Codes alone say neither, so
                  the expectation is encoded, not printed for a human to know.
    B EXPOSURE    what answers with NO credential, and from where.
    C ENTRY CHAIN the public login space, /fleet, /s/<id>/ and every node
                  endpoint: which Access app covers it and what its policies
                  actually are.
    D BLIND       what could not be checked, and why.

CONSTITUTION Law IV — report, never repair. This writes nothing, restarts
nothing, and calls no Cloudflare endpoint but GET. Every finding carries the
command that would show more; it runs none of them.

CONSTITUTION Law V — no secret reaches this output. The Cloudflare API token is
read and never printed, not even truncated; only WHERE it came from. The
service token file is stat'ed, never opened. node.json's tunnel id is
truncated. Nothing here holds a value it could leak, so there is no leak to
prevent later.

THE HONEST LIMITS, stated up front because a checker that overstates its reach
is worse than none:

  IT ONLY KNOWS THE BOX IT IS RUNNING ON. env, the sqlite config, ~/.flare and
  the bind address are facts about THIS machine. Point --hub at another box and
  every one of those becomes "unknown for the target" and moves to group D
  rather than being quietly reported as if it were the target's. That
  substitution — describing the local box under a remote box's name — is the
  worst bug a fleet tool can have, and it has already happened here once
  (see handlers/lobbyhost.py, why the Fleet pane was removed).

  A STATUS FROM THE EDGE DOES NOT PROVE THE ORIGIN IS UP. 401, 302 and 404 can
  all be minted by Cloudflare without a packet reaching the box. What a public
  probe proves is that the hostname exists and something is guarding it.
  Said again in the output, every time, rather than assumed understood.

  NO CREDENTIAL IS PRESENTED, EVER. So this can prove a path is OPEN. It cannot
  prove a closed path works for someone who is allowed through. "401" here
  means "refused me", not "correctly configured for the lobby".

  AN ACCESS APP IS NOT READ FROM THE EDGE, IT IS READ FROM THE API. Without a
  Cloudflare token group C is unknown — not empty, unknown.
"""
import json
import os
import re
import socket
import sqlite3
import subprocess
import sys
import time
import urllib.error
import urllib.request

CF_API = 'https://api.cloudflare.com/client/v4'


# 20404829  _root — where the repo is, surviving having no __file__
def _root():
    """Where the repo is, and it must survive having no __file__.

    This gets run three ways: as a file on a node, as a file on the operator's
    Windows PC, and piped over ssh into `python3 -` so that inspecting a box
    does not require WRITING a tool onto it. The third way has no __file__ at
    all, and a NameError at import is not "degrading honestly".

    HUB_ROOT is the override for the piped case. Everything that reads the repo
    handles '' by reporting that it could not read it, so a wrong root produces
    'unknown', never a wrong answer.
    """
    env = os.environ.get('HUB_ROOT', '').strip()
    if env:
        return env
    try:
        return os.path.dirname(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__))))
    except NameError:
        return os.getcwd()


ROOT = _root()
HUB_DIR = os.path.join(ROOT, 'hub')

# The six paths named in the brief, because these are the ones whose exposure
# actually costs something. Not a sample: every one of these was returning 200
# with no credential on a box whose gates are declared at 1 and 2.
WATCHED = ('/api/config', '/api/status', '/api/containers', '/api/vault',
           '/api/node', '/api/lobby')

# Severity vocabulary. Four words, fixed, because a findings list a model reads
# is only useful if the words mean the same thing every run.
EXPOSURE = 'exposure'   # something reachable that should not be
BROKEN = 'broken'       # something that should answer and does not
DRIFT = 'drift'         # declared posture and real posture disagree
UNKNOWN = 'unknown'     # could not be determined — never folded into 'ok'

LOCAL_HOSTS = ('127.0.0.1', 'localhost', '::1', '[::1]')


# ── plumbing ────────────────────────────────────────────────────────────────
# Everything in this section returns a value and never raises. A diagnostic
# that dies on the first missing file diagnoses nothing, and the machines this
# runs on are deliberately different from each other: a node has /proc, a
# systemd unit and ~/.flare; the operator's Windows PC has none of them.

# 20404803  _now — one timestamp for the whole run
def _now():
    return time.strftime('%Y-%m-%dT%H:%M:%S', time.localtime())


# 20404804  _read — a repo file, or '' if it is not there
def _read(rel):
    try:
        with open(os.path.join(ROOT, rel), encoding='utf-8', errors='ignore') as f:
            return f.read()
    except Exception:
        return ''


# 20404805  _probe — one HTTP request, and what its status MEANS
def _probe(url, timeout=8, host_header=None):
    """Never raises. Returns reached/status/error, and nothing else.

    `reached` is the load-bearing field and it is deliberately separate from
    `status`. reached=False with status=None is "I could not see it". That is
    NOT a 500 and it is NOT down — it is the answer that got confused with
    both, three times in one evening.

    No credential is sent and no redirect is followed. Not following the
    redirect is the point: a 302 to a Cloudflare login IS the finding, and
    chasing it would replace that finding with whatever the login page returns.
    """
    class _NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *a, **k):
            return None

    headers = {'User-Agent': 'FlareSHub-situation/1 (read-only)'}
    if host_header:
        headers['Host'] = host_header
    req = urllib.request.Request(url, headers=headers)
    op = urllib.request.build_opener(_NoRedirect)
    t0 = time.time()
    try:
        with op.open(req, timeout=timeout) as r:
            return {'reached': True, 'status': r.status, 'error': None,
                    'ms': int((time.time() - t0) * 1000)}
    except urllib.error.HTTPError as e:
        # An HTTP error IS an answer. Something is there and it refused us,
        # which is frequently the correct outcome.
        return {'reached': True, 'status': e.code, 'error': None,
                'ms': int((time.time() - t0) * 1000)}
    except urllib.error.URLError as e:
        return {'reached': False, 'status': None, 'error': str(e.reason)[:90],
                'ms': int((time.time() - t0) * 1000)}
    except Exception as e:
        return {'reached': False, 'status': None, 'error': str(e)[:90],
                'ms': int((time.time() - t0) * 1000)}


# 20404806  _dns — does the name resolve at all, and to what
def _dns(name):
    """Separated from _probe on purpose. "DNS does not resolve" and "it
    resolves and nothing answers" are different faults with different fixes,
    and a single failed curl cannot tell them apart."""
    try:
        infos = socket.getaddrinfo(name, None)
        addrs = sorted({i[4][0] for i in infos})
        return {'resolves': True, 'addrs': addrs, 'error': None}
    except Exception as e:
        return {'resolves': False, 'addrs': [], 'error': str(e)[:90]}


# 20404807  _cf_token — the same places enroll.sh looks, and the VALUE NEVER LEAVES
def _cf_token():
    """Returns (token, source). The token is used and never reported: the
    caller gets `source` to print and nothing else. cf-check.py prints four
    characters of it; that is four more than anything needs."""
    t = os.environ.get('CF_API_TOKEN', '').strip()
    if t:
        return t, '$CF_API_TOKEN'
    for p in (os.path.expanduser('~/.cf-token'), '/etc/flare/token'):
        try:
            with open(p, encoding='utf-8', errors='ignore') as f:
                m = re.findall(r'[A-Za-z0-9_\-]{30,}', f.read())
            if m:
                return m[0], p
        except Exception:
            continue
    return '', ''


# 20404808  _cf — one Cloudflare GET. GET only, structurally.
def _cf(token, path, timeout=20):
    """Returns (body, why). Exactly one is falsy.

    There is no method parameter. Not "defaults to GET" — no parameter, so
    this module cannot be edited into something that writes by passing a
    string. A tool whose job is to name exposures must not be able to create
    one.
    """
    if not token:
        return None, 'no Cloudflare token'
    req = urllib.request.Request(
        CF_API + path, headers={'Authorization': 'Bearer ' + token,
                                'Content-Type': 'application/json'})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.load(r), ''
    except urllib.error.HTTPError as e:
        try:
            body = json.load(e)
        except Exception:
            return None, 'HTTP %s from the Cloudflare API' % e.code
        errs = (body or {}).get('errors') or []
        if errs:
            return None, '%s %s' % (errs[0].get('code', ''), errs[0].get('message', ''))
        return None, 'HTTP %s from the Cloudflare API' % e.code
    except Exception as e:
        return None, str(e)[:90]


# 20404809  _lan_addr — this box's own routable address, derived not configured
def _lan_addr():
    """The UDP-connect trick: it names a destination so the kernel picks a
    source interface, and sends nothing. Returns '' rather than guessing on a
    box with no route, because a wrong LAN address probes some other machine
    and reports the answer under this one's name."""
    for dest in ('192.168.1.1', '8.8.8.8'):
        s = None
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.settimeout(1.0)
            s.connect((dest, 9))
            ip = s.getsockname()[0]
            if ip and not ip.startswith('127.'):
                return ip
        except Exception:
            continue
        finally:
            if s is not None:
                try:
                    s.close()
                except Exception:
                    pass
    return ''


# 20404810  _tailscale — the daemon's own answer, not the GUI's claim
def _tailscale():
    """THE GUI IS NOT EVIDENCE. It said "connected" while the daemon sat in
    NoState with no route, and an evening went into believing it. So this asks
    the daemon and reports BackendState verbatim.

    Absent binary is a legitimate state ("unknown"), not a fault. Running this
    inside a container or on a box that never had Tailscale must not invent a
    Tailscale problem.
    """
    for exe in ('tailscale', 'tailscale.exe',
                r'C:\Program Files\Tailscale\tailscale.exe',
                '/usr/bin/tailscale'):
        try:
            p = subprocess.run([exe, 'status', '--json'],
                               capture_output=True, text=True, timeout=12)
        except Exception:
            continue
        if not (p.stdout or '').strip():
            return {'known': False, 'why': '%s ran but said nothing' % exe,
                    'state': None, 'self': None}
        try:
            d = json.loads(p.stdout)
        except Exception:
            return {'known': False, 'why': '%s returned unparseable json' % exe,
                    'state': None, 'self': None}
        me = (d.get('Self') or {})
        ips = me.get('TailscaleIPs') or []
        return {'known': True, 'why': '', 'state': d.get('BackendState'),
                'self': me.get('HostName') or '',
                'ips': ips,
                'online': bool(me.get('Online')),
                'peers': len(d.get('Peer') or {})}
    return {'known': False, 'why': 'no tailscale binary on this machine',
            'state': None, 'self': None}


# ── what the code DECLARES, read from the code ──────────────────────────────

# 20404811  _declared_gates — the gate each watched path claims, from ROUTES
def _declared_gates():
    """Law I: derive, do not maintain. A copy of the gate levels typed into
    this file would be wrong the first time a route moved, and wrong silently,
    which is the only kind that matters. So the route table is parsed.

    Returns (map, source). A fallback map is provided for the case where the
    repo is not beside this file, and it is LABELLED as a fallback in the
    output — a guess that presents as a reading is how a checker starts lying.
    """
    src = _read('hub/kernel/router.py')
    if not src:
        return ({'/api/config': 1, '/api/status': 1, '/api/containers': 1,
                 '/api/vault': 2, '/api/node': 1, '/api/lobby': 1},
                'declared inside situation.py — router.py was not readable, '
                'so this may have drifted from the real table')
    out = {}
    for m in re.finditer(r'"path":\s*"([^"]+)".*?"gate":\s*(\d+)', src):
        out.setdefault(m.group(1), int(m.group(2)))
    if not out:
        return ({}, 'router.py was readable but no route entries parsed — '
                    'the table shape changed and this parser did not')
    return out, 'parsed from hub/kernel/router.py ROUTES'


# 20404812  _splash_hosts — the hostnames that are PUBLIC on purpose
def _splash_hosts():
    """The apex is a public page, so it cannot sit behind Access, so it reaches
    the origin with nothing in front of it. router._splash_only is the entire
    reason /api/config is not on the open internet today. Which hostnames it
    covers is therefore worth reading rather than assuming."""
    env = os.environ.get('HUB_SPLASH_HOSTS', '').strip()
    if env:
        return [h.strip().lower() for h in env.split(',') if h.strip()], 'env HUB_SPLASH_HOSTS'
    src = _read('hub/kernel/router.py')
    m = re.search(r"'HUB_SPLASH_HOSTS',\s*'([^']*)'", src)
    if m:
        return [h.strip().lower() for h in m.group(1).split(',') if h.strip()], \
               'default in hub/kernel/router.py'
    return [], 'could not determine'


# 20404828  _behind_login — the paths _splash_only lets THROUGH on a splash host
def _behind_login():
    """SPLASH_BEHIND_LOGIN is the most dangerous list in the hub and the least
    obvious one, so it gets its own reader.

    _splash_only 404s the whole API on a splash host EXCEPT these paths, and it
    lets them through on one assumption, written in the comment beside it:
    "Cloudflare Access is scoped to these paths, so a request only arrives here
    having already signed in."

    That assumption is per HOSTNAME, and the code cannot check it. An Access app
    on flarevault.dev/api does not cover www.flarevault.dev/api. So the moment a
    second splash hostname exists without its own path-scoped apps, every path
    on this list is on the open internet with gates in shadow mode behind it —
    and _splash_only reads as though it is protecting them.

    This is exactly the incident the code comment describes, which means the
    check has to exist outside the code that made the assumption.
    """
    src = _read('hub/kernel/router.py')
    m = re.search(r'SPLASH_BEHIND_LOGIN\s*=\s*\((.*?)\)', src, re.S)
    if not m:
        return [], 'SPLASH_BEHIND_LOGIN could not be parsed from router.py'
    paths = re.findall(r"'([^']+)'", m.group(1))
    return paths, 'parsed from hub/kernel/router.py SPLASH_BEHIND_LOGIN'


# 20404813  _bind — what address the hub listens on, and whether it is a choice
def _bind():
    """Read from source, because there is nothing else to read: server.py
    hardcodes ('0.0.0.0', PORT) with no env override. That is the finding.
    An operator who wants the hub on loopback only cannot get there from
    configuration; it takes a code change.
    """
    src = _read('hub/server.py')
    m = re.search(r"ThreadedServer\(\(\s*'([^']+)'\s*,", src)
    if not m:
        return {'known': False, 'addr': None, 'configurable': None,
                'why': 'hub/server.py not readable from here'}
    addr = m.group(1)
    knob = bool(re.search(r"HUB_BIND|HUB_HOST\b", src))
    return {'known': True, 'addr': addr, 'configurable': knob, 'why': ''}


# 20404814  _totp_configured — the switch that decides whether gates 2 and 3 exist
def _totp_configured(db_path):
    """auth.gate_check returns TRUE when totp_secret is unset. Read that line
    again: with no TOTP configured, every gate-2 and gate-3 route admits
    anyone who got past gate 1 — and gate 1 is not enforced either. /api/vault
    is gate 2. /api/run is gate 3.

    So this single row decides whether two thirds of the declared posture
    exists at all, and it is the least visible fact on the box.

    Opened URI read-only. This tool must not be capable of creating the
    database it is inspecting, which a plain sqlite3.connect() on a missing
    path would cheerfully do.
    """
    if not db_path or not os.path.isfile(db_path):
        return {'known': False, 'configured': None,
                'why': 'no hub database at %s' % (db_path or '(unknown path)')}
    try:
        uri = 'file:%s?mode=ro' % db_path.replace('?', '%3f').replace('#', '%23')
        conn = sqlite3.connect(uri, uri=True, timeout=5)
        row = conn.execute(
            "SELECT value FROM hub_config WHERE key='totp_secret'").fetchone()
        conn.close()
        # The VALUE is never touched beyond asking whether it is empty.
        return {'known': True, 'configured': bool(row and row[0]), 'why': ''}
    except Exception as e:
        return {'known': False, 'configured': None,
                'why': 'hub_config unreadable: %s' % str(e)[:60]}


# ── A. SERVING ──────────────────────────────────────────────────────────────

# 20404815  _classify — what KIND of hostname this is, which sets the expectation
def _classify(host, splash, reaches_hub=None, node_prefix='flareshub-'):
    """The whole point of group A. A status code is meaningless without knowing
    what the hostname is FOR:

      node    flareshub-<id>.<zone>. Service-token only, by spec rule 6. It
              MUST refuse a browser. 401/403 is the pass. 302 means a human
              identity policy is attached to a hostname that is supposed to
              refuse humans. 200 means no gate at all.
      splash  the apex. Public on purpose, serves the login space and nothing
              else. 200 at / is correct; 200 at /api/* is the four-minute
              incident repeating.
      human   an Access-protected hostname into the HUB. 302 to a login is
              correct; 200 to an anonymous request is not.
      other   a hostname on the same tunnel that does NOT reach the hub port.

    WHY 'other' EXISTS. The first version classified every tunnel hostname as
    'human' and duly reported ntfy.ksgco.app answering 200 as an EXPOSURE. ntfy
    is a notification service on another port, and a public one may be exactly
    what the operator intends. This tool knows what the HUB should expose; it
    knows nothing about the other nine services sharing the tunnel, and
    inventing an expectation for them is how a security report earns the right
    to be ignored. So they are listed, and their status is reported as
    unjudged rather than as a fault.
    """
    h = (host or '').lower()
    if h in splash:
        return 'splash'
    if h.startswith(node_prefix):
        return 'node'
    if reaches_hub is False:
        return 'other'
    return 'human'


# Encoded expectations. Deliberately a table and not prose: "401 is correct
# here" is exactly the kind of knowledge that lived in one person's head and
# cost a round of argument every time a code was read out loud.
EXPECT = {
    # kind:   root path          what a CREDENTIAL-FREE request should get
    'node':   {'ok': (401, 403), 'exposed': (200,),
               'drift': (302,),
               'means': 'service-token only — a browser must be refused'},
    'splash': {'ok': (200,), 'exposed': (),
               'drift': (302, 401, 403),
               'means': 'public login space — the page itself is meant to load'},
    'human':  {'ok': (302, 401, 403), 'exposed': (200,),
               'drift': (),
               'means': 'behind Access — an anonymous request should be sent to a login'},
    # Nothing is 'exposed' here on purpose: see _classify. This tool has no
    # standing to say what another service on the same tunnel should answer.
    'other':  {'ok': (), 'exposed': (), 'drift': (),
               'means': 'on this tunnel but NOT pointed at the hub — this tool has '
                        'no expectation for it and is not pretending to'},
}


# 20404816  serving — every hostname this node answers for, and whether it is right
def serving(ctx):
    """Hostnames are DERIVED from three sources and each is labelled, because
    which source a hostname came from changes what its absence means:

      node.json     the one hostname enrolment created for this box.
      tunnel ingress the real list — what Cloudflare will actually route here.
                    This is the source that catches the case that hurts: a
                    hostname added to the tunnel by hand, pointing at the hub,
                    with no Access app in front of it.
      splash hosts   the apex names the code treats as public.

    With no Cloudflare token the middle source is missing, and the hostname
    list is then INCOMPLETE — which is reported, because a short list that
    looks complete is worse than no list.
    """
    out = {'sources': [], 'hostnames': [], 'complete': False}
    seen = {}

    nj = ctx['node_json']
    if nj.get('hostname'):
        seen[nj['hostname'].lower()] = ['node.json']
        out['sources'].append('~/.flare/node.json')
    elif ctx['target_local']:
        ctx['blind'].append({
            'check': 'hostnames from node.json',
            'why': 'this box has no ~/.flare/node.json — it has never enrolled',
            'command': 'cat ~/.flare/node.json'})

    for h in ctx['splash_hosts']:
        seen.setdefault(h, []).append('splash host')
    if ctx['splash_hosts']:
        out['sources'].append('router.SPLASH_HOSTS (%s)' % ctx['splash_source'])

    ing = ctx['ingress']
    if ing['known']:
        out['sources'].append('cloudflare tunnel ingress')
        out['complete'] = True
        for e in ing['entries']:
            if e.get('hostname'):
                seen.setdefault(e['hostname'].lower(), []).append('tunnel ingress')
    # ing['why'] already went into blind at collection time.

    hub_port = str(ctx['hub_port'])
    for host in sorted(seen):
        svc = ''
        for e in ing.get('entries', []):
            if (e.get('hostname') or '').lower() == host:
                svc = e.get('service') or ''
        reaches_hub = (':' + hub_port) in svc if svc else None
        kind = _classify(host, ctx['splash_hosts'], reaches_hub)

        d = _dns(host)
        rec = {'hostname': host, 'kind': kind, 'from': seen[host],
               'tunnel_service': svc or None, 'reaches_hub': reaches_hub,
               'dns_resolves': d['resolves'], 'dns_error': d['error'],
               'status': None, 'reached': False, 'ok': None, 'unknown': True,
               'expected': list(EXPECT[kind]['ok']),
               'means': EXPECT[kind]['means'], 'verdict': 'unknown'}

        if not d['resolves']:
            rec['verdict'] = 'dns does not resolve'
            ctx['find'](UNKNOWN if not ctx['dns_works'] else BROKEN,
                        'hostname %s does not resolve' % host,
                        'DNS, from wherever this tool ran',
                        'a hostname that does not resolve serves nobody — but if '
                        'this machine has no working DNS at all, the hostname may '
                        'be fine and the VIEWER is broken. Which it is, is in the '
                        'vantage block.',
                        'nslookup %s' % host)
            out['hostnames'].append(rec)
            continue

        p = _probe('https://%s/' % host, ctx['timeout'])
        rec['reached'] = p['reached']
        rec['status'] = p['status']
        rec['error'] = p['error']
        if not p['reached']:
            rec['verdict'] = 'no answer'
            rec['unknown'] = True
            ctx['find'](UNKNOWN,
                        'https://%s/ did not answer' % host,
                        'the public edge',
                        'resolves but nothing answered. This is NOT proof the '
                        'origin is down: the edge itself may be the thing that '
                        'did not reply, and this tool cannot tell from here.',
                        'curl -sSv -m 10 https://%s/' % host)
            # Also in group D, because "a hostname I could not reach" is the
            # definition of something I could not see, and group D is where the
            # operator is told to look when the verdict surprises them.
            ctx['blind'].append({
                'check': 'whether %s is serving correctly (A)' % host,
                'why': 'it resolves and did not answer within %ss. Unknown — not '
                       'reported as down, and not reported as fine.' % ctx['timeout'],
                'command': 'curl -sSv -m 10 https://%s/' % host})
            out['hostnames'].append(rec)
            continue

        e = EXPECT[kind]
        rec['unknown'] = False
        if kind == 'other':
            # Listed, never judged. See _classify.
            rec['ok'] = None
            rec['unknown'] = True
            rec['verdict'] = ('HTTP %s — not the hub (%s). No expectation encoded, '
                              'so no verdict claimed.' % (p['status'], svc or 'unknown service'))
        elif p['status'] in e['exposed']:
            rec['ok'] = False
            rec['verdict'] = 'EXPOSURE — %s answered %s with no credential' % (host, p['status'])
            ctx['find'](EXPOSURE,
                        '%s answers HTTP %s to an anonymous request' % (host, p['status']),
                        'the public internet',
                        'this hostname is a %s: %s. A 200 means there is no gate '
                        'in front of it at all.' % (kind, e['means']),
                        'curl -si -m 10 https://%s/ | head -20' % host)
        elif p['status'] in e['drift']:
            rec['ok'] = False
            rec['verdict'] = 'drift — expected %s, got %s' % (
                '/'.join(str(x) for x in e['ok']), p['status'])
            ctx['find'](DRIFT,
                        '%s answered %s; a %s hostname should answer %s' % (
                            host, p['status'], kind,
                            ' or '.join(str(x) for x in e['ok'])),
                        'the public edge',
                        e['means'] + '. The gate in front of it is not the one '
                        'this hostname is supposed to have.',
                        'python3 hub/tools/situation.py --json  # group C names the app')
        elif p['status'] in e['ok']:
            rec['ok'] = True
            rec['verdict'] = 'correct — %s is what a %s should answer' % (p['status'], kind)
        else:
            rec['ok'] = None
            rec['verdict'] = 'unrecognised status %s for a %s hostname' % (p['status'], kind)
            ctx['find'](UNKNOWN,
                        '%s answered %s, which this tool has no expectation for' % (
                            host, p['status']),
                        'the public edge',
                        'not classified as correct OR wrong. Unrecognised is not '
                        'the same as fine, and it is not being counted as fine.',
                        'curl -si -m 10 https://%s/ | head -20' % host)
        out['hostnames'].append(rec)

    if not out['complete']:
        ctx['blind'].append({
            'check': 'the full hostname list (A)',
            'why': 'without the tunnel ingress from the Cloudflare API, only the '
                   'hostnames this box wrote down are known. A hostname added to '
                   'the tunnel by hand would be invisible here.',
            'command': 'python3 hub/tools/cf-check.py --zone <zone>   # then re-run'})
    return out


# ── B. EXPOSURE ─────────────────────────────────────────────────────────────

# 20404827  _hub_env — the HUB PROCESS's environment, not this shell's
def _hub_env(ctx):
    """THIS FUNCTION EXISTS BECAUSE THE FIRST VERSION OF THIS TOOL LIED.

    It read os.environ and reported "HUB_CF_TRUST_IP (unset) — CF doors off".
    The hub process on that same box had HUB_CF_TRUST_IP=127.0.0.1. Both
    statements were about "this machine" and only one was about the hub: an ssh
    shell does not inherit a systemd unit's or a nohup'd process's environment.
    A posture report that reads the wrong environment is worse than no posture
    report, because it is confidently wrong about whether a door is open.

    So: find the hub process, read ITS environ. /proc only, which means Linux
    only, which means the operator's Windows PC gets 'unknown' — correctly,
    since there is no hub there to have an environment.

    Several server.py processes can be running at once (there were three on
    ksgcohub: the real one plus two throwaway rigs on other ports), so the
    candidate is chosen by the port it was told to serve.
    """
    out = {'known': False, 'env': {}, 'pid': None, 'source': '',
           'why': 'no /proc on this platform' if not os.path.isdir('/proc')
                  else 'no hub process found'}
    if not os.path.isdir('/proc'):
        return out
    cands = []
    try:
        pids = [d for d in os.listdir('/proc') if d.isdigit()]
    except Exception:
        return out
    for pid in pids:
        try:
            with open('/proc/%s/cmdline' % pid, 'rb') as f:
                cmd = f.read().decode('utf-8', 'ignore')
        except Exception:
            continue
        if 'server.py' not in cmd or 'situation' in cmd:
            continue
        try:
            with open('/proc/%s/environ' % pid, 'rb') as f:
                raw = f.read().decode('utf-8', 'ignore')
        except Exception:
            # A hub running as another user. Knowable that it exists, not what
            # it was configured with. That is 'unknown', and it is reported.
            cands.append((pid, None))
            continue
        env = {}
        for item in raw.split('\0'):
            if '=' in item and (item.startswith('HUB_') or item.startswith('CF_')):
                k, v = item.split('=', 1)
                env[k] = v
        cands.append((pid, env))
    for pid, env in cands:
        if env is None:
            continue
        port = int(env.get('HUB_PORT', '8765') or 8765)
        if port == ctx['hub_port']:
            out.update({'known': True, 'env': env, 'pid': int(pid),
                        'source': '/proc/%s/environ — the hub serving port %d'
                                  % (pid, port), 'why': ''})
            return out
    if cands:
        out['why'] = ('found %d server.py process(es) but none whose environment '
                      'could be read and whose HUB_PORT matches %d'
                      % (len(cands), ctx['hub_port']))
    return out


# 20404817  posture — the four facts that decide whether any gate is real
def posture(ctx):
    """Declared and enforced are different words and the difference is the
    whole of this function.

    Most routes carry a gate -- run edges.py for the count, because an
    instrument printing a hand-typed one is the defect it exists to remove.
    HUB_ENFORCE_GATES defaults to OFF, so the
    router records what it WOULD have denied and then calls the handler
    anyway. On top of that, gate_check returns True whenever TOTP is
    unconfigured, so gates 2 and 3 pass even after gate 1 starts being
    enforced. Either one alone makes the route table decorative.

    Reported as NOT ENFORCED, never as present.
    """
    p = {}
    he = ctx['hub_env']
    p['env_source'] = {'known': he['known'], 'source': he['source'] or None,
                       'why': he['why'] or None}
    if ctx['target_local'] and he['known']:
        env = he['env']
        raw = env.get('HUB_ENFORCE_GATES', '')
        p['enforce_gates'] = {
            'known': True,
            'enforced': raw.lower() not in ('0', 'false', ''),
            'raw': raw or '(unset)',
            'note': 'unset is the default, and the default is OFF'}
        p['cf_role'] = {'known': True, 'value': env.get('HUB_CF_ROLE', 'admin'),
                        'note': 'the role handed to anyone the Cloudflare doors let in'}
        p['cf_trust_ip'] = {
            'known': True, 'value': env.get('HUB_CF_TRUST_IP', '') or None,
            'note': 'the ONLY source address whose Cf-Access-* headers are '
                    'believed. Empty disables both Cloudflare doors entirely.'}
        p['cf_emails'] = {
            'known': True,
            'count': len([e for e in env.get('HUB_CF_EMAILS', '').split(',') if e.strip()]),
            'note': 'an empty list means any email Access approved is accepted'}
    else:
        for k in ('enforce_gates', 'cf_role', 'cf_trust_ip', 'cf_emails'):
            p[k] = {'known': False,
                    'note': 'the HUB PROCESS\'s environment could not be read. This '
                            'shell\'s environment is a different thing and is not '
                            'being substituted for it.'}
        ctx['blind'].append({
            'check': 'HUB_ENFORCE_GATES, HUB_CF_ROLE, HUB_CF_TRUST_IP, HUB_CF_EMAILS (B)',
            'why': ('the hub under test is at %s, not on this machine' % ctx['hub'])
                   if not ctx['target_local'] else
                   ('the hub process environment was not readable: %s. An ssh '
                    'shell does not inherit a service\'s environment, so reading '
                    'this shell instead would report the wrong posture under the '
                    'hub\'s name.' % he['why']),
            'command': 'sudo tr \'\\0\' \'\\n\' < /proc/$(pgrep -f server.py|head -1)/environ | grep ^HUB_'})

    p['totp'] = _totp_configured(ctx['db_path']) if ctx['target_local'] else {
        'known': False, 'configured': None,
        'why': 'the hub database belongs to the target box, not this one'}
    if not p['totp']['known'] and not ctx['target_local']:
        ctx['blind'].append({
            'check': 'whether TOTP is configured (B)',
            'why': 'gate_check() returns True when totp_secret is unset, so this '
                   'row decides whether gates 2 and 3 exist at all — and it is on '
                   'the target box.',
            'command': 'ssh <the target> "sqlite3 -readonly ~/hub/db/server.db '
                       '\\"select length(value)>0 from hub_config where key=\'totp_secret\'\\""'})
    elif not p['totp']['known']:
        ctx['blind'].append({
            'check': 'whether TOTP is configured (B)',
            'why': p['totp']['why'],
            'command': 'ls -l %s' % (ctx['db_path'] or '<hub db>')})

    p['bind'] = _bind() if ctx['target_local'] else {
        'known': False, 'addr': None,
        'why': 'read from the target\'s source, which is not this machine'}

    p['svctoken_file'] = _svctoken_presence(ctx)

    # The findings. Each one is a fact about the posture, not about a probe,
    # and they are worth stating even when nothing answered — a hub nobody can
    # reach still has no gates on.
    ef = p['enforce_gates']
    if ef.get('known') and not ef['enforced']:
        ctx['find'](DRIFT,
                    'HUB_ENFORCE_GATES is off — every declared gate is SHADOW ONLY',
                    'the hub process on this box',
                    'kernel/router.py records what it would have denied and then '
                    'runs the handler anyway. So "gate 1" and "gate 2" in the '
                    'route table describe an intention, not a control. The only '
                    'things actually keeping the hub off the internet are '
                    '_splash_only and Cloudflare Access.',
                    'python3 -c "from kernel import router; print(router.ENFORCE_GATES, len(router.shadow_report()))"')
    if p['totp'].get('known') and p['totp']['configured'] is False:
        ctx['find'](DRIFT,
                    'TOTP is not configured, so gate_check() returns True for every level',
                    'kernel/auth.py gate_check',
                    'gates 2 and 3 — /api/vault, /api/bank, /api/run, '
                    '/api/docker/prune — pass unconditionally. Turning '
                    'HUB_ENFORCE_GATES on would NOT close them: it closes gate 1 '
                    'only. This is the second lock and it is not fitted.',
                    'curl -s localhost:%s/api/totp/status' % ctx['hub_port'])
    b = p['bind']
    if b.get('known') and b.get('addr') in ('0.0.0.0', '::'):
        ctx['find'](EXPOSURE if ctx['lan_open'] else DRIFT,
                    'the hub binds %s and there is no setting to narrow it' % b['addr'],
                    'every interface on the box — loopback, LAN, tailnet',
                    'server.py hardcodes the bind address, so "listen on '
                    'loopback only and let cloudflared reach it there" is not '
                    'reachable from configuration. Combined with gates in shadow '
                    'mode, anything that can route to this box can read the hub.',
                    'ss -ltnp | grep %s' % ctx['hub_port'])
    tip = p.get('cf_trust_ip') or {}
    if tip.get('known') and tip.get('value') in LOCAL_HOSTS:
        ctx['find'](DRIFT,
                    'HUB_CF_TRUST_IP is %s — any process on this box can forge an '
                    'Access identity' % tip['value'],
                    'the loopback interface',
                    'the Cloudflare doors trust Cf-Access-Authenticated-User-Email '
                    'and Cf-Access-Jwt-Assertion from this address. That is correct '
                    'when cloudflared is the only thing on loopback, and it is also '
                    'the widest form of that trust: the path is the entire proof, so '
                    'anything local inherits it.',
                    'ss -ltnp | grep %s   # who else is on loopback' % ctx['hub_port'])
    return p


# 20404818  _svctoken_presence — stat'ed, never opened
def _svctoken_presence(ctx):
    """Whether the lobby holds a credential, and whether the file mode still
    protects it. The file is NOT read. svctoken.py refuses a widened file on
    read for the same reason ssh refuses a group-readable key; this reports the
    mode so a widened file is visible before something needs it."""
    if not ctx['target_local']:
        return {'known': False, 'why': 'on the target box, not this one'}
    path = os.environ.get('HUB_SVCTOKEN_FILE',
                          os.path.expanduser('~/.flare/svctoken.json'))
    try:
        st = os.stat(path)
    except Exception:
        return {'known': True, 'present': False, 'mode': None,
                'note': 'no service token on this box — the lobby cannot reach any '
                        'node, and a drill-in will read as the node being down'}
    mode = oct(st.st_mode & 0o777)
    if (st.st_mode & 0o077) != 0:
        ctx['find'](EXPOSURE,
                    'the Cloudflare Access service token file is mode %s' % mode,
                    path,
                    'that credential opens EVERY node in the fleet '
                    '(any_valid_service_token). Anything readable beyond its owner '
                    'is a fleet-wide key with a group on it.',
                    'chmod 600 %s' % path)
    return {'known': True, 'present': True, 'mode': mode,
            'note': 'presence and mode only — the file was not opened'}


# 20404819  exposure — what answers with no credential, per trust zone
def exposure(ctx):
    """THE GROUP THAT MATTERS MOST, and the reason it is split by zone.

    loopback, LAN, tailnet and the public edge are four different trust zones
    and a single "is it exposed" answer flattens them into nonsense. The hub
    answering /api/config on loopback is expected. The same answer on the LAN
    address means every device on the home network reads it. The same answer
    from the public hostname is the four-minute incident that actually happened.

    No credential is presented on any of these. So a 200 here is proof of an
    open door. A 401 is proof only that THIS caller was refused — it is not
    proof the door works for whoever is supposed to come through it, and that
    distinction is written into every record.
    """
    gates, gsrc = ctx['gates'], ctx['gates_source']
    out = {'gate_source': gsrc, 'zones': [], 'paths': []}

    zones = []
    # NAME THE ZONE BY WHAT IT ACTUALLY IS. --hub pointed at a tailnet address
    # was being labelled "loopback — the box itself", which understates it
    # twice: it is a network hop, and an unauthenticated 200 across a network is
    # an exposure rather than the expected local behaviour. A zone with the
    # wrong name gets the wrong severity, and the severity is what gets acted on.
    if ctx['target_local']:
        zones.append({'zone': 'loopback', 'base': ctx['hub'],
                      'trust': 'the box itself. The hub is meant to answer here.',
                      'severity_if_open': DRIFT})
    else:
        zones.append({'zone': 'direct:' + ctx['hub'].split('//')[-1],
                      'base': ctx['hub'],
                      'trust': 'whatever network can route to that address — a '
                               'tailnet or a LAN. Not loopback, and not nothing.',
                      'severity_if_open': EXPOSURE})
    if ctx['lan_ip'] and ctx['target_local']:
        zones.append({'zone': 'lan', 'base': 'http://%s:%s' % (ctx['lan_ip'], ctx['hub_port']),
                      'trust': 'every device on the local network. No credential '
                               'is required to be on it.',
                      'severity_if_open': EXPOSURE})
    elif ctx['target_local']:
        ctx['blind'].append({
            'check': 'the LAN trust zone (B)',
            'why': 'no routable address could be derived for this box, so the LAN '
                   'zone was not probed. It is not known to be closed.',
            'command': 'ip -4 addr show | grep inet'})
    # THE APEX IS ITS OWN TRUST ZONE and it is the one that has actually leaked.
    # It is public by design, so nothing at the edge stops these paths — only
    # router._splash_only does, and it is one function. Probing it is the only
    # way to know that function is still in the request path.
    probe_public = list(ctx['public_hosts'])
    for h in ctx['splash_hosts']:
        if h not in probe_public:
            probe_public.append(h)
    for h in probe_public:
        splashy = h in ctx['splash_hosts']
        zones.append({'zone': 'public:' + h, 'base': 'https://' + h,
                      'splash': splashy,
                      'trust': ('the open internet. PUBLIC BY DESIGN — no Access in '
                                'front of it, so router._splash_only is the only '
                                'thing making these 404.' if splashy else
                                'the open internet, through Cloudflare.'),
                      'severity_if_open': EXPOSURE})
    if not probe_public:
        ctx['blind'].append({
            'check': 'the public trust zone (B)',
            'why': 'no public hostname for this node could be derived, so nothing '
                   'was probed from outside. The most important zone is the one '
                   'that was not tested.',
            'command': 'python3 hub/tools/situation.py --public <hostname>'})

    for z in zones:
        zrec = dict(z)
        zrec['probes'] = []
        reached_any = False
        splashy = z.get('splash')
        # On a splash host the interesting paths are not only the six watched
        # ones: they are every path _splash_only deliberately lets through.
        paths = list(WATCHED)
        if splashy:
            for extra in ctx['behind_login']:
                if extra not in paths:
                    paths.append(extra)
        for path in paths:
            gate = gates.get(path)
            p = _probe(z['base'] + path, ctx['timeout'])
            reached_any = reached_any or p['reached']
            rec = {'path': path, 'url': z['base'] + path,
                   'declared_gate': gate,
                   'enforced': bool(ctx['posture']['enforce_gates'].get('enforced'))
                               if ctx['posture']['enforce_gates'].get('known') else None,
                   'reached': p['reached'], 'status': p['status'],
                   'error': p['error'], 'ok': None, 'unknown': not p['reached']}
            # `open` is its own field rather than inferred from the status,
            # because "200 on a gate-0 path" is open too when that path is one
            # _splash_only let through onto a public hostname. Inferring it from
            # the gate level alone printed /fleet as unclassified while the
            # finding beneath it called the same thing an exposure.
            rec['open'] = bool(
                p['status'] == 200 and ((gate or 0) >= 1 or
                                        (splashy and path in ctx['behind_login'])))
            if not p['reached']:
                rec['meaning'] = 'no answer — unknown, not closed'
            elif p['status'] == 200:
                rec['ok'] = False if rec['open'] else None
                rec['meaning'] = ('OPEN: served content to a request carrying no '
                                  'session, no gate token and no Access header')
            elif p['status'] in (401, 403):
                rec['ok'] = True
                rec['meaning'] = ('refused THIS caller. Not proof the path works '
                                  'for a caller who is allowed through')
            elif p['status'] in (301, 302, 303, 307, 308):
                rec['ok'] = True
                rec['meaning'] = 'redirected, almost certainly to an Access login'
            elif p['status'] == 404:
                rec['ok'] = True
                rec['meaning'] = ('not found. On a splash host this is _splash_only '
                                  'hiding the route on purpose — 404 rather than 403 '
                                  'so the reply does not confirm the route exists')
            else:
                rec['meaning'] = 'HTTP %s — no expectation encoded' % p['status']
            zrec['probes'].append(rec)

            # THE SPLASH-HOST HOLE, reported on its own terms. A 200 here is
            # not "a gate failed" — no gate was ever in the request path. The
            # code let it through on the assumption that Access covers this
            # hostname AND this path, and that assumption is what is false.
            if splashy and p['status'] == 200 and path in ctx['behind_login']:
                covering = ctx['covering_app'](z['base'].split('//')[-1], path)
                ctx['find'](EXPOSURE,
                            'https://%s%s answers 200 to the open internet'
                            % (z['base'].split('//')[-1], path),
                            'the public internet, no credential of any kind',
                            'this path is in router.SPLASH_BEHIND_LOGIN, so '
                            '_splash_only lets it through on a splash host rather '
                            'than 404ing it. The comment beside that list says why: '
                            '"Cloudflare Access is scoped to these paths". On THIS '
                            'hostname %s — and gate enforcement is off behind it, so '
                            'nothing else stops it either. The apex hostname is not '
                            'the same hostname as its www alias, and an Access app '
                            'on one does not cover the other.'
                            % ('it is not known whether an Access app covers it — '
                               'group C could not be read' if covering == 'unknown'
                               else 'no Access app covers it' if not covering
                               else 'the covering app is %s, which did not stop this'
                                    % covering),
                            'curl -si -m 8 https://%s%s | head -15'
                            % (z['base'].split('//')[-1], path))
            elif p['status'] == 200 and gate and gate >= 1:
                sev = z['severity_if_open']
                ctx['find'](sev,
                            '%s returns 200 with no credential (declared gate %d, '
                            'NOT ENFORCED)' % (path, gate),
                            '%s — %s' % (z['zone'], z['trust']),
                            ('gate %d is what the route table asks for. What is '
                             'actually in front of this path here is nothing. ' % gate) +
                            ('/api/vault is the pointer store and /api/config is the '
                             'hub configuration; both are gate 2 or 1 and both answer.'
                             if path in ('/api/vault', '/api/config') else
                             'It answers to anyone who can route to this address.'),
                            'curl -si -m 6 %s | head -5' % (z['base'] + path))

        if not reached_any:
            zrec['reached'] = False
            ctx['blind'].append({
                'check': 'the %s zone (B) — none of the %d paths answered' % (
                    z['zone'], len(WATCHED)),
                'why': 'nothing on %s replied. UNKNOWN: this is not evidence the '
                       'paths are closed, and not evidence the hub is down.' % z['base'],
                'command': 'curl -sSv -m 6 %s/api/status' % z['base']})
        else:
            zrec['reached'] = True
        out['zones'].append(zrec)

    for path in WATCHED:
        out['paths'].append({
            'path': path, 'declared_gate': gates.get(path),
            'gate_known': path in gates,
            'note': None if path in gates else
                    'this path is not in the route table as parsed — either it '
                    'has moved or the parse missed it'})
    return out


# ── C. THE ENTRY CHAIN ──────────────────────────────────────────────────────

# 20404820  entry_chain — one domain, one login, and every gate on the way in
def entry_chain(ctx):
    """The chain is: the public login space on the apex, then /fleet, then
    /s/<id>/ into a server, then the flareshub-<id> node endpoint the lobby
    reaches with a service token. Four links, and each one is a separate
    Cloudflare Access application.

    WHAT THIS IS LOOKING FOR, specifically. An Access app with ZERO policies
    denies everyone — the hostname 302s to a sign-in that can never succeed,
    which presents as "the login is broken" and not as "there is no rule". On
    this account app 0f070dc3 sat with "policies": [] from the day it was
    created, because enrolment printed a warning instead of attaching one.
    A warning is not a step. So this counts them and says so loudly.

    It also reports WHAT KIND each policy is. identity (allow:email) on a node
    endpoint is backwards — spec rule 6 says node endpoints refuse humans
    entirely — and service-token on the human login space would lock the
    operator out. Counting policies without reading their kind would call both
    of those fine.
    """
    out = {'known': False, 'why': '', 'zone': ctx['zone'], 'apps': [],
           'links': [], 'apex': None, 'account_id': None}
    if not ctx['cf_token']:
        out['why'] = 'no Cloudflare API token on this machine'
        ctx['blind'].append({
            'check': 'the entire entry chain (C)',
            'why': 'group C is read from the Cloudflare API, not from the edge. '
                   'With no token, which app covers which hostname and how many '
                   'policies it has are UNKNOWN. A hostname that answers 401 at '
                   'the edge tells you an app exists; it cannot tell you the app '
                   'has a policy that anyone can satisfy.',
            'command': 'CF_API_TOKEN=... python3 hub/tools/situation.py   '
                       '# or write ~/.cf-token 0600'})
        return out
    if not ctx['zone']:
        out['why'] = 'no zone known — this box has never enrolled and none was given'
        ctx['blind'].append({
            'check': 'the entry chain (C)',
            'why': 'the zone comes from ~/.flare/node.json, and there is none here.',
            'command': 'python3 hub/tools/situation.py --zone flarevault.dev'})
        return out

    body, why = _cf(ctx['cf_token'], '/zones?name=' + ctx['zone'], ctx['timeout'] * 2)
    res = (body or {}).get('result') or []
    if not res:
        out['why'] = why or 'zone %s is not visible to this token' % ctx['zone']
        ctx['blind'].append({
            'check': 'the entry chain (C)',
            'why': 'the zone lookup failed: %s' % out['why'],
            'command': 'python3 hub/tools/cf-check.py --zone %s' % ctx['zone']})
        return out
    acct = ((res[0].get('account') or {}).get('id')) or ''
    out['account_id'] = acct[:8] + '…' if acct else None
    if not acct:
        out['why'] = 'the zone is visible but its account id was not returned'
        ctx['blind'].append({
            'check': 'Access apps (C)',
            'why': out['why'] + ' — Access apps are an ACCOUNT-level read and the '
                                'token may be zone-scoped only.',
            'command': 'python3 hub/tools/cf-check.py --zone %s' % ctx['zone']})
        return out

    body, why = _cf(ctx['cf_token'], '/accounts/%s/access/apps' % acct, ctx['timeout'] * 2)
    apps = (body or {}).get('result')
    if apps is None:
        out['why'] = why or 'Access apps could not be listed'
        ctx['blind'].append({
            'check': 'Access apps (C)',
            'why': out['why'],
            'command': 'python3 hub/tools/cf-check.py --zone %s' % ctx['zone']})
        return out

    out['known'] = True
    for a in apps:
        dom = (a.get('domain') or '').lower()
        if ctx['zone'] not in dom:
            continue        # other zones on the same account are not this chain
        pol, pwhy = _cf(ctx['cf_token'],
                        '/accounts/%s/access/apps/%s/policies' % (acct, a['id']),
                        ctx['timeout'] * 2)
        plist = (pol or {}).get('result')
        rec = {'domain': dom, 'type': a.get('type'), 'app_id': (a.get('id') or '')[:8],
               'policies_known': plist is not None,
               'policies': None if plist is None else len(plist),
               'kinds': [], 'identity': False, 'service_token': False}
        if plist is None:
            rec['why'] = pwhy or 'policies could not be read'
            ctx['blind'].append({
                'check': 'policies on the Access app for %s (C)' % dom,
                'why': rec['why'] + ' — an app whose policies cannot be read might '
                                    'have none, which denies everyone.',
                'command': 'the token needs Access: Apps and Policies -> Read'})
        else:
            for p in plist:
                keys = set()
                for inc in (p.get('include') or []):
                    keys |= set(inc.keys())
                rec['kinds'].append({'name': p.get('name'),
                                     'decision': p.get('decision'),
                                     'include': sorted(keys)})
                if 'any_valid_service_token' in keys or 'service_token' in keys:
                    rec['service_token'] = True
                elif keys:
                    rec['identity'] = True
            if len(plist) == 0:
                ctx['find'](BROKEN,
                            'the Access app for %s has ZERO policies' % dom,
                            'Cloudflare Access, app %s' % rec['app_id'],
                            'an app with no policy DENIES EVERYONE. The hostname '
                            'still 302s to a sign-in, and that sign-in can never '
                            'succeed, so this presents as a broken login rather '
                            'than as a missing rule. It has already happened on '
                            'this account.',
                            'Zero Trust > Access > Applications > %s > Policies' % dom)
        out['apps'].append(rec)

    # Published for exposure() BEFORE any judgement is made, so that a 200 on a
    # public hostname can name the app that was supposed to cover it. Set here
    # and nowhere else: two copies of the app list is two answers to the same
    # question.
    ctx['entry_apps'] = [r['domain'] for r in out['apps']]
    ctx['apps_known'] = True

    # The four links, each matched to the app that actually covers it. A link
    # with no app is the finding that matters most here: nothing in front of a
    # path that reaches this origin.
    # THE APEX IS NOT LIKE THE OTHER LINKS, and the first version of this tool
    # got it wrong by treating it the same. flarevault.dev has NO Access app of
    # its own and must not have one: it is the public login space, a public page
    # cannot sit behind a login, and enroll's own reasoning says so. What guards
    # it is (1) router._splash_only, one function, and (2) PATH-scoped Access
    # apps on /api, /fleet, /s and /flareshub.
    #
    # So the question is not "is there an app on the apex" — the answer to that
    # is correctly no. The question is whether the paths that must not be public
    # on it are each covered. A missing app on <zone>/api is the exact shape of
    # the four-minute incident, and reporting "no app covers the apex" as the
    # finding would have buried it.
    apex = ctx['zone']
    apex_is_splash = apex in ctx['splash_hosts']
    api_app = next((r for r in out['apps'] if r['domain'] in (apex + '/api', apex + '/api/')), None)
    out['apex'] = {
        'hostname': apex, 'declared_public_by_code': apex_is_splash,
        'splash_source': ctx['splash_source'],
        'api_path_app': api_app['domain'] if api_app else None,
        'api_path_policies': api_app['policies'] if api_app else None,
        'ok': bool(apex_is_splash and api_app),
        'means': 'public by design; guarded by router._splash_only plus path-scoped '
                 'Access apps, never by an app on the apex itself'}
    if not apex_is_splash:
        ctx['find'](EXPOSURE,
                    '%s reaches this origin but the code does not list it as a splash host'
                    % apex,
                    'router.SPLASH_HOSTS (%s)' % ctx['splash_source'],
                    'router._splash_only only 404s the API for hostnames it knows '
                    'about. A hostname pointed at this origin and NOT on that list '
                    'gets the whole API. That is precisely what happened for four '
                    'minutes when a second hostname was added without an Access app.',
                    'HUB_SPLASH_HOSTS=... or check hub/kernel/router.py SPLASH_HOSTS')
    elif not api_app:
        ctx['find'](DRIFT,
                    'no Access app covers %s/api — the only guard there is _splash_only'
                    % apex,
                    'Cloudflare Access, zone %s' % apex,
                    'one function in one file is the entire defence for the hub API '
                    'on a hostname that is public on purpose. It works today. It is '
                    'also a single point of failure with no second layer, on the one '
                    'hostname that has already leaked.',
                    'Zero Trust > Access > Applications — one app for %s/api' % apex)

    node_hosts = [h.lower() for h in ctx['public_hosts'] if h.lower().startswith('flareshub-')]
    links = [
        ('/fleet', ctx['zone'] + '/fleet', 'identity',
         'the lobby page. Gate 0 in the route table on purpose — Access is the control here.'),
        ('/s/<id>/', ctx['zone'] + '/s', 'identity',
         'the route INTO a server. Same person, one door further in.'),
    ] + [('node endpoint', h, 'service_token',
          'spec rule 6: node endpoints refuse humans entirely. The lobby reaches '
          'them with a service token.') for h in node_hosts]

    for name, want_dom, want_kind, why_matters in links:
        match = None
        for rec in out['apps']:
            d = rec['domain']
            if d == want_dom or want_dom.startswith(d.rstrip('/')) and d.count('/'):
                match = rec if (match is None or len(d) > len(match['domain'])) else match
            if d == want_dom:
                match = rec
                break
        link = {'link': name, 'expects': want_dom, 'wants': want_kind,
                'why_matters': why_matters,
                'app': match['domain'] if match else None,
                'policies': match['policies'] if match else None,
                'kind': ('service-token' if match and match['service_token']
                         else 'identity' if match and match['identity']
                         else None),
                'ok': None}
        if match is None:
            link['ok'] = False
            ctx['find'](EXPOSURE,
                        'no Cloudflare Access app covers %s (%s)' % (want_dom, name),
                        'Cloudflare Access for zone %s' % ctx['zone'],
                        why_matters + ' With no app, whatever the origin serves at '
                        'that address is served to the open internet, and the only '
                        'thing left in front of it is router._splash_only.',
                        'Zero Trust > Access > Applications — add an app for %s' % want_dom)
        elif match['policies'] == 0:
            link['ok'] = False   # already reported above as BROKEN
        elif want_kind == 'service_token' and match['identity']:
            link['ok'] = False
            ctx['find'](EXPOSURE,
                        '%s is covered by an IDENTITY policy, not a service token' % want_dom,
                        'Cloudflare Access, app %s' % match['app_id'],
                        'a node endpoint with a human policy is a human-facing door '
                        'on a hostname that is specified to refuse humans. It also '
                        'means a second login for the same person, which is the '
                        'thing the entry chain exists to remove.',
                        'Zero Trust > Access > Applications > %s > Policies' % want_dom)
        elif want_kind == 'identity' and match['service_token'] and not match['identity']:
            link['ok'] = False
            ctx['find'](BROKEN,
                        '%s is service-token only, so no person can reach it' % want_dom,
                        'Cloudflare Access, app %s' % match['app_id'],
                        why_matters + ' A service-token-only policy on a human link '
                        'locks the operator out of their own fleet.',
                        'Zero Trust > Access > Applications > %s > Policies' % want_dom)
        else:
            link['ok'] = True
        out['links'].append(link)

    if not node_hosts:
        ctx['blind'].append({
            'check': 'node endpoints in the entry chain (C)',
            'why': 'no flareshub-<id> hostname was derived, so no node endpoint '
                   'was matched to an Access app. The nodes are not known to be '
                   'covered; they are not known at all.',
            'command': 'cat ~/.flare/node.json   # or --public flareshub-<id>.<zone>'})
    return out


# ── the distinction the whole tool exists for ───────────────────────────────

# 20404821  perspective — is the thing broken, or can I just not see it?
def perspective(ctx):
    """"ksgcohub is down" was the operator's Tailscale.

    The only way to tell a broken target from a broken viewer is to reach the
    target by MORE THAN ONE PATH and compare. Nothing else in this file can do
    it; every other check sees one path and cannot know what it is looking at.

    The reasoning, stated so it can be argued with:

      public answers, tailnet does not  -> the node is serving. YOUR path is
                                           broken. Do not touch the node.
      tailnet answers, public does not  -> the node is up; the edge, the tunnel
                                           or DNS is the fault.
      neither answers                   -> UNKNOWN. Genuinely. This is the case
                                           where a tool must refuse to guess,
                                           because both guesses have been made
                                           before and both were wrong.
      no second path available          -> also unknown, and said out loud, so
                                           a single failed probe never gets
                                           read as a verdict.
    """
    v = {'paths': [], 'conclusion': 'unknown',
         'line': 'not enough vantage points to say', 'tailscale': ctx['tailscale']}

    for label, url in ctx['vantage_urls']:
        p = _probe(url, ctx['timeout'])
        v['paths'].append({'path': label, 'url': url, 'reached': p['reached'],
                           'status': p['status'], 'error': p['error']})

    ts = ctx['tailscale']
    if ts.get('known') and ts.get('state') not in (None, 'Running'):
        ctx['find'](BROKEN,
                    'the Tailscale daemon on THIS machine is in %s' % ts['state'],
                    'this machine, not the target',
                    'a GUI saying "connected" is not evidence and has been wrong '
                    'here before. In this state nothing on the tailnet is '
                    'reachable from here, so every tailnet probe below is about '
                    'this machine and not about the target.',
                    'tailscale status')
    elif not ts.get('known'):
        ctx['blind'].append({
            'check': 'the Tailscale daemon state',
            'why': ts.get('why') or 'could not be determined',
            'command': 'tailscale status --json'})

    pub = [p for p in v['paths'] if p['path'].startswith('public')]
    priv = [p for p in v['paths'] if not p['path'].startswith('public')]
    pub_ok = any(p['reached'] for p in pub)
    priv_ok = any(p['reached'] for p in priv)

    if pub and priv:
        if pub_ok and not priv_ok:
            v['conclusion'] = 'target_serving_viewer_blind'
            v['line'] = ('the target IS serving — the public edge answered. The '
                         'tailnet/LAN path from THIS machine did not. Fix the path, '
                         'not the node.')
        elif priv_ok and not pub_ok:
            v['conclusion'] = 'origin_up_edge_down'
            v['line'] = ('the origin is up and answering on the private path. The '
                         'public edge is not — so the tunnel, DNS or Access is '
                         'the fault, and the hub is not.')
        elif pub_ok and priv_ok:
            v['conclusion'] = 'reachable_both_ways'
            v['line'] = 'reachable by both a public and a private path.'
        else:
            v['conclusion'] = 'cannot_say'
            v['line'] = ('NOTHING answered on any path. This is the case where '
                         'guessing has cost whole evenings: it is equally '
                         'consistent with a dead node and with a dead viewer. '
                         'Check this machine\'s own network before touching the node.')
            ctx['blind'].append({
                'check': 'whether the target is up at all',
                'why': 'no path reached it — public and private both failed. '
                       'UNKNOWN, in both directions.',
                'command': 'tailscale status; curl -sv -m 8 https://<public hostname>/'})
    elif pub_ok or priv_ok:
        v['conclusion'] = 'one_path_only'
        v['line'] = ('reached by one path only, and there was no second path to '
                     'compare against — so this cannot distinguish a broken '
                     'target from a broken viewer.')
        ctx['blind'].append({
            'check': 'the broken-target vs broken-viewer distinction',
            'why': 'only one vantage point was available. The comparison that '
                   'answers this question needs two.',
            'command': 'python3 hub/tools/situation.py --hub http://<tailnet ip>:8765 '
                       '--public <hostname>'})
    else:
        ctx['blind'].append({
            'check': 'the broken-target vs broken-viewer distinction',
            'why': 'no vantage point reached the target at all.',
            'command': 'tailscale status'})
    return v


# ── context, verdict, output ────────────────────────────────────────────────

# 20404822  _ingress — the hostnames Cloudflare will actually route here
def _ingress(ctx):
    """The tunnel's own configuration, which is the only authoritative list of
    what arrives at this origin. A hostname on this list with no Access app is
    the shape of the four-minute incident: a second hostname was pointed at the
    origin without a gate, and https://<that host>/api/config answered."""
    out = {'known': False, 'entries': [], 'why': '', 'tunnel': None}
    tid = ctx['node_json'].get('tunnel_id') or ''
    if not ctx['cf_token'] or not tid or not ctx['zone']:
        out['why'] = ('no Cloudflare token' if not ctx['cf_token'] else
                      'no tunnel id in node.json' if not tid else 'no zone')
        ctx['blind'].append({
            'check': 'the tunnel ingress — which hostnames reach this origin (A)',
            'why': out['why'] + '. Without it, a hostname pointed at this box by '
                                'hand is invisible to this tool.',
            'command': 'cat ~/.flare/node.json; python3 hub/tools/cf-check.py --zone <zone>'})
        return out
    z, why = _cf(ctx['cf_token'], '/zones?name=' + ctx['zone'], ctx['timeout'] * 2)
    res = (z or {}).get('result') or []
    if not res:
        out['why'] = why or 'zone not visible'
        return out
    acct = ((res[0].get('account') or {}).get('id')) or ''
    body, why = _cf(ctx['cf_token'],
                    '/accounts/%s/cfd_tunnel/%s/configurations' % (acct, tid),
                    ctx['timeout'] * 2)
    if body is None:
        out['why'] = why
        ctx['blind'].append({
            'check': 'the tunnel ingress (A)',
            'why': why + ' — the token likely lacks Cloudflare Tunnel -> Read, '
                         'which is an ACCOUNT-level permission a zone-scoped '
                         'token cannot hold.',
            'command': 'python3 hub/tools/cf-check.py --zone %s' % ctx['zone']})
        return out
    ing = (((body or {}).get('result') or {}).get('config') or {}).get('ingress') or []
    out['known'] = True
    out['entries'] = [{'hostname': e.get('hostname') or '',
                       'service': e.get('service') or ''} for e in ing]
    t, _ = _cf(ctx['cf_token'], '/accounts/%s/cfd_tunnel/%s' % (acct, tid),
               ctx['timeout'] * 2)
    tr = (t or {}).get('result') or {}
    if tr:
        out['tunnel'] = {'name': tr.get('name'), 'status': tr.get('status'),
                         'connections': len(tr.get('connections') or [])}
        if tr.get('status') not in ('healthy', None):
            ctx['find'](BROKEN if tr.get('status') == 'down' else DRIFT,
                        'the tunnel %s reports status "%s"' % (tr.get('name'), tr.get('status')),
                        'Cloudflare, the tunnel serving this origin',
                        'every public hostname on this box arrives through this '
                        'tunnel. "degraded" usually means fewer connections than '
                        'Cloudflare wants — it is serving, with less headroom than '
                        'it should have, and a single connection means one failure '
                        'from an outage.',
                        'systemctl status cloudflared; journalctl -u cloudflared -n 40')
    return out


# 20404823  _context — one gathering pass, so every group sees the same facts
def _context(argv):
    """Gathered once and shared. Two groups computing the same fact separately
    is how a report contradicts itself, and a self-contradicting report is
    indistinguishable from a wrong one."""
    def opt(name, default=None):
        if name in argv:
            i = argv.index(name)
            if i + 1 < len(argv):
                return argv[i + 1]
        return default

    ctx = {}
    ctx['json'] = '--json' in argv
    ctx['timeout'] = int(opt('--timeout', '8'))
    ctx['hub'] = (opt('--hub') or os.environ.get('HUB_URL')
                  or 'http://127.0.0.1:8765').rstrip('/')
    host = ctx['hub'].split('//', 1)[-1].split('/')[0].split(':')[0]
    ctx['target_local'] = host in LOCAL_HOSTS
    try:
        ctx['hub_port'] = int(ctx['hub'].rsplit(':', 1)[1].split('/')[0])
    except Exception:
        ctx['hub_port'] = 8765

    ctx['findings'] = []
    ctx['blind'] = []

    def find(sev, what, where, why, cmd):
        ctx['findings'].append({'severity': sev, 'what': what, 'where': where,
                                'why_it_matters': why, 'command': cmd})
    ctx['find'] = find

    node_file = os.environ.get('HUB_NODE_FILE', os.path.expanduser('~/.flare/node.json'))
    nj = {}
    try:
        with open(node_file, encoding='utf-8') as f:
            raw = json.load(f)
        if isinstance(raw, dict):
            nj = raw
    except Exception:
        pass
    ctx['node_json'] = nj
    ctx['node_file'] = node_file
    # The tunnel id is an identifier and not a credential, but it is also
    # nobody's business in a pasted report, so it is truncated everywhere.
    ctx['tunnel_id_short'] = (nj.get('tunnel_id') or '')[:8] or None

    ctx['zone'] = (opt('--zone') or nj.get('zone')
                   or os.environ.get('FLARE_ZONE') or '').strip().lower()
    ctx['db_path'] = os.environ.get('HUB_DB', os.path.join(ROOT, 'db', 'server.db'))
    ctx['gates'], ctx['gates_source'] = _declared_gates()
    ctx['splash_hosts'], ctx['splash_source'] = _splash_hosts()
    ctx['behind_login'], ctx['behind_login_source'] = _behind_login()
    if not ctx['behind_login']:
        ctx['blind'].append({
            'check': 'the paths _splash_only lets through on a public hostname (B)',
            'why': ctx['behind_login_source'] + '. Those paths are the ones most '
                   'likely to be publicly reachable, so not knowing them means the '
                   'most likely exposure was not looked for.',
            'command': 'grep -A4 SPLASH_BEHIND_LOGIN hub/kernel/router.py'})

    # Filled in by entry_chain(), consulted by exposure(). Kept here rather than
    # passed around so there is exactly one copy of the app list.
    ctx['entry_apps'] = []
    ctx['apps_known'] = False

    def covering_app(host, path):
        """Which Access app, if any, covers this host+path. 'unknown' when group
        C could not be read — which is NOT the same as 'none', and saying 'none'
        there would invent a finding out of a missing token."""
        if not ctx['apps_known']:
            return 'unknown'
        best = ''
        for d in ctx['entry_apps']:
            if d == host:
                return d
            if d.startswith(host + '/') and path.startswith(d[len(host):].rstrip('/')):
                if len(d) > len(best):
                    best = d
        return best
    ctx['covering_app'] = covering_app
    ctx['lan_ip'] = opt('--lan') or (_lan_addr() if ctx['target_local'] else '')

    tok, src = ('', '') if '--no-cf' in argv else _cf_token()
    ctx['cf_token'] = tok
    ctx['cf_token_source'] = src or None

    pub = [p for p in (opt('--public') or '').split(',') if p.strip()]
    if not pub and nj.get('hostname'):
        pub = [nj['hostname']]
    ctx['public_hosts'] = [p.strip().lower() for p in pub]

    # Is DNS working AT ALL from here? Without this, every unresolvable
    # hostname reads as a broken hostname, when the resolver may be the thing
    # that is broken. One control question, asked once.
    ctx['dns_works'] = _dns('cloudflare.com')['resolves']
    if not ctx['dns_works']:
        ctx['blind'].append({
            'check': 'every DNS answer in this report',
            'why': 'this machine could not resolve cloudflare.com, so its resolver '
                   'is suspect. Hostnames reported as not resolving may be fine.',
            'command': 'nslookup cloudflare.com'})

    ctx['tailscale'] = _tailscale()
    ctx['hub_env'] = _hub_env(ctx)

    # Vantage points for perspective(): one private, one public, both optional.
    v = [('private:' + ctx['hub'], ctx['hub'] + '/api/status')]
    if ctx['public_hosts']:
        v.append(('public:' + ctx['public_hosts'][0],
                  'https://%s/' % ctx['public_hosts'][0]))
    ctx['vantage_urls'] = v

    # Probed before posture() needs it: whether the hub answers on a non-loopback
    # address is what turns "binds 0.0.0.0" from a note into an exposure.
    ctx['lan_open'] = False
    if ctx['lan_ip']:
        ctx['lan_open'] = _probe('http://%s:%s/api/status' % (ctx['lan_ip'], ctx['hub_port']),
                                 4)['status'] == 200
    # THE WINDOWS-PC CASE, said out loud. On the operator's PC the repo is
    # present and no hub is running, so the file-derived posture facts below
    # describe the SOURCE and the checked-out config -- not a live service. A
    # reader who does not know that reads "TOTP not configured" as a statement
    # about the server, which it is not.
    ctx['hub_answers'] = _probe(ctx['hub'] + '/api/status', 4)['reached']
    if ctx['target_local'] and not ctx['hub_answers']:
        ctx['blind'].append({
            'check': 'everything in group B that came from files rather than probes',
            'why': 'no hub answered on %s, so the environment, the sqlite config '
                   'and the bind address describe this checkout and this shell -- '
                   'not a running hub. They are real facts about the code; they '
                   'are not observations of a live service, here or anywhere '
                   'else.' % ctx['hub'],
            'command': 'python3 hub/tools/situation.py --hub http://<the node>:8765'})
    ctx['ingress'] = _ingress(ctx)
    return ctx


# 20404824  _verdict — four states, and 'ok' is the hardest one to earn
def _verdict(ctx, groups):
    """Four states, in strict precedence. An exposure outranks a breakage
    because a breakage is visible and an exposure is not.

    'ok' requires that nothing was unseen. A clean report from a tool that
    could not reach anything is the exact failure this whole file is against:
    silence reading as health.
    """
    sev = [f['severity'] for f in ctx['findings']]
    counts = {s: sev.count(s) for s in (EXPOSURE, BROKEN, DRIFT, UNKNOWN)}
    blind = len(ctx['blind'])
    if counts[EXPOSURE]:
        return {'state': 'exposed', 'counts': counts, 'blind': blind,
                'line': '%d thing(s) answer that should not. Start with the '
                        'exposure findings.' % counts[EXPOSURE]}
    if counts[BROKEN]:
        return {'state': 'broken', 'counts': counts, 'blind': blind,
                'line': '%d thing(s) that should answer do not. Nothing appears '
                        'exposed.' % counts[BROKEN]}
    reached = any(h.get('reached') for h in groups['serving']['hostnames']) or \
        any(z.get('reached') for z in groups['exposure']['zones'])
    if not reached or blind:
        return {'state': 'cannot_say', 'counts': counts, 'blind': blind,
                'line': 'nothing found, and %d check(s) could not run. That is not '
                        'a clean bill of health — see WHAT I COULD NOT SEE.' % blind}
    if counts[DRIFT]:
        return {'state': 'drift', 'counts': counts, 'blind': blind,
                'line': '%d place(s) where the declared posture and the real one '
                        'disagree. Nothing exposed, nothing broken.' % counts[DRIFT]}
    return {'state': 'ok', 'counts': counts, 'blind': blind,
            'line': 'everything checked answered as expected, and every check ran.'}


ORDER = {EXPOSURE: 0, BROKEN: 1, DRIFT: 2, UNKNOWN: 3}


# 20404825  _human — the report an operator reads at 1am
def _human(ctx, groups, verdict):
    # ASCII on the way out. Not fussiness: the operator's Windows console is
    # cp1252, and an em-dash there prints as a replacement glyph in the middle
    # of the sentence that explains the finding. A report you cannot read is a
    # report that does not exist. The JSON mode keeps the real characters.
    _FOLD = {0x2014: '--', 0x2013: '-', 0x2018: "'", 0x2019: "'",
             0x201c: '"', 0x201d: '"', 0x00b7: '*', 0x2026: '...'}

    def w(s):
        try:
            sys.stdout.write(s.translate(_FOLD))
        except Exception:
            sys.stdout.write(s.translate(_FOLD).encode(
                'ascii', 'replace').decode('ascii'))
    w('\n  SITUATION — what is serving, and to whom\n')
    w('  %s   hub under test: %s%s\n' % (
        _now(), ctx['hub'], '' if ctx['target_local'] else '  (REMOTE)'))
    w('  read-only. nothing was changed, nothing was restarted.\n\n')

    w('  VERDICT  %s\n' % verdict['state'].upper().replace('_', ' '))
    w('    %s\n\n' % verdict['line'])

    p = groups['perspective']
    w('  WHICH SIDE IS BROKEN\n')
    w('    %s\n' % p['line'])
    for r in p['paths']:
        w('      %-34s %s\n' % (r['path'], 'HTTP %s' % r['status'] if r['reached']
                                else 'no answer (%s)' % (r['error'] or '')))
    ts = p['tailscale']
    if ts.get('known'):
        w('      tailscale (this machine)           BackendState=%s  peers=%s\n'
          % (ts.get('state'), ts.get('peers')))
    else:
        w('      tailscale (this machine)           unknown — %s\n' % ts.get('why'))
    w('\n')

    w('  A. SERVING — is each hostname answering what it SHOULD?\n')
    if not groups['serving']['hostnames']:
        w('    no hostname could be derived. See WHAT I COULD NOT SEE.\n')
    for h in groups['serving']['hostnames']:
        mark = 'ok  ' if h['ok'] else ('BAD ' if h['ok'] is False else '????')
        w('    [%s] %-44s %s\n' % (mark, h['hostname'],
                                   'HTTP %s' % h['status'] if h['reached'] else 'no answer'))
        w('           %s · %s\n' % (h['kind'], h['verdict']))
    if groups['serving']['sources']:
        w('    derived from: %s\n' % ', '.join(groups['serving']['sources']))
    if not groups['serving']['complete']:
        w('    THIS LIST IS INCOMPLETE — the tunnel ingress could not be read.\n')
    w('\n')

    w('  B. EXPOSURE — what answers with NO credential\n')
    po = groups['posture']
    ef = po['enforce_gates']
    w('    HUB_ENFORCE_GATES   %s\n' % (
        ('ON' if ef['enforced'] else 'OFF — every gate below is DECLARED, NOT ENFORCED')
        if ef.get('known') else 'unknown (target is not this machine)'))
    t = po['totp']
    w('    TOTP configured     %s\n' % (
        ('yes' if t['configured'] else
         'NO — gate_check() returns True, so gates 2 and 3 pass for everyone')
        if t.get('known') else 'unknown — %s' % t.get('why')))
    w('    HUB_CF_ROLE         %s\n' % (po['cf_role'].get('value', 'unknown')
                                        if po['cf_role'].get('known') else 'unknown'))
    w('    HUB_CF_TRUST_IP     %s\n' % (po['cf_trust_ip'].get('value') or '(unset — CF doors off)'
                                        if po['cf_trust_ip'].get('known') else 'unknown'))
    b = po['bind']
    w('    hub binds to        %s\n' % (
        '%s%s' % (b['addr'], '' if b.get('configurable') else '  (hardcoded — no setting narrows it)')
        if b.get('known') else 'unknown — %s' % b.get('why')))
    sv = po['svctoken_file']
    w('    service token file  %s\n' % (
        ('present, mode %s' % sv['mode']) if sv.get('present')
        else 'absent — the lobby cannot reach any node' if sv.get('known')
        else 'unknown'))
    w('    gate levels from    %s\n' % groups['exposure']['gate_source'])
    es = po['env_source']
    w('    env read from       %s\n' % (es['source'] if es['known']
                                        else 'NOT READ -- %s' % es['why']))
    for z in groups['exposure']['zones']:
        w('\n    %s\n      %s\n' % (z['zone'], z['trust']))
        if not z['reached']:
            w('      NOTHING ANSWERED — unknown, not closed.\n')
        for r in z['probes']:
            g = 'gate %s' % r['declared_gate'] if r['declared_gate'] else 'gate 0'
            st = 'HTTP %s' % r['status'] if r['reached'] else '--- '
            flag = 'OPEN' if r.get('open') else ('ok  ' if r['ok'] else '????')
            w('      [%s] %-18s %-9s %-9s %s\n' % (flag, r['path'], st, g, r['meaning'][:64]))
    w('\n')

    w('  C. THE ENTRY CHAIN — one domain, one login\n')
    ec = groups['entry_chain']
    if not ec['known']:
        w('    UNKNOWN — %s\n' % ec['why'])
    else:
        ap = ec['apex'] or {}
        w('    [%s] %-20s %-34s\n' % ('ok  ' if ap.get('ok') else 'BAD ',
                                      'public login space', ap.get('hostname') or '?'))
        w('           public by design (no app on the apex, correctly). '
          'listed as splash: %s\n' % ('yes' if ap.get('declared_public_by_code') else 'NO'))
        w('           app on %s/api: %s\n' % (
            ap.get('hostname') or '?',
            ('%s, %s policy(ies)' % (ap['api_path_app'], ap['api_path_policies']))
            if ap.get('api_path_app') else 'NONE -- only _splash_only guards it'))
        for l in ec['links']:
            mark = 'ok  ' if l['ok'] else ('BAD ' if l['ok'] is False else '????')
            w('    [%s] %-20s %-34s\n' % (mark, l['link'], l['expects']))
            if l['app'] is None:
                w('           NO ACCESS APP COVERS THIS\n')
            else:
                w('           app %s · %s policy(ies) · %s\n' % (
                    l['app'], l['policies'], l['kind'] or 'policy kind unknown'))
        w('    all Access apps on this zone:\n')
        for a in ec['apps']:
            n = a['policies'] if a['policies_known'] else '?'
            w('      %-46s %s policy(ies)%s\n' % (
                a['domain'], n, '   <-- ZERO POLICIES DENIES EVERYONE' if n == 0 else ''))
    w('\n')

    w('  FINDINGS\n')
    if not ctx['findings']:
        w('    none.\n')
    for f in sorted(ctx['findings'], key=lambda x: ORDER[x['severity']]):
        w('    [%s] %s\n' % (f['severity'].upper(), f['what']))
        w('        where : %s\n' % f['where'])
        w('        why   : %s\n' % f['why_it_matters'])
        w('        show  : %s\n' % f['command'])
    w('\n')

    w('  D. WHAT I COULD NOT SEE\n')
    if not ctx['blind']:
        w('    nothing — every check ran.\n')
    for b2 in ctx['blind']:
        w('    - %s\n' % b2['check'])
        w('        why : %s\n' % b2['why'])
        w('        try : %s\n' % b2['command'])
    w('\n  Read this group first if the verdict surprised you. Anything listed\n')
    w('  here is UNKNOWN, and unknown is not the same as fine.\n\n')


# 20404830  report — the whole situation as one dict, and nothing printed
def report(argv=()):
    """Returns (ctx, groups, verdict, obj). This is the seam.

    Separated from main() for one specific reason, argued rather than assumed: a
    handler that wants to serve this over HTTP should be able to call ONE
    function and get the object, instead of a second copy of the assembly being
    written in handlers/ that then drifts from this one. That is the exact defect
    handlers/status.py:get_sitemap has against kernel/router.py:ROUTES — two
    parallel lists, already disagreeing.

    Whether it SHOULD be served over HTTP is a different question and the answer
    is 'not at gate 0 and not at gate 1'. This object is an inventory of open
    doors, internal addresses and Access app ids. See the note at the bottom of
    this file.
    """
    ctx = _context(list(argv))
    groups = {}
    # posture BEFORE exposure: the exposure probes annotate every result with
    # whether the gate they name is actually enforced, and they cannot do that
    # until the posture is known.
    groups['posture'] = posture(ctx)
    ctx['posture'] = groups['posture']
    groups['serving'] = serving(ctx)
    # entry_chain BEFORE exposure: exposure explains a public 200 by naming the
    # Access app that should have stopped it, and it can only do that once the
    # app list has been read. Without this order it would report "no app covers
    # it" for every path, which is a fabricated finding.
    groups['entry_chain'] = entry_chain(ctx)
    groups['exposure'] = exposure(ctx)
    groups['perspective'] = perspective(ctx)
    verdict = _verdict(ctx, groups)

    # ONE object, stable keys, every judgement carrying an explicit ok or
    # unknown. This is the surface a model reads, so nothing here is a bare
    # status code and nothing is implied by absence.
    obj = {
        'tool': 'situation',
        'code': '20404715',
        'schema': 1,
        'generated': _now(),
        'read_only': True,
        'target': {
            'hub': ctx['hub'], 'is_local': ctx['target_local'],
            'hub_port': ctx['hub_port'], 'zone': ctx['zone'] or None,
            'node_hostname': ctx['node_json'].get('hostname') or None,
            'node_name': ctx['node_json'].get('node') or None,
            'server_id': ctx['node_json'].get('server_id') or None,
            'tunnel_id_short': ctx['tunnel_id_short'],
            'cf_token_source': ctx['cf_token_source'],
            'dns_works_here': ctx['dns_works'],
        },
        'verdict': verdict,
        'perspective': groups['perspective'],
        'serving': groups['serving'],
        'posture': groups['posture'],
        'exposure': groups['exposure'],
        'entry_chain': groups['entry_chain'],
        'findings': sorted(ctx['findings'], key=lambda x: ORDER[x['severity']]),
        'blind': ctx['blind'],
        'notes': [
            'No credential was presented on any probe. A 401 or 403 means '
            'THIS caller was refused; it is not proof the path works for a '
            'caller that is allowed through.',
            'A status from the Cloudflare edge does not prove the origin is '
            'up. 401, 302 and 404 can all be minted at the edge.',
            'Facts read from files, env and sqlite describe the machine this '
            'ran on. When target.is_local is false they are absent or in '
            'blind, never attributed to the target.',
            'An empty findings list with a non-empty blind list is NOT a '
            'clean result. Read blind first.',
        ],
    }
    return ctx, groups, verdict, obj


# 20404826  main — gather, judge, print. In that order, once.
def main(argv):
    ctx, groups, verdict, obj = report(argv)
    if ctx['json']:
        print(json.dumps(obj, indent=2))
    else:
        _human(ctx, groups, verdict)

    # Exit codes for a caller that wants one: 0 clean, 1 something is wrong,
    # 2 could not see enough to say. 2 is deliberately not 0.
    return {'ok': 0, 'drift': 1, 'exposed': 1, 'broken': 1, 'cannot_say': 2}[verdict['state']]


if __name__ == '__main__':
    try:
        sys.exit(main(sys.argv[1:]))
    except KeyboardInterrupt:
        sys.exit(130)


# ─────────────────────────────────────────────────────────────────────────────
# SHOULD THIS BE A ROUTE?  The argument, so it is not re-litigated from memory.
#
# The case FOR is real. The operator asked for "a plug-in for the AI to sink
# into", and over HTTP a model or the hub UI could ask this without ssh.
# /api/events/self is the precedent: gate 0, because "notifications are broken"
# and "I cannot log in" have the same first question.
#
# The case AGAINST is stronger, and it is specific rather than squeamish:
#
#  1  THE PRECEDENT DOES NOT TRANSFER. events/self names files and says whether
#     they exist. It returns no content. This returns internal addresses, which
#     paths are open, the tailnet and LAN IPs, Access app ids and the tunnel's
#     state. It is a map of the way in. Publishing the exposure report on the
#     same origin as the exposures is the one thing not to do.
#
#  2  THIS HUB HAS NO WORKING GATE TO PUT IT BEHIND. gate 1 is shadow-mode, and
#     gate_check() returns True for 2 and 3 while TOTP is unconfigured. So
#     "gate 2" on this route today means gate 0. A route is only as private as
#     the enforcement, and the enforcement is off -- which this tool's own
#     output says.
#
#  3  IT WOULD BE AN OUTBOUND AMPLIFIER. One request makes the hub issue dozens
#     of HTTPS probes and several Cloudflare API calls, and takes tens of
#     seconds on a threaded stdlib server. Unauthenticated, that is a way to
#     make the box work for a stranger.
#
#  4  IT WOULD PUT THE CF TOKEN ON A REQUEST PATH. Today the token is read when
#     a human runs a tool. As a route, a remote caller decides when it is read.
#
# So: NOT ROUTED, and run over ssh, which is what it was built for --
#     ssh <node> "python3 - --json" < hub/tools/situation.py
# needs no deploy, writes nothing to the box, and has the operator's own
# credential in front of it already.
#
# IF IT IS ROUTED ANYWAY, the shape that is least wrong:
#
#   {"code": "20404715", "method": "POST", "path": "/api/situation",
#    "prefix": False, "gate": 2, "handler": "post_situation", "module": "ops"}
#
#   POST, not GET: nothing should be able to trigger it with a link, a prefetch
#   or a service worker, and it must not be cacheable.
#   gate 2, never 0 or 1 -- and gate 2 is only real once TOTP exists, so this
#   route should not be added before it does.
#   It must NEVER be added to router.SPLASH_BEHIND_LOGIN. Every path on that
#   list is currently public on www.flarevault.dev; this tool found that by
#   probing it. Adding this route to that list would publish the findings.
#   It must NEVER be added to handlers/lobby.py:PROXY_ALLOW. The lobby reaches
#   nodes with a fleet-wide service token; proxying this would let one token
#   collect every node's open-door inventory in one pass.
#   A handler is then two lines, because report() already returns the object:
#       from tools.situation import report
#       handler.send_json(report(['--json'])[3])
#   with a minimum interval between runs, or point 3 above applies to the
#   operator's own dashboard refreshing on a timer.
# ─────────────────────────────────────────────────────────────────────────────
