#!/usr/bin/env python3
"""
# 20404716  tools.tracks — the three tracks, checked. Not a docket.

    python3 hub/tools/tracks.py
    python3 hub/tools/tracks.py --json
    python3 hub/tools/tracks.py --track unison
    python3 hub/tools/tracks.py --hub http://100.107.234.9:8765     # from elsewhere
    ssh <node> "python3 -" < hub/tools/tracks.py                    # nothing written to the box

THE PROBLEM THIS EXISTS FOR. The operator asked for "a project manager to make
sure we're tuned to what we need to resolve and get set up". There is already a
written one: TASKS.md, 165 lines, last touched 2026-09-16. It is one of 46
tracked markdown files in this repo, and the operator has named that sprawl a
defect in his own words -- "you just dump everywhere and don't have any regard
to where they go".

A written docket stops being true and NOBODY NOTICES. That is the whole failure.
It is not that the document is wrong; it is that a wrong document looks exactly
like a right one. So this file writes nothing down. Every item below asks the
machine or the repo a question with an answer, and reports the answer.

This is tools/step.py's method applied to three tracks instead of one, and it
inherits step.py's rules verbatim:

  - The next thing to do is the FIRST item that is not finished. Not the one
    that feels next.
  - A later item passing does not excuse an earlier one that does not. That is
    reported as OUT OF ORDER, because it is how the port band shipped before
    any project had been told.
  - AN ITEM THAT CANNOT BE CHECKED IS 'unknown'. Never 'done', never 'todo'.
    Silence is not evidence. An unknown is a reason to go look, and the command
    to look with is printed beside it.
  - It reports and never repairs. Read-only, stdlib only, no writes, no
    restarts, no Cloudflare call but GET.

THE THREE TRACKS, in the operator's stated dependency order:

    1  ENTRY    "complete the entry enough for FlareVault"
    2  UNISON   the plan AI sessions get directed to. It must be finished
                BEFORE the new front end, because a front end built against an
                unsettled plan is a front end built twice.
    3  NEW UI   the new server console. After unison.

The order is load-bearing, not decorative: while UNISON has an unfinished item,
the NEW UI track prints BLOCKED and names the item that blocks it.

WHAT IS NOT A TASK. Several things in the way are DECISIONS only the operator
can make -- the Access restructure, whether to arm HUB_ENFORCE_GATES, which box
is central, the shape of the PIN, VAPID or ntfy for push. Those are listed
separately, attributed to him, and are NOT counted in any done/total. Counting a
decision as a task makes the totals lie and makes the tool nag about something
it has no standing to nag about.

SINGLE SOURCE OF TRUTH. The five build-order checks in the UNISON track are
IMPORTED from hub/tools/step.py and run as-is. They are not copied here. Two
copies of a check is two answers to one question, which is the disease this
repo already has in four places (status.py:get_sitemap vs router.ROUTES, two
readers of the disks, five copies of config get/set, three of get_server_info).
If step.py cannot be found or imported, those five items are unknown -- not
re-implemented.

THE HONEST LIMITS, up front, because a checker that overstates its reach is
worse than none:

  IT ONLY KNOWS THE BOX IT RUNS ON. ~/.flare/node.json, the Cloudflare token
  and the repo checkout are facts about THIS machine. Run it on the operator's
  Windows PC and the node hostname, the Access apps and the live hub are all
  unknown -- which is correct, and they are reported as unknown rather than
  quietly answered from the PC and printed under a server's name. That exact
  substitution is the worst bug a fleet tool can have and it has happened here
  once already (see handlers/lobbyhost.py, why the Fleet pane was removed).

  THE REPO IS NOT THE MACHINE. The checkout here can be a different ref from
  the hub that is actually serving. Where both can be read, they are compared
  and a disagreement is a finding, not an average.

  A STATUS FROM THE CLOUDFLARE EDGE DOES NOT PROVE THE ORIGIN IS UP. 401, 302
  and 301 can all be minted at the edge with no packet reaching the box. What a
  public probe proves is that the hostname exists and something is guarding it.

  NO CREDENTIAL IS PRESENTED, EVER. So a 200 here proves a door is open. A 401
  proves only that THIS caller was refused; it does not prove the door works
  for whoever is meant to come through it.

  NO SECRET IS PRINTED. The Cloudflare token is read the way situation.py reads
  it and never reported -- only WHERE it came from. Nothing here holds a value
  it could leak.

  DEPTH BELONGS TO THE OTHER TOOLS. situation.py is the full reading of who is
  serving what to whom, and step.py owns the build order. This counts coverage
  and completion and points at them. It does not re-derive their answers.
"""
import json
import os
import re
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request

CF_API = 'https://api.cloudflare.com/client/v4'

# Three words, fixed. A track report a model reads is only useful if the words
# mean the same thing on every run.
DONE = 'done'
TODO = 'todo'
UNKNOWN = 'unknown'

LOCAL_HOSTS = ('127.0.0.1', 'localhost', '::1', '[::1]')

# The bulletin table has no "list all" route (see _bulletins), so it is walked
# by number. This is the stop: a table longer than this is a different problem
# and an unbounded walk over HTTP is not a diagnostic, it is a load test.
BULLETIN_WALK_MAX = 200

# An action a project does not have to act on. STATE.md is explicit that
# "nothing right now" is a common and valid answer, so a bulletin carrying one
# is complete, not outstanding -- counting it as actionable would make every
# readout look like a demand and projects stop reading them.
NOT_ACTIONABLE = ('', 'none', 'nothing', 'nothing right now', 'n/a', '-')


# ── plumbing ────────────────────────────────────────────────────────────────
# Everything here returns a value and never raises. The machines this runs on
# are deliberately unlike each other: a node has /proc, ~/.flare and a hub on
# loopback; the operator's Windows PC has none of them. A checker that dies on
# the first missing file checks nothing.

# 20404901  _root — where the repo is, surviving having no __file__
def _root():
    """Three ways this gets run and only one of them has a __file__: as a file
    in the repo, as a file on the Windows PC, and piped over ssh into
    `python3 -` so that inspecting a box never means WRITING a tool onto it.
    A NameError at import in the third case is not degrading honestly.

    HUB_ROOT overrides. Otherwise it walks up from __file__ and then from the
    cwd looking for a marker that only this repo has. Everything that reads the
    repo handles '' by reporting that it could not read it, so a wrong root
    produces 'unknown' and never a wrong answer.
    """
    env = os.environ.get('HUB_ROOT', '').strip()
    if env and os.path.isdir(env):
        return env

    def looks_right(p):
        return os.path.isfile(os.path.join(p, 'hub', 'kernel', 'router.py'))

    cands = []
    try:
        cands.append(os.path.dirname(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__)))))
    except NameError:
        pass                                  # piped: there is no __file__
    here = os.getcwd()
    cands.append(here)
    # ~/hub on both servers holds the repo whose hub/ is one level down, and a
    # piped run lands in the home directory, not in the repo.
    for extra in (os.path.join(here, 'hub'), os.path.expanduser('~/hub'),
                  os.path.dirname(here)):
        cands.append(extra)
    for c in cands:
        if c and looks_right(c):
            return c
    return ''


# 20404902  _read — a repo file, or '' if it is not there
def _read(root, rel):
    if not root:
        return ''
    try:
        with open(os.path.join(root, rel), encoding='utf-8', errors='ignore') as f:
            return f.read()
    except Exception:
        return ''


# 20404903  _probe — one HTTP request, and reached kept apart from status
def _probe(url, timeout=8):
    """`reached` is the load-bearing field and it is deliberately not derived
    from `status`. reached=False with status=None means "I could not see it" --
    which is neither a 500 nor a down service, and getting those three confused
    has already cost this project whole evenings.

    Redirects are NOT followed. That is the point: a 301 on an alias and a 302
    to an Access login are each the finding, and chasing them would replace the
    finding with whatever the destination returns.
    """
    class _NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *a, **k):
            return None

    req = urllib.request.Request(
        url, headers={'User-Agent': 'FlareSHub-tracks/1 (read-only)'})
    op = urllib.request.build_opener(_NoRedirect)
    try:
        with op.open(req, timeout=timeout) as r:
            return {'reached': True, 'status': r.status, 'error': None}
    except urllib.error.HTTPError as e:
        # An HTTP error IS an answer: something is there and it refused us,
        # which on a node hostname is the correct outcome.
        return {'reached': True, 'status': e.code, 'error': None}
    except urllib.error.URLError as e:
        return {'reached': False, 'status': None, 'error': str(e.reason)[:80]}
    except Exception as e:
        return {'reached': False, 'status': None, 'error': str(e)[:80]}


# 20404904  _dns — does the name resolve at all
def _dns(name):
    """Kept apart from _probe because "the name does not exist" and "it exists
    and nothing answered" are different faults with different fixes, and one
    failed request cannot tell them apart."""
    try:
        socket.getaddrinfo(name, None)
        return True
    except Exception:
        return False


# 20404905  _api — one hub GET, with unreachable distinguishable from empty
def _api(hub, path, timeout=8):
    """Returns (reached, status, obj).

    THIS DISTINCTION IS THE WHOLE REASON THIS FUNCTION EXISTS rather than
    reusing step.py's api(). step.py's helper collapses an unreachable hub into
    (0, {}), so step 5 reports "registry is empty -- no intake has started"
    when in fact it never reached a hub at all. That is a real answer standing
    in for a missing one. Here, reached=False makes the item unknown.
    """
    url = hub.rstrip('/') + path
    req = urllib.request.Request(
        url, headers={'User-Agent': 'FlareSHub-tracks/1 (read-only)'})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            try:
                return True, r.status, json.load(r)
            except Exception:
                return True, r.status, None
    except urllib.error.HTTPError as e:
        return True, e.code, None
    except Exception:
        return False, None, None


# 20404906  _cf_token — the same places enroll.sh looks, and the VALUE NEVER LEAVES
def _cf_token():
    """Returns (token, source). The token is used and never reported: callers
    get `source` to print and nothing else. cf-check.py prints four characters
    of it, which is four more than anything needs."""
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


# 20404907  _cf — one Cloudflare GET. GET only, structurally.
def _cf(token, path, timeout=20):
    """Returns (body, why); exactly one is falsy.

    There is no method parameter. Not "defaults to GET" -- no parameter at all,
    so this module cannot be edited into something that writes by passing a
    string. A tool whose job is to say whether the doors are shut must not be
    able to open one.
    """
    if not token:
        return None, 'no Cloudflare token on this machine'
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
        return None, str(e)[:80]


# 20404908  _git_ref — the checked-out ref, or '' if git cannot say
def _git_ref(root):
    if not root:
        return '', ''
    try:
        p = subprocess.run(['git', '-C', root, 'rev-parse', '--short', 'HEAD'],
                           capture_output=True, text=True, timeout=15)
        b = subprocess.run(['git', '-C', root, 'rev-parse', '--abbrev-ref', 'HEAD'],
                           capture_output=True, text=True, timeout=15)
        return (p.stdout or '').strip(), (b.stdout or '').strip()
    except Exception:
        return '', ''


# 20404909  item — one checked item, in one shape
def item(iid, title, state, why, show='', mine=True, evidence=None):
    """Every item carries `state` explicitly. There is no "absent means fine":
    a caller reading this object never has to infer a verdict from a missing
    field, because inference is where a clean-looking report comes from.

    `mine` is False for the one kind of item that is real, unfinished, and NOT
    the operator's to move -- FlareVault replacing its own splash page. Those
    are reported and excluded from "what do I do next", because a next-action
    line that names someone else's work is a next-action line nobody can act on.
    """
    return {'id': iid, 'title': title, 'state': state, 'why': why,
            'show': show, 'mine': mine, 'evidence': evidence or {}}


# 20404910  decision — not a task, and never counted as one
def decision(did, title, why, observed, ask):
    """A DECISION is a thing the machine cannot settle because it is a choice.
    Listing these as todo would make the tool nag about something it has no
    standing to nag about, and would make every done/total wrong."""
    return {'id': did, 'title': title, 'owner': 'operator', 'why': why,
            'observed': observed, 'the_question': ask}


# ── the five build-order checks, IMPORTED and not copied ────────────────────

# 20404911  _step_checks — run step.py's own five checks, as step.py wrote them
def _step_checks(ctx):
    """step.py is the source of truth for the build order. It is imported by
    path and its STEPS are called unmodified.

    NOT SHELLED OUT, and the reason is specific: step.py's main() prints a
    human report and returns 0 or 1, so parsing its stdout would mean a regex
    over prose -- the exact defect control.py:_drift() already has, where a
    number is pulled back out of a text field by pattern. Importing gets the
    (ok, why) pair each check actually returned.

    Its module globals HUB and ROOT are re-pointed at this run's target so that
    --hub reaches the same box for both tools. Nothing else about it is touched.
    """
    out = {'known': False, 'why': '', 'results': [], 'source': ''}
    root = ctx['root']
    path = os.path.join(root, 'hub', 'tools', 'step.py') if root else ''
    if not path or not os.path.isfile(path):
        out['why'] = ('hub/tools/step.py was not found (repo root: %s). The five '
                      'build-order items are UNKNOWN -- they are not '
                      're-implemented here, because two copies of a check is two '
                      'answers to one question.'
                      % (root or 'not found from this directory'))
        return out
    try:
        import importlib.util
        spec = importlib.util.spec_from_file_location('flare_step_imported', path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
    except Exception as e:
        out['why'] = 'step.py would not import: %s' % str(e)[:90]
        return out
    mod.HUB = ctx['hub']
    mod.ROOT = root
    out['known'] = True
    out['source'] = path
    for num, title, fn in getattr(mod, 'STEPS', []):
        try:
            ok, why = fn()
            out['results'].append({'num': num, 'title': title, 'ok': bool(ok),
                                   'why': why, 'raised': False})
        except Exception as e:
            # step.py's own main() turns a raised check into a failure. Here it
            # becomes unknown instead: a check that crashed did not observe
            # anything, and "not done" is a claim about the system.
            out['results'].append({'num': num, 'title': title, 'ok': None,
                                   'why': 'the check itself failed: %s' % str(e)[:60],
                                   'raised': True})
    return out


# ── TRACK 1 — ENTRY ─────────────────────────────────────────────────────────

# 20404912  _zone — the apex, derived, never typed in here
def _zone(ctx):
    """Order of preference, and each is labelled in the output because which
    source it came from changes what its absence means. A zone hardcoded in
    this file would be wrong the first time the domain moved, and wrong
    silently, which is the only kind that matters."""
    if ctx['opt_zone']:
        return ctx['opt_zone'], '--zone'
    z = (ctx['node_json'].get('zone') or '').strip().lower()
    if z:
        return z, '~/.flare/node.json'
    src = _read(ctx['root'], 'hub/kernel/router.py')
    m = re.search(r"'HUB_CANONICAL_HOST',\s*'([^']*)'", src)
    if m and m.group(1):
        return m.group(1).strip().lower(), 'router.CANONICAL_HOST default'
    m = re.search(r"'HUB_SPLASH_HOSTS',\s*'([^']*)'", src)
    if m and m.group(1):
        return m.group(1).split(',')[0].strip().lower(), 'router.SPLASH_HOSTS default'
    return '', ''


# 20404913  _node_hostnames — the flareshub-<id> names, from evidence only
def _node_hostnames(ctx):
    """Returns (hosts, source). A node hostname is minted by enrolment and
    written to ~/.flare/node.json on the box it belongs to, or listed in the
    tunnel ingress. Neither is readable from the operator's PC, and the server
    id does NOT appear in the repo as data -- only inside a docstring in
    fix-entry.py, which is prose and not a source.

    So off-box this is empty and the item goes unknown. Guessing a hostname
    here and probing it would produce a confident answer about a name nobody
    configured.
    """
    if ctx['opt_public']:
        return ctx['opt_public'], '--public'
    hosts, sources = [], []
    h = (ctx['node_json'].get('hostname') or '').strip().lower()
    if h:
        hosts.append(h)
        sources.append('~/.flare/node.json')
    # BOTH sources, unioned, not the first one that answers. node.json holds the
    # ONE hostname enrolment minted for this box; the tunnel ingress is what
    # Cloudflare will actually route here, and it is the source that catches the
    # case that hurts -- a hostname added by hand, pointing at the hub, with no
    # Access app in front of it. Stopping at node.json would miss it.
    ing, _why = _ingress(ctx)
    if ing is not None:
        added = False
        for e in ing:
            if e.startswith('flareshub-') and e not in hosts:
                hosts.append(e)
                added = True
        if added or not hosts:
            sources.append('cloudflare tunnel ingress')
    return hosts, ' + '.join(sources)


# 20404914  _ingress — the hostnames Cloudflare will actually route to this box
def _ingress(ctx):
    """Returns (hostnames or None, why). None means unknown. The tunnel's own
    configuration is the only authoritative list of what arrives at this
    origin: a hostname added by hand is invisible to every other source."""
    tid = (ctx['node_json'].get('tunnel_id') or '').strip()
    if not ctx['cf_token'] or not tid or not ctx['zone']:
        return None, ('no Cloudflare token' if not ctx['cf_token'] else
                      'no tunnel id in node.json' if not tid else 'no zone')
    acct, why = _account(ctx)
    if not acct:
        return None, why
    body, why = _cf(ctx['cf_token'],
                    '/accounts/%s/cfd_tunnel/%s/configurations' % (acct, tid))
    if body is None:
        return None, why
    ing = (((body or {}).get('result') or {}).get('config') or {}).get('ingress') or []
    return [(e.get('hostname') or '').lower() for e in ing if e.get('hostname')], ''


# 20404915  _account — the account id behind the zone, read once
def _account(ctx):
    if ctx.get('_acct_cached') is not None:
        return ctx['_acct_cached'], ctx.get('_acct_why', '')
    acct, why = '', ''
    if ctx['cf_token'] and ctx['zone']:
        body, why = _cf(ctx['cf_token'], '/zones?name=' + ctx['zone'])
        res = (body or {}).get('result') or []
        if res:
            acct = ((res[0].get('account') or {}).get('id')) or ''
            if not acct:
                why = 'the zone is visible but returned no account id'
        elif not why:
            why = 'zone %s is not visible to this token' % ctx['zone']
    elif not ctx['cf_token']:
        why = 'no Cloudflare token on this machine'
    else:
        why = 'no zone could be derived'
    ctx['_acct_cached'] = acct
    ctx['_acct_why'] = why
    return acct, why


# 20404916  _access_apps — which Access apps exist on the zone, and their policy counts
def _access_apps(ctx):
    """Returns (apps or None, why). Coverage and policy COUNTS only.

    Deliberately shallow. situation.py group C already reads policy kinds and
    catches the case that has actually bitten this account -- an app with zero
    policies, which denies everyone and presents as a broken login rather than
    as a missing rule. Re-deriving that here would put two readings of the same
    Cloudflare state in the repo, and this file exists partly to complain about
    exactly that. So: count, name, and point at the other tool.
    """
    acct, why = _account(ctx)
    if not acct:
        return None, why
    body, why = _cf(ctx['cf_token'], '/accounts/%s/access/apps' % acct)
    apps = (body or {}).get('result')
    if apps is None:
        return None, why or 'Access apps could not be listed'
    out = []
    for a in apps:
        dom = (a.get('domain') or '').lower()
        if ctx['zone'] not in dom:
            continue                   # other zones on the account are not this chain
        pol, pwhy = _cf(ctx['cf_token'],
                        '/accounts/%s/access/apps/%s/policies' % (acct, a['id']))
        plist = (pol or {}).get('result')
        out.append({'domain': dom,
                    'policies': None if plist is None else len(plist),
                    'why': pwhy if plist is None else ''})
    return out, ''


# 20404917  track_entry — one address, one login, and nothing public that should not be
def track_entry(ctx):
    """"Complete the entry enough for FlareVault."

    Every item is a probe or a read. Nothing here is taken from a plan
    document, because the entry chain is the part of this system that has
    actually leaked -- for four minutes, when a second hostname was pointed at
    the origin with no Access app, and again when an alias served the machine
    id at /api/node. Both were true while every document in the repo said the
    entry was gated.
    """
    z = ctx['zone']
    items = []

    if not z:
        items.append(item(
            'E1', 'the apex serves the public login space', UNKNOWN,
            'no zone could be derived from --zone, ~/.flare/node.json or '
            'router.py, so there is no apex to probe. Every item in this track '
            'is about a hostname, and the hostname is not known.',
            'python3 hub/tools/tracks.py --zone flarevault.dev'))
        return items

    # E1  the apex. It is public on purpose -- a login page cannot sit behind a
    # login -- so 200 is the pass and anything else means the door is missing.
    p = _probe('https://%s/' % z, ctx['timeout'])
    if not p['reached']:
        items.append(item('E1', 'the apex serves the public login space', UNKNOWN,
                          'https://%s/ did not answer (%s). This is NOT proof it '
                          'is down: the edge may be what failed to reply, and this '
                          'tool cannot tell from here.' % (z, p['error']),
                          'curl -sSv -m 10 https://%s/' % z))
    elif p['status'] == 200:
        items.append(item('E1', 'the apex serves the public login space', DONE,
                          'https://%s/ answers 200 with no credential, which is '
                          'what a public login space must do.' % z, '',
                          evidence={'status': 200}))
    else:
        items.append(item('E1', 'the apex serves the public login space', TODO,
                          'https://%s/ answers %s. The one page that has to load '
                          'for a stranger does not.' % (z, p['status']),
                          'curl -si -m 10 https://%s/ | head -20' % z,
                          evidence={'status': p['status']}))

    # E2  /fleet. Gate 0 in the route table ON PURPOSE -- Access is the control
    # on this path -- so a 200 here is not a failed gate, it is no gate.
    p = _probe('https://%s/fleet' % z, ctx['timeout'])
    if not p['reached']:
        items.append(item('E2', '/fleet is behind a login, not public', UNKNOWN,
                          '/fleet did not answer (%s).' % p['error'],
                          'curl -sSv -m 10 https://%s/fleet' % z))
    elif p['status'] in (301, 302, 303, 307, 308, 401, 403):
        items.append(item('E2', '/fleet is behind a login, not public', DONE,
                          '/fleet answers %s to an anonymous request -- refused or '
                          'sent to a login. That refusal is about THIS caller; it '
                          'is not proof the door opens for the operator.'
                          % p['status'], '', evidence={'status': p['status']}))
    else:
        items.append(item('E2', '/fleet is behind a login, not public', TODO,
                          '/fleet answers %s with no credential. It is gate 0 in the '
                          'route table by design, so nothing in the hub stops this -- '
                          'Cloudflare Access is the only control on this path.'
                          % p['status'],
                          'curl -si -m 8 https://%s/fleet | head -15' % z,
                          evidence={'status': p['status']}))

    # E3  node endpoints. Spec rule 6: they refuse humans entirely. 401 is the
    # pass; 200 is no gate; 302 is a human identity policy on a hostname that
    # is specified to refuse humans.
    hosts, hsrc = _node_hostnames(ctx)
    # Read once, here, because E3 needs it too: a node hostname that has an
    # Access app but is absent from node.json and from THIS box's tunnel
    # ingress belongs to the other server, and it still has to refuse a browser.
    # It is added to what E3 PROBES and deliberately left out of what E5 checks
    # coverage for -- deriving the coverage list from the app list would make
    # E5 circular and it would pass forever.
    apps, apps_why = _access_apps(ctx)
    probe_hosts = list(hosts)
    if apps:
        for a in apps:
            d = a['domain'].rstrip('/')
            if d.startswith('flareshub-') and '/' not in d and d not in probe_hosts:
                probe_hosts.append(d)
        if len(probe_hosts) > len(hosts):
            hsrc = (hsrc + ' + Access app list') if hsrc else 'Access app list'
    if not probe_hosts:
        items.append(item(
            'E3', 'node hostnames refuse a browser (401, not 200)', UNKNOWN,
            'no flareshub-<id> hostname could be derived on this machine. It is '
            'written by enrolment into ~/.flare/node.json on the node, or listed '
            'in the tunnel ingress, and neither is readable from here. Nothing is '
            'guessed: a probe of a name nobody configured would answer a question '
            'that was not asked.',
            'ssh <node> "python3 -" < hub/tools/tracks.py   # or --public flareshub-<id>.%s' % z))
    else:
        bad, good, blind = [], [], []
        for h in probe_hosts:
            if not _dns(h):
                blind.append('%s does not resolve' % h)
                continue
            r = _probe('https://%s/' % h, ctx['timeout'])
            if not r['reached']:
                blind.append('%s did not answer' % h)
            elif r['status'] in (401, 403):
                good.append('%s %s' % (h, r['status']))
            else:
                bad.append('%s %s' % (h, r['status']))
        if bad:
            items.append(item('E3', 'node hostnames refuse a browser (401, not 200)',
                              TODO,
                              'a node endpoint must be service-token only. These are '
                              'not: %s. A 200 means no gate at all; a 302 means a '
                              'human identity policy is attached to a hostname that '
                              'is supposed to refuse humans, which also costs the '
                              'operator a second login.' % ', '.join(bad),
                              'python3 hub/tools/situation.py   # group C names the app',
                              evidence={'from': hsrc, 'wrong': bad, 'right': good}))
        elif good and not blind:
            items.append(item('E3', 'node hostnames refuse a browser (401, not 200)',
                              DONE,
                              '%s refuse an anonymous browser: %s. Read from %s.'
                              % (len(good), ', '.join(good), hsrc), '',
                              evidence={'from': hsrc, 'right': good}))
        else:
            items.append(item('E3', 'node hostnames refuse a browser (401, not 200)',
                              UNKNOWN,
                              'could not see every node hostname: %s%s'
                              % ('; '.join(blind),
                                 '. Refused correctly: %s' % ', '.join(good) if good else ''),
                              'nslookup <hostname>; curl -sSv -m 10 https://<hostname>/',
                              evidence={'from': hsrc, 'blind': blind, 'right': good}))

    # E4  the alias. This is a REGRESSION CHECK, not a feature check: www was on
    # SPLASH_HOSTS, SPLASH_BEHIND_LOGIN let /api/node through on a splash host
    # on the assumption that Access is scoped to those paths -- true for the
    # apex, false for an alias with no apps of its own -- and
    # www.<zone>/api/node served the machine id and LAN address publicly.
    src = _read(ctx['root'], 'hub/kernel/router.py')
    m = re.search(r"'HUB_REDIRECT_HOSTS',\s*'([^']*)'", src)
    aliases = [h.strip().lower() for h in (m.group(1) if m else '').split(',') if h.strip()]
    if not src:
        items.append(item('E4', 'an alias redirects and serves nothing', UNKNOWN,
                          'hub/kernel/router.py was not readable from here, so the '
                          'alias list could not be derived. An alias that is not on '
                          'REDIRECT_HOSTS is not redirected, and this cannot tell '
                          'whether the list is empty or unread.',
                          'grep -n HUB_REDIRECT_HOSTS hub/kernel/router.py'))
    elif not aliases:
        items.append(item('E4', 'an alias redirects and serves nothing', TODO,
                          'router.REDIRECT_HOSTS is empty. Any alias pointed at this '
                          'origin therefore falls through to the normal request path, '
                          'and the paths in SPLASH_BEHIND_LOGIN are let through on the '
                          'assumption that Access covers them -- which is false for a '
                          'hostname with no apps of its own.',
                          'grep -n -A6 HUB_REDIRECT_HOSTS hub/kernel/router.py'))
    else:
        serves, redirects, blind = [], [], []
        for h in aliases:
            if not _dns(h):
                blind.append('%s does not resolve' % h)
                continue
            # Both the root and the path that actually leaked. Checking only
            # the root would have passed on the night it leaked.
            for path in ('/', '/api/node'):
                r = _probe('https://%s%s' % (h, path), ctx['timeout'])
                if not r['reached']:
                    blind.append('%s%s did not answer' % (h, path))
                elif r['status'] in (301, 302, 307, 308):
                    redirects.append('%s%s %s' % (h, path, r['status']))
                else:
                    serves.append('%s%s %s' % (h, path, r['status']))
        if serves:
            items.append(item('E4', 'an alias redirects and serves nothing', TODO,
                              'an alias is SERVING rather than redirecting: %s. This '
                              'is the exact shape of the leak -- www/api/node returned '
                              'the machine id and the LAN address to the open internet, '
                              'because gating assumed the apex and an alias is not the '
                              'apex.' % ', '.join(serves),
                              'curl -si -m 8 https://%s/api/node | head -15' % aliases[0],
                              evidence={'aliases': aliases, 'serving': serves}))
        elif redirects and not blind:
            items.append(item('E4', 'an alias redirects and serves nothing', DONE,
                              'every alias answers a redirect and serves nothing: %s. '
                              'Gating stays in one place, which is the point.'
                              % ', '.join(redirects), '',
                              evidence={'aliases': aliases, 'redirects': redirects}))
        else:
            items.append(item('E4', 'an alias redirects and serves nothing', UNKNOWN,
                              'could not see every alias: %s' % '; '.join(blind),
                              'curl -sSv -m 10 https://%s/' % aliases[0],
                              evidence={'aliases': aliases, 'blind': blind}))

    # E5  Access coverage. Read from the API, never from the edge: a 401 at the
    # edge proves an app exists; it cannot prove the app has a policy anyone can
    # satisfy, and a zero-policy app on this account denied everyone for days.
    why = apps_why
    want = [z + '/api', z + '/fleet', z + '/s'] + list(hosts)
    if apps is None:
        items.append(item(
            'E5', 'an Access app covers every path that must not be public', UNKNOWN,
            'the Access app list is read from the Cloudflare API, not from the '
            'edge, and it could not be read here: %s. Which app covers which path '
            'is UNKNOWN -- not empty, unknown. Reporting "no app covers it" from a '
            'missing token would invent the worst finding this tool can make.' % why,
            'CF_API_TOKEN=... python3 hub/tools/tracks.py --track entry   '
            '# or run it on the node, where ~/.cf-token lives'))
    else:
        covered, missing, empty = [], [], []
        doms = [a['domain'] for a in apps]
        for w in want:
            best = ''
            for a in apps:
                d = a['domain']
                if d == w or (w.startswith(d.rstrip('/')) and d.count('/')):
                    if len(d) > len(best):
                        best = d
            if not best:
                missing.append(w)
                continue
            n = next((a['policies'] for a in apps if a['domain'] == best), None)
            if n == 0:
                empty.append('%s (app %s has ZERO policies)' % (w, best))
            else:
                covered.append('%s <- %s (%s policy)' % (w, best, n if n is not None else '?'))
        ev = {'apps_on_zone': len(apps), 'domains': doms, 'covered': covered,
              'uncovered': missing, 'zero_policy': empty}
        if missing or empty:
            items.append(item(
                'E5', 'an Access app covers every path that must not be public', TODO,
                '%d Access app(s) on %s. UNCOVERED: %s. ZERO-POLICY: %s. An '
                'uncovered path reaching this origin is served to the open '
                'internet with only router._splash_only in front of it; a '
                'zero-policy app denies everyone and reads as a broken login '
                'rather than as a missing rule.'
                % (len(apps), z, ', '.join(missing) or 'none',
                   ', '.join(empty) or 'none'),
                'python3 hub/tools/situation.py   # group C reads the policy kinds',
                evidence=ev))
        else:
            items.append(item(
                'E5', 'an Access app covers every path that must not be public', DONE,
                '%d Access app(s) on %s, and each path that must not be public has '
                'one with at least one policy: %s. Policy KINDS are not read here '
                '-- situation.py group C does that, and an identity policy on a '
                'node endpoint would pass this item and fail that one.'
                % (len(apps), z, '; '.join(covered)), '', evidence=ev))

    # E6  the splash. The placeholder says in its own comment that FlareVault
    # owns this page. So this is NOT the operator's item and is excluded from
    # the next-action line -- it is listed so the placeholder is never mistaken
    # for the finished page, which is how a temporary thing becomes permanent.
    sp = _read(ctx['root'], 'hub/splash.html')
    if not sp:
        items.append(item('E6', 'the splash is FlareVault\'s own page, not our placeholder',
                          UNKNOWN,
                          'hub/splash.html was not readable from here, so whether it '
                          'is still the placeholder is unknown.',
                          'grep -n "FlareVault owns this page" hub/splash.html',
                          mine=False))
    elif 'FlareVault owns this page' in sp:
        items.append(item('E6', 'the splash is FlareVault\'s own page, not our placeholder',
                          TODO,
                          'hub/splash.html still carries its own comment: "FlareVault '
                          'owns this page; when it can serve its own it replaces this '
                          'file and nothing else changes". %d lines, deliberately '
                          'minimal. NOT YOURS TO MOVE -- it is listed because a '
                          'placeholder nobody is tracking is how a placeholder ships.'
                          % len(sp.splitlines()),
                          'the swap is FlareVault replacing hub/splash.html',
                          mine=False, evidence={'lines': len(sp.splitlines())}))
    else:
        items.append(item('E6', 'the splash is FlareVault\'s own page, not our placeholder',
                          DONE,
                          'the "FlareVault owns this page" comment is gone from '
                          'hub/splash.html, which is weak evidence that FlareVault '
                          'replaced it and equally consistent with the comment being '
                          'deleted. Weak evidence is stated as weak.',
                          'git log -1 -- hub/splash.html', mine=False))

    # E7  login.<zone>. This one is checked LAST on purpose: the code already
    # tells a refused caller to go there, so if it does not exist the repo and
    # the machine disagree in the worst direction -- an error message that sends
    # a locked-out operator to a hostname that does not resolve.
    lh = 'login.' + z
    told = []
    for rel in ('hub/handlers/door.py', 'hub/handlers/users.py', 'hub/handlers/lobby.py'):
        if lh in _read(ctx['root'], rel):
            told.append(rel)
    if not _dns(lh):
        items.append(item('E7', 'login.<zone> exists as the one human door', TODO,
                          '%s does not resolve.%s Until it exists, the single human '
                          'door named by the code is a hostname that is not there.'
                          % (lh,
                             ' The code already sends people there: %s.' % ', '.join(told)
                             if told else ''),
                          'nslookup %s' % lh,
                          evidence={'resolves': False, 'named_in': told}))
    else:
        r = _probe('https://%s/' % lh, ctx['timeout'])
        if not r['reached']:
            items.append(item('E7', 'login.<zone> exists as the one human door', UNKNOWN,
                              '%s resolves and did not answer (%s).' % (lh, r['error']),
                              'curl -sSv -m 10 https://%s/' % lh))
        else:
            items.append(item('E7', 'login.<zone> exists as the one human door', DONE,
                              '%s answers %s. Whether its Access policy admits the '
                              'operator is item E5\'s question, not this one.'
                              % (lh, r['status']), '',
                              evidence={'resolves': True, 'status': r['status'],
                                        'named_in': told}))
    return items


# ── TRACK 2 — UNISON ────────────────────────────────────────────────────────

# 20404918  _bulletins — walk the bulletin table, because no route lists it
def _bulletins(ctx):
    """Returns a dict, with `known` False if the hub was not reached.

    WHY IT WALKS BY NUMBER. There is no route that lists the bulletins table.
    GET /api/bulletins/<project> lists what ONE project has not read, and with
    the registry empty there is no project list to iterate -- so the project
    names are derived from the bulletins' own scope field instead, which is
    evidence rather than a guess.

    AND A REPO/MACHINE DISAGREEMENT FOUND ON THE WAY: the route
    GET /api/bulletin-readers/<n> (router.py, code 20315705) is declared, but
    its handler strips the prefix '/api/bulletin/' from a path that begins
    '/api/bulletin-readers/', so _target() returns '' and the route answers
    400 "bulletin number required" for every input. The per-bulletin reader
    count is therefore unreachable over HTTP, which is why read counts below
    come from the per-project listing instead. NOT FIXED HERE -- this file
    reports and repairs nothing, and it may only touch itself.
    """
    out = {'known': False, 'why': '', 'total': 0, 'actionable': 0,
           'scopes': [], 'projects': [], 'read_total': 0}
    reached, status, _ = _api(ctx['hub'], '/api/status', ctx['timeout'])
    if not reached:
        out['why'] = ('no hub answered on %s. An empty bulletin list and an '
                      'unreachable hub are not the same thing and are not being '
                      'merged.' % ctx['hub'])
        return out
    misses = 0
    n = 0
    while n < BULLETIN_WALK_MAX and misses < 3:
        n += 1
        r, st, obj = _api(ctx['hub'], '/api/bulletin/%d' % n, ctx['timeout'])
        if not r:
            out['why'] = 'the hub stopped answering during the walk at n=%d' % n
            return out
        if st != 200 or not obj or not obj.get('ok'):
            misses += 1
            continue
        misses = 0
        out['known'] = True
        out['total'] += 1
        # Prefix match, not equality: the real strings are "nothing right now --
        # unless you are on the old band", and an equality test would count
        # every one of those as work a project owes.
        act = (obj.get('action') or '').strip().lower()
        if act and not any(act.startswith(x) for x in NOT_ACTIONABLE if x):
            out['actionable'] += 1
        sc = obj.get('scope') or 'all'
        if sc not in out['scopes']:
            out['scopes'].append(sc)
    out['known'] = True
    out['projects'] = [s for s in out['scopes'] if s != 'all']
    # Read counts, per project, from the listing that does work.
    for p in out['projects']:
        r, st, obj = _api(ctx['hub'], '/api/bulletins/%s?all=1' % p, ctx['timeout'])
        if r and st == 200 and obj:
            bs = obj.get('bulletins') or []
            out['read_total'] += sum(1 for b in bs if b.get('read'))
    return out


# 20404919  track_unison — the plan sessions get pointed at, and whether it is settled
def track_unison(ctx):
    """The five build-order items are step.py's, imported and run unmodified.
    The rest are the questions step.py does not ask: is anything in the
    registry, have the bulletins been read, has anything ever left through the
    outbox, and is the checkout the same code as the box.

    WHY THIS TRACK IS BEFORE THE UI. A front end is built against a plan. If
    the plan is still moving, the front end gets built twice -- and the second
    build is the one nobody has appetite for.
    """
    items = []
    st = _step_checks(ctx)
    hub_up = ctx['hub_answers']

    if not st['known']:
        for i, t in enumerate(('outbound through the server',
                               '_pending() from the record, not a dict',
                               'push on change',
                               'bootstrap -> enroll -> live hostname',
                               'one intake end to end'), start=1):
            items.append(item('U%d' % i, 'build order %d: %s' % (i, t), UNKNOWN,
                              st['why'], 'python3 hub/tools/step.py'))
    else:
        for r in st['results']:
            iid = 'U%s' % r['num']
            title = 'build order %s: %s' % (r['num'], r['title'])
            show = 'python3 hub/tools/step.py'
            if r['raised']:
                items.append(item(iid, title, UNKNOWN, r['why'], show))
                continue
            # Two places where step.py's OWN answer cannot be trusted from the
            # machine this is running on. Not re-checked -- declined, with the
            # reason, which is the only honest third option.
            if r['num'] == '4' and not ctx['node_json']:
                items.append(item(
                    iid, title, UNKNOWN,
                    'step 4 reads ~/.flare/node.json on whatever machine it runs '
                    'on, and this machine has never enrolled. Its answer ("%s") '
                    'would be about THIS box under the target\'s name, which is '
                    'the substitution that removed the Fleet pane. Run it on the '
                    'node.' % r['why'][:70], 'ssh <node> "python3 hub/tools/step.py"'))
                continue
            if r['num'] == '5' and not hub_up:
                items.append(item(
                    iid, title, UNKNOWN,
                    'step 5 asks the hub for the registry, and step.py\'s api() '
                    'turns an unreachable hub into an empty answer -- so its '
                    'verdict ("%s") is indistinguishable from "I never reached a '
                    'hub". No hub answered on %s.' % (r['why'][:60], ctx['hub']),
                    'python3 hub/tools/tracks.py --hub http://<the node>:8765'))
                continue
            items.append(item(iid, title, DONE if r['ok'] else TODO, r['why'], show,
                              evidence={'from': 'hub/tools/step.py, imported'}))

    # U6  the registry. Zero projects is the number that matters: every route,
    # table and bulletin in this track exists to serve a registered project.
    reached, status, reg = _api(ctx['hub'], '/api/registry', ctx['timeout'])
    if not reached or reg is None:
        items.append(item('U6', 'the registry has at least one project', UNKNOWN,
                          'no hub answered on %s, so the registry could not be '
                          'read. Unknown -- not empty.' % ctx['hub'],
                          'python3 hub/tools/tracks.py --hub http://<the node>:8765'))
        master = ''
    else:
        projects = reg.get('projects') or []
        master = (reg.get('master') or '')
        if projects:
            items.append(item('U6', 'the registry has at least one project', DONE,
                              '%d project(s) registered: %s'
                              % (len(projects),
                                 ', '.join(str(p.get('name')) for p in projects)), '',
                              evidence={'count': len(projects)}))
        else:
            items.append(item('U6', 'the registry has at least one project', TODO,
                              'the registry is EMPTY. Four projects are running on '
                              'the two boxes and none of them is in it, so every '
                              'bulletin, ack and ticket below this line is machinery '
                              'with nothing in it.',
                              'curl -s %s/api/registry' % ctx['hub'],
                              evidence={'count': 0}))

    # U7  bulletins. Published is not told: a bulletin nobody has read is a
    # document again, which is the thing this whole track is against.
    b = _bulletins(ctx)
    if not b['known']:
        items.append(item('U7', 'the bulletins that are queued have been read', UNKNOWN,
                          b['why'], 'python3 hub/tools/tracks.py --hub http://<the node>:8765'))
    elif b['total'] == 0:
        items.append(item('U7', 'the bulletins that are queued have been read', TODO,
                          'no bulletins have been published. Rung 1 ("you are '
                          'already in this server") is the first thing any project '
                          'is owed and it has not been written.',
                          'curl -s %s/api/bulletin/1' % ctx['hub'],
                          evidence={'total': 0}))
    elif b['read_total'] > 0:
        items.append(item('U7', 'the bulletins that are queued have been read', DONE,
                          '%d bulletin(s) published, %d of them actionable, %d read '
                          'across %d project(s).'
                          % (b['total'], b['actionable'], b['read_total'],
                             len(b['projects'])), '',
                          evidence={'total': b['total'], 'actionable': b['actionable'],
                                    'reads': b['read_total'], 'projects': b['projects']}))
    else:
        items.append(item('U7', 'the bulletins that are queued have been read', TODO,
                          '%d bulletin(s) published, %d of them carry an action a '
                          'project would have to do, and ZERO have been read by '
                          'anyone. Project scopes seen in the table: %s. The number '
                          'that matters is not how many were written, it is reads '
                          'going from 0 to 1.'
                          % (b['total'], b['actionable'],
                             ', '.join(b['projects']) or 'none'),
                          'curl -s %s/api/bulletins/<project>' % ctx['hub'],
                          evidence={'total': b['total'], 'actionable': b['actionable'],
                                    'reads': 0, 'projects': b['projects']}))

    # U8  the outbox. Step 1 asks whether the mechanism EXISTS. This asks
    # whether it has ever carried anything, which is a different question and
    # the one that decides whether the operator is still the transport.
    reached, status, ob = _api(ctx['hub'], '/api/outbox', ctx['timeout'])
    if not reached or ob is None:
        items.append(item('U8', 'something has actually gone out through the outbox',
                          UNKNOWN,
                          'no hub answered on %s, so the outbox could not be read. '
                          'An empty outbox and an unreachable hub look identical '
                          'from here and are not being merged.' % ctx['hub'],
                          'python3 hub/tools/tracks.py --hub http://<the node>:8765'))
    else:
        counts = ob.get('counts') or {}
        worker = ob.get('worker') or {}
        moved = sum(int(counts.get(k) or 0) for k in ('collected', 'acked'))
        staged = int(counts.get('staged') or 0)
        if moved:
            items.append(item('U8', 'something has actually gone out through the outbox',
                              DONE,
                              '%d message(s) collected or acknowledged; %d still '
                              'staged. The server is the transport.'
                              % (moved, staged), '', evidence={'counts': counts}))
        else:
            items.append(item('U8', 'something has actually gone out through the outbox',
                              TODO,
                              'the outbox is empty: staged %s, collected %s, acked '
                              '%s, failed %s. The worker reports started=%s with %s '
                              'attempt(s). The route and the worker exist; nothing '
                              'has ever gone through them, so the operator is still '
                              'the transport.'
                              % (counts.get('staged'), counts.get('collected'),
                                 counts.get('acked'), counts.get('failed'),
                                 worker.get('started'), worker.get('attempts')),
                              'curl -s %s/api/outbox' % ctx['hub'],
                              evidence={'counts': counts, 'worker_started': worker.get('started')}))

    # U9  congruence. "Unison" is the word for this one: the plan a session gets
    # pointed at is the plan in the CHECKOUT, and a session acting on it will be
    # acting on code the box is not running.
    ref, branch = _git_ref(ctx['root'])
    if not ref or not master:
        items.append(item('U9', 'the checkout and the serving hub are the same code',
                          UNKNOWN,
                          'could not compare: local ref %s, hub master %s. One side '
                          'is missing, so no congruence claim is made.'
                          % (ref or 'unknown', master or 'unknown'),
                          'git rev-parse --short HEAD; curl -s %s/api/registry' % ctx['hub']))
    elif master.startswith(ref) or ref.startswith(master):
        items.append(item('U9', 'the checkout and the serving hub are the same code',
                          DONE,
                          'both at %s (branch %s). Congruence means the same code '
                          'ref, never the same values -- different disks must give '
                          'different numbers.' % (ref, branch or '?'), '',
                          evidence={'local': ref, 'hub': master}))
    else:
        items.append(item('U9', 'the checkout and the serving hub are the same code',
                          TODO,
                          'THE REPO AND THE MACHINE DISAGREE. This checkout is %s on '
                          'branch %s; the hub at %s reports master %s. A session '
                          'pointed at the plan in this checkout is being pointed at '
                          'code the box is not running.'
                          % (ref, branch or '?', ctx['hub'], master),
                          'git log --oneline %s..%s' % (master, ref),
                          evidence={'local': ref, 'branch': branch, 'hub': master}))
    return items


# ── TRACK 3 — NEW UI ────────────────────────────────────────────────────────

# 20404920  _registry_views — the real view counts, parsed from ui/registry.js
def _registry_views(ctx):
    """Parsed, not maintained. A count typed into this file would be wrong the
    first time a view was added, and wrong silently."""
    src = _read(ctx['root'], 'hub/ui/registry.js')
    if not src:
        return None, 'hub/ui/registry.js was not readable from here'
    m = re.search(r'window\.HUB_VIEWS\s*=\s*\{(.*?)\n\};', src, re.S)
    if not m:
        return None, ('hub/ui/registry.js was readable but HUB_VIEWS did not parse '
                      '-- the shape changed and this parser did not')
    body = m.group(1)
    entries = re.findall(r'(\w+)\s*:\s*\{([^}]*)\}', body)
    if not entries:
        return None, 'HUB_VIEWS parsed to zero entries, which is not believable'
    out = {'total': len(entries), 'mount_null': 0, 'has_file': 0, 'hidden': 0,
           'lines': len(src.splitlines())}
    for _k, v in entries:
        flat = v.replace(' ', '')
        if 'mount:null' in flat:
            out['mount_null'] += 1
        if 'file:true' in flat:
            out['has_file'] += 1
        if 'hidden:true' in flat:
            out['hidden'] += 1
    return out, ''


# 20404921  track_ui — the new console, and what is owed before a line of it
def track_ui(ctx):
    """Every item here is a COUNT off the tree. No opinion about what the
    console should look like is encoded, because that is the operator's and he
    has already asked for mockups first.

    THE MOCKUPS ARE THE FIRST ITEM ON PURPOSE. He asked for them. Building the
    console before he has seen it is how a front end gets built twice, and
    hub/ui-next/ is already one unrequested shell sitting in the tree with zero
    importers -- its own README names a half-adopted fork as the one outcome
    that must not happen.
    """
    items = []
    root = ctx['root']

    # UI1  mockups. Derived by looking for them, not asserted.
    if not root:
        items.append(item('UI1', 'a mockup of the new console exists to be approved',
                          UNKNOWN,
                          'the repo was not found from this directory, so nothing '
                          'could be searched for.',
                          'HUB_ROOT=/path/to/repo python3 hub/tools/tracks.py --track ui'))
    else:
        found = []
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames
                           if d not in ('.git', 'node_modules', '__pycache__', 'dist')]
            for fn in filenames:
                low = fn.lower()
                if 'mockup' in low or 'mock-up' in low or 'wireframe' in low:
                    found.append(os.path.relpath(os.path.join(dirpath, fn), root))
        if found:
            items.append(item('UI1', 'a mockup of the new console exists to be approved',
                              DONE,
                              '%d file(s) found: %s. Whether he has APPROVED them is '
                              'not on the disk and is not claimed here.'
                              % (len(found), ', '.join(found[:6])), '',
                              evidence={'files': found[:20]}))
        else:
            items.append(item('UI1', 'a mockup of the new console exists to be approved',
                              TODO,
                              'no mockup or wireframe file anywhere in the tree. The '
                              'operator asked for mockups, so they are OWED before '
                              'any of this track is built -- and the four screens in '
                              'hub/plan/UNISON-PLAN.md Part VI are prose, which is '
                              'not a mockup.',
                              'the mockups are a deliverable, not a check'))

    # UI2  one console, not two. "nooo were saying 1 fucking app" -- 23
    # restatements, and there are currently four served HTML pages.
    fronts = {}
    for rel in ('hub/app.html', 'hub/mobile.html', 'hub/lobby.html', 'hub/splash.html'):
        src = _read(root, rel)
        if src:
            fronts[rel] = len(src.splitlines())
    consoles = {k: v for k, v in fronts.items() if k in ('hub/app.html', 'hub/mobile.html')}
    if not fronts:
        items.append(item('UI2', 'ONE console front end, not two', UNKNOWN,
                          'none of the hub HTML pages was readable from here.',
                          'wc -l hub/*.html'))
    elif len(consoles) > 1:
        items.append(item('UI2', 'ONE console front end, not two', TODO,
                          'TWO consoles exist: %s. A second front end is a second '
                          'place every fix has to land, and the desktop one is a '
                          'single global script scope that ui/registry.js is only '
                          'part way through dismantling. (%s are the login space and '
                          'the lobby, which are different jobs and are not counted '
                          'here.)'
                          % (', '.join('%s %d lines' % (k, v) for k, v in sorted(consoles.items())),
                             ', '.join(k for k in fronts if k not in consoles) or 'none'),
                          'wc -l hub/app.html hub/mobile.html',
                          evidence=fronts))
    else:
        items.append(item('UI2', 'ONE console front end, not two', DONE,
                          'one console: %s' % ', '.join('%s %d lines' % (k, v)
                                                        for k, v in consoles.items()),
                          '', evidence=fronts))

    # UI3  views own their files. mount:null is the honest marker the registry
    # already keeps for "still rendered by the legacy switch".
    rv, why = _registry_views(ctx)
    if rv is None:
        items.append(item('UI3', 'views render from their own files, not the legacy switch',
                          UNKNOWN, why, 'grep -c "mount:null" hub/ui/registry.js'))
    else:
        try:
            viewfiles = sorted(f for f in os.listdir(os.path.join(root, 'hub', 'ui', 'views'))
                               if f.endswith('.js'))
        except Exception:
            viewfiles = []
        migrated = rv['total'] - rv['mount_null']
        if rv['mount_null'] == 0:
            items.append(item('UI3', 'views render from their own files, not the legacy switch',
                              DONE,
                              'all %d registry entries have a mount; %d file(s) in '
                              'hub/ui/views/.' % (rv['total'], len(viewfiles)), '',
                              evidence={'entries': rv['total'], 'mount_null': 0,
                                        'view_files': viewfiles}))
        else:
            items.append(item('UI3', 'views render from their own files, not the legacy switch',
                              TODO,
                              '%d of %d registry entries still have mount:null, so %d '
                              'view(s) are migrated. %d entr(ies) declare file:true '
                              'and hub/ui/views/ holds %d file(s) (%s) -- those files '
                              'load and their mounts are not wired, so they render '
                              'from the legacy switch anyway.'
                              % (rv['mount_null'], rv['total'], migrated,
                                 rv['has_file'], len(viewfiles),
                                 ', '.join(viewfiles) or 'none'),
                              'grep -n "mount:null" hub/ui/registry.js | wc -l',
                              evidence={'entries': rv['total'],
                                        'mount_null': rv['mount_null'],
                                        'migrated': migrated,
                                        'declares_file': rv['has_file'],
                                        'view_files': viewfiles}))

    # UI4  ui-next. Adopted or gone -- the one state to avoid is the one it is
    # in, which its own README says out loud.
    if not root:
        items.append(item('UI4', 'hub/ui-next/ is either wired in or deleted', UNKNOWN,
                          'the repo was not found from this directory.',
                          'ls hub/ui-next'))
    elif not os.path.isdir(os.path.join(root, 'hub', 'ui-next')):
        items.append(item('UI4', 'hub/ui-next/ is either wired in or deleted', DONE,
                          'hub/ui-next/ is not in the tree. The half-adopted fork it '
                          'warned about cannot happen.', ''))
    else:
        nfiles = nlines = 0
        for dirpath, dirnames, filenames in os.walk(os.path.join(root, 'hub', 'ui-next')):
            dirnames[:] = [d for d in dirnames
                           if d not in ('node_modules', '.git', 'dist', '__pycache__')]
            for fn in filenames:
                nfiles += 1
                try:
                    with open(os.path.join(dirpath, fn), encoding='utf-8',
                              errors='ignore') as f:
                        nlines += sum(1 for _ in f)
                except Exception:
                    pass
        # An importer is a reference from OUTSIDE ui-next. Its own files
        # referring to each other prove nothing about adoption.
        importers = []
        for rel in ('hub/app.html', 'hub/mobile.html', 'hub/lobby.html',
                    'hub/server.py', 'hub/ui/registry.js'):
            if 'ui-next' in _read(root, rel):
                importers.append(rel)
        if importers:
            items.append(item('UI4', 'hub/ui-next/ is either wired in or deleted', DONE,
                              'referenced from %s, so it is adopted rather than '
                              'orphaned.' % ', '.join(importers), '',
                              evidence={'files': nfiles, 'importers': importers}))
        else:
            items.append(item('UI4', 'hub/ui-next/ is either wired in or deleted', TODO,
                              '%d file(s), roughly %d lines, and ZERO importers -- '
                              'nothing outside it mentions it. This is the exact '
                              'state its own README calls the one outcome that must '
                              'not happen. Adopt it as the shell or delete it; both '
                              'are defensible and neither has been chosen.'
                              % (nfiles, nlines),
                              'grep -rn "ui-next" hub/ --include=*.html --include=*.py',
                              evidence={'files': nfiles, 'lines': nlines,
                                        'importers': []}))
    return items


# ── rolling it up ───────────────────────────────────────────────────────────

# 20404922  roll — done/total, the first unfinished, and what is OUT OF ORDER
def roll(name, title, items, blocked_by=None):
    """The three numbers that make this a project manager rather than a list.

    `total` counts checked items only. A DECISION is never in `items`, so it
    can never inflate a denominator or be nagged about.

    OUT OF ORDER is the finding this whole file inherits from step.py: a later
    item done while an earlier one is not. It is not a style complaint -- it is
    how the port band got deployed before a single project had been told, which
    is the error the operator is still living with.
    """
    total = len(items)
    done = sum(1 for i in items if i['state'] == DONE)
    unknown = [i for i in items if i['state'] == UNKNOWN]
    first = next((i for i in items if i['state'] != DONE), None)
    actionable = next((i for i in items
                       if i['state'] != DONE and i['mine']), None)

    # OUT OF ORDER is measured from the first item that is KNOWN unfinished,
    # never from an unknown. An unknown earlier item may well be done -- calling
    # the work ahead of it out of order would be an accusation built on a
    # blindfold, and this tool loses its standing the first time it does that.
    first_todo = next((i for i in items if i['state'] == TODO), None)
    ahead = []
    if first_todo is not None:
        seen = False
        for i in items:
            if i['id'] == first_todo['id']:
                seen = True
                continue
            if seen and i['state'] == DONE:
                ahead.append(i['id'])
    return {'track': name, 'title': title, 'done': done, 'total': total,
            'unknown': len(unknown), 'items': items,
            'first_unfinished': first['id'] if first else None,
            'first_actionable': actionable['id'] if actionable else None,
            'first_known_unfinished': first_todo['id'] if first_todo else None,
            'out_of_order': ahead,
            'blocked_by': blocked_by,
            'complete': first is None}


# 20404923  next_line — one sentence, and it respects the order
def next_line(tracks, only):
    """WHAT DO I DO NEXT, in one sentence.

    The rule, stated so it can be argued with rather than guessed at:

      * The earliest track with an unfinished item owns the next action. That
        is the operator's stated order -- entry, then unison, then the UI -- and
        working the later track first is precisely what produced a port band
        nobody had been told about.
      * An UNKNOWN is not a task, it is a blindfold. If the first unfinished
        item could not be checked, the next action is to go and look, with the
        command, because you cannot work on what you cannot see.
      * An item that is not the operator's to move (FlareVault's own splash) is
        skipped for this line and still listed in the track.
    """
    for t in tracks:
        if only and t['track'] != only:
            continue
        if t['complete']:
            continue
        # Asked for a blocked track by name: answer the question, but do not
        # hand back a next action that the order says must not start yet.
        if only and t['blocked_by']:
            return 'BLOCKED -- %s' % t['blocked_by']
        pick = None
        for i in t['items']:
            if i['state'] != DONE and i['mine']:
                pick = i
                break
        if pick is None:
            continue
        if pick['state'] == UNKNOWN:
            # First SENTENCE, split on '. ' and not on '.', because the reasons
            # are full of paths -- '~/.flare/node.json' cut the line to "step 4
            # reads ~/" and the one sentence that had to be readable was not.
            first_sentence = pick['why'].split('. ')[0].rstrip('.')
            return ('GO LOOK: %s %s is UNKNOWN from here -- %s'
                    % (t['track'], pick['id'], first_sentence))
        return ('%s %s -- %s' % (t['track'], pick['id'], pick['title']))
    if only:
        return 'nothing unfinished and actionable in the %s track.' % only
    return ('every checked item in all three tracks is done. Read the DECISIONS '
            'and anything marked not-yours before believing that.')


# ── output ──────────────────────────────────────────────────────────────────

# 20404924  _human — the report the operator reads without scrolling far
def _human(obj, only):
    # ASCII on the way out. Not fussiness: the operator's Windows console is
    # cp1252 and an em-dash there prints as a replacement glyph in the middle of
    # the sentence that explains the finding. A report you cannot read is a
    # report that does not exist. --json keeps the real characters.
    _FOLD = {0x2014: '--', 0x2013: '-', 0x2018: "'", 0x2019: "'",
             0x201c: '"', 0x201d: '"', 0x00b7: '*', 0x2026: '...'}

    def w(s):
        try:
            sys.stdout.write(s.translate(_FOLD))
        except Exception:
            sys.stdout.write(s.translate(_FOLD).encode('ascii', 'replace').decode('ascii'))

    t = obj['target']
    w('\n  TRACKS -- what is left, checked against the machine\n')
    w('  %s   hub: %s%s   zone: %s\n'
      % (obj['generated'], t['hub'], '' if t['hub_is_local'] else '  (REMOTE)',
         t['zone'] or 'unknown'))
    w('  repo: %s   ref: %s\n' % (t['repo_root'] or 'NOT FOUND', t['repo_ref'] or '?'))
    w('  read-only. nothing was changed, nothing was restarted, no secret printed.\n\n')

    w('  NEXT:  %s\n\n' % obj['next'])

    mark = {DONE: 'done', TODO: 'TODO', UNKNOWN: '????'}
    for tr in obj['tracks']:
        if only and tr['track'] != only:
            continue
        head = '  %s -- %s' % (tr['track'], tr['title'])
        w('%s\n' % head)
        w('  %s\n' % ('-' * (len(head) - 2)))
        if tr['blocked_by']:
            w('  BLOCKED: %s\n' % tr['blocked_by'])
        w('  %d of %d done%s\n'
          % (tr['done'], tr['total'],
             ', %d could not be checked' % tr['unknown'] if tr['unknown'] else ''))
        for i in tr['items']:
            w('    [%s] %-6s %s%s\n' % (mark[i['state']], i['id'], i['title'],
                                        '   (NOT YOURS TO MOVE)' if not i['mine'] else ''))
            w('             %s\n' % i['why'])
            if i['show'] and i['state'] != DONE:
                w('             show: %s\n' % i['show'])
        if tr['out_of_order']:
            w('\n  OUT OF ORDER: %s done while %s is not.\n'
              % (', '.join(tr['out_of_order']), tr['first_known_unfinished']))
            w('  That is how the port band shipped before any project had been told.\n')
        w('\n')

    if not only:
        w('  DECISIONS -- yours, not tasks. Not counted above.\n')
        for d in obj['decisions']:
            w('    %-5s %s\n' % (d['id'], d['title']))
            w('          asks   : %s\n' % d['the_question'])
            w('          why    : %s\n' % d['why'])
            w('          now    : %s\n' % d['observed'])
        w('\n')

    w('  WHAT I COULD NOT CHECK\n')
    # Filtered with --track, because an unknown from a track that is not on
    # screen reads as an unknown in the one that is.
    blind = [b for b in obj['blind'] if not only or b['track'] == only]
    if not blind:
        w('    nothing -- every item%s was checked.\n'
          % (' in this track' if only else ''))
    for b in blind:
        w('    - %s %s\n' % (b['id'], b['title']))
        w('        why : %s\n' % b['why'])
        if b['show']:
            w('        try : %s\n' % b['show'])
    w('\n  An unknown is not a pass. Read this list before believing a total.\n\n')


# 20404925  report — the whole thing as one dict, and nothing printed
def report(argv=()):
    """Returns (ctx, obj). Separated from main() for the same reason
    situation.report() is: anything that wants this over HTTP or in another
    tool should call ONE function, not grow a second copy of the assembly that
    then drifts from this one.

    Whether it SHOULD be routed is a different question, and the answer is the
    same as situation.py's: not at gate 0 and not at gate 1. This object names
    internal addresses, Access app domains and which doors are open.
    """
    argv = list(argv)

    def opt(name, default=''):
        if name in argv:
            i = argv.index(name)
            if i + 1 < len(argv):
                return argv[i + 1]
        return default

    ctx = {}
    ctx['root'] = _root()
    ctx['timeout'] = int(opt('--timeout', '8') or 8)
    ctx['hub'] = (opt('--hub') or os.environ.get('HUB_URL')
                  or 'http://127.0.0.1:8765').rstrip('/')
    host = ctx['hub'].split('//', 1)[-1].split('/')[0].split(':')[0]
    ctx['hub_is_local'] = host in LOCAL_HOSTS
    ctx['opt_zone'] = (opt('--zone') or '').strip().lower()
    ctx['opt_public'] = [p.strip().lower()
                         for p in (opt('--public') or '').split(',') if p.strip()]
    ctx['_acct_cached'] = None

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

    tok, src = ('', '') if '--no-cf' in argv else _cf_token()
    ctx['cf_token'] = tok
    ctx['cf_token_source'] = src or None
    ctx['zone'], ctx['zone_source'] = _zone(ctx)
    # Asked once, up front: "the hub did not answer" changes the meaning of
    # every hub-derived item below, and it must not be re-discovered per item.
    ctx['hub_answers'] = _api(ctx['hub'], '/api/status', 4)[0]
    ref, branch = _git_ref(ctx['root'])

    e = roll('ENTRY', 'complete the entry enough for FlareVault', track_entry(ctx))
    u = roll('UNISON', 'the plan sessions get pointed at -- before any front end',
             track_unison(ctx))
    # THE DEPENDENCY, enforced rather than described. The operator put unison
    # before the front end because the plan is what AI sessions get directed
    # to; a console built against a moving plan is a console built twice.
    blocked = None
    if not u['complete']:
        first = next(i for i in u['items'] if i['state'] != DONE)
        blocked = ('UNISON is not complete -- %s (%s) is %s. Nothing in this track '
                   'should start before it is done, because the plan is what a '
                   'session gets pointed at and the console is built against the '
                   'plan.' % (first['id'], first['title'], first['state']))
    i3 = roll('NEW UI', 'the new server console -- after unison', track_ui(ctx),
              blocked_by=blocked)
    tracks = [e, u, i3]

    only = (opt('--track') or '').strip().lower()
    only = {'entry': 'ENTRY', 'unison': 'UNISON', 'ui': 'NEW UI'}.get(only, '')

    obj = {
        'tool': 'tracks',
        'code': '20404716',
        'schema': 1,
        'generated': time.strftime('%Y-%m-%dT%H:%M:%S', time.localtime()),
        'read_only': True,
        'target': {
            'hub': ctx['hub'], 'hub_is_local': ctx['hub_is_local'],
            'hub_answers': ctx['hub_answers'],
            'zone': ctx['zone'] or None, 'zone_source': ctx['zone_source'] or None,
            'repo_root': ctx['root'] or None, 'repo_ref': ref or None,
            'repo_branch': branch or None,
            'node_enrolled_here': bool(nj),
            'cf_token_source': ctx['cf_token_source'],
        },
        'order': ['ENTRY', 'UNISON', 'NEW UI'],
        'next': next_line(tracks, only),
        'tracks': tracks,
        'decisions': decisions(ctx),
        'blind': [{'id': i['id'], 'track': t['track'], 'title': i['title'],
                   'why': i['why'], 'show': i['show']}
                  for t in tracks for i in t['items'] if i['state'] == UNKNOWN],
        'notes': [
            'An item is done, todo or unknown. Unknown means it could not be '
            'checked from this machine -- it is never folded into either of the '
            'other two, and a total with unknowns in it is not a clean bill.',
            'DECISIONS are the operator\'s and are not counted in any done/total.',
            'The five build-order items are imported from hub/tools/step.py and '
            'run unmodified. They are not re-implemented here.',
            'No credential was presented on any probe. A 401 means THIS caller '
            'was refused, not that the door works for someone allowed through.',
            'A status from the Cloudflare edge does not prove the origin is up.',
            'Facts read from ~/.flare, the Cloudflare token and the repo describe '
            'the machine this ran on. Off-box they are unknown, never attributed '
            'to the target.',
        ],
    }
    return ctx, obj, only


# 20404926  decisions — the five that are not tasks
def decisions(ctx):
    """These block work and cannot be checked, because they are choices. Each
    one carries what the machine currently shows, so the choice is made against
    the state rather than against a memory of it."""
    apps, why = (None, '')
    if ctx['cf_token'] and ctx['zone']:
        apps, why = _access_apps(ctx)
    reached, _st, reg = _api(ctx['hub'], '/api/registry', ctx['timeout'])
    mode = ((reg or {}).get('who') or {}).get('mode') if reg else None
    pin_src = _read(ctx['root'], 'hub/kernel/control.py')
    # Was 'def _pin(' -- 4 digits of sha256 over the bulletin TEXT, one code for
    # every recipient, which is why a project could ack as another: the text is
    # printed to everybody, so everybody could recompute everybody's code. That
    # function is gone. The shape to report is the per-recipient one.
    pin_shape = ('4 digits from an HMAC of a per-bulletin secret keyed by the '
                 'project, so one code per (bulletin, recipient) '
                 '(control._recipient_pin)' if 'def _recipient_pin(' in pin_src
                 else 'not found in control.py')
    notify = _read(ctx['root'], 'hub/ui/notify.js')
    sw = _read(ctx['root'], 'hub/ui/sw.js')
    vapid = 'VAPID' in (notify + sw) or 'vapid' in (notify + sw)
    ntfy_tool = bool(ctx['root'] and os.path.isfile(
        os.path.join(ctx['root'], 'hub', 'tools', 'enable-ntfy.sh')))
    return [
        decision('D1', 'the Access restructure',
                 'every path that must not be public needs an app, and each app '
                 'added by hand is another chance to create the door without the '
                 'lock -- which has happened on this account already. One '
                 'path-scoped set on the apex, or a hostname per screen, is a '
                 'shape decision and it changes what E5 should be checking.',
                 ('%d Access app(s) on %s: %s'
                  % (len(apps), ctx['zone'], ', '.join(a['domain'] for a in apps))
                  if apps else 'not read from here (%s)' % (why or 'no token')),
                 'path-scoped apps on one hostname, or one app per hostname?'),
        decision('D2', 'HUB_ENFORCE_GATES -- arm it or leave it',
                 'Most routes declare a gate -- edges.py prints the count -- and the router records what it '
                 'would have denied and then runs the handler anyway. Arming gate 1 '
                 'does not close gates 2 and 3, because gate_check() returns True '
                 'while TOTP is unconfigured -- and arming it can lock the UI out. '
                 'That is a risk only you can accept.',
                 'not read here by design -- situation.py reads the HUB PROCESS\'s '
                 'environment, and this shell\'s environment is a different thing',
                 'arm gate 1 now, or after the second lock (TOTP) is fitted?'),
        decision('D3', 'which box is central',
                 'fks-services holds the authority layer -- FlareVault has run there '
                 'since 2026-07-27 -- and ksgcohub is the box that is actually '
                 'enrolled and serving. The two are on split tailnets and cannot '
                 'reach each other, so this is not a preference, it decides which '
                 'box the other one federates INTO.',
                 'the hub at %s reports mode=%s' % (ctx['hub'], mode or 'unknown'),
                 'fks-services or ksgcohub as central?'),
        decision('D4', 'the shape of the PIN',
                 'the PIN is the entire proof that a readout was absorbed rather '
                 'than skimmed. Whether it is per rung, per project, or per '
                 'bulletin changes what an ack means, and every ack already taken '
                 'is keyed the old way.',
                 pin_shape,
                 'four digits per bulletin, or per rung per project?'),
        decision('D5', 'VAPID or ntfy for push',
                 'both are half present, and two push paths means two places a '
                 'notification can be lost. The relayed FlareVault note says ntfy '
                 'keeps its own token auth and never sits behind Access, which is a '
                 'different trust model from a browser subscription.',
                 'VAPID present in hub/ui/notify.js + sw.js: %s; '
                 'hub/tools/enable-ntfy.sh present: %s' % (vapid, ntfy_tool),
                 'web push (VAPID) or ntfy as the one push path?'),
    ]


# 20404927  main — gather, roll up, print. In that order, once.
def main(argv):
    ctx, obj, only = report(argv)
    if '--json' in argv:
        print(json.dumps(obj, indent=2))
    else:
        _human(obj, only)
    # Exit codes for a caller that wants one, and 2 is deliberately not 0:
    # 0 everything checked is done, 1 there is work, 2 something could not be
    # seen and the totals therefore do not mean what they look like.
    shown = [t for t in obj['tracks'] if not only or t['track'] == only]
    if any(t['unknown'] for t in shown):
        return 2
    return 0 if all(t['complete'] for t in shown) else 1


if __name__ == '__main__':
    try:
        sys.exit(main(sys.argv[1:]))
    except KeyboardInterrupt:
        sys.exit(130)


# ─────────────────────────────────────────────────────────────────────────────
# WHY THIS IS NOT A ROUTE, AND NOT A DOCUMENT.
#
# NOT A DOCUMENT, because TASKS.md is the control experiment. 165 lines, last
# true on 2026-09-16, still sitting in the tree looking exactly as authoritative
# as it did the day it was written. Nobody noticed it go stale, and nobody could
# have, because a document has no way to disagree with the machine. Every item
# above can be wrong, and if it is wrong it says so out loud on the next run.
#
# NOT A ROUTE, for the same reasons situation.py argues at its own foot and one
# more of its own:
#
#  1  IT IS AN INVENTORY OF WHAT IS NOT FINISHED. Which paths have no Access
#     app, which alias serves, which hostname has no gate. Publishing the list
#     of unlocked doors on the origin behind those doors is the one thing not
#     to do.
#  2  THERE IS NO WORKING GATE TO PUT IT BEHIND. Gate 1 is shadow mode and
#     gate_check() returns True for 2 and 3 while TOTP is unconfigured. "gate 2"
#     on a new route today means gate 0.
#  3  IT MAKES DOZENS OF OUTBOUND REQUESTS -- public probes, a bulletin walk,
#     several Cloudflare API calls. Unauthenticated, that is a way to make the
#     box work for a stranger.
#  4  IT WOULD PUT THE CF TOKEN ON A REQUEST PATH. Today the token is read when
#     a human runs a tool; as a route, a remote caller decides when it is read.
#
# So it is run over ssh, which is what the _root() fallback exists for:
#     ssh <node> "python3 -" < hub/tools/tracks.py
# nothing is written to the box, nothing is deployed, and the operator's own
# credential is already in front of it.
#
# WHAT THIS FILE CANNOT DO, so it is never asked to:
#   * It cannot say whether a mockup is GOOD, or whether the operator approved
#     it. It can only say whether one exists on disk.
#   * It cannot tell a door that is closed from a door that is closed to
#     everyone. No credential is ever presented, so a 401 is "refused me".
#   * It cannot read the other server. Both boxes are on split tailnets and
#     cannot reach each other; run it twice, once per box, and compare.
#   * It cannot see a project-scoped bulletin whose project has never appeared
#     in the bulletins table, and it cannot use GET /api/bulletin-readers/<n>,
#     which answers 400 for every input because the handler strips the wrong
#     prefix. Both limits are in _bulletins()'s docstring rather than here so
#     that the reason sits beside the code that suffers it.
# ─────────────────────────────────────────────────────────────────────────────
