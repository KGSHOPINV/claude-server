#!/usr/bin/env python3
"""
# 20200012  kernel.heartbeat — the node-side emitter and its fallback chain

HEARTBEATS ARE ENRICHMENT, NOT THE SOURCE OF TRUTH. Corrected 2026-09-26.

Nothing depends on this module for the fleet to be VISIBLE. kernel.fleet
enumerates the fleet from the zone's `flareshub-*` DNS records, which are
derived from each node's own server id at enrolment — so who exists is
answered by the register, with no beat, no election and no box that has to be
up for the others to be seen.

What a beat carries that DNS cannot: containers, projects, attention, os,
uptime, and the fact that this node was alive a moment ago. That is worth
having and it is why this file stays. But a node that never beats, or a
receiver that is down for a day, costs LIVE DETAIL about a node — never the
knowledge that the node is there.

Which is also why the emitter is harmless to lose. It was already written that
way ("A node that cannot reach central on ANY path is not broken"); the
difference now is that the fleet view is not degraded to nothing while it fails.

Runs only in NODE mode. Every 30s it POSTs this node's /api/node payload to
central, trying three paths in order:

    1. cloudflare   central_url         production
    2. tailscale    central_tailscale   failsafe, assumed always available
    3. lan          central_lan         same network only

First success wins. The path that worked is reported with the beat, because a
node that quietly fell back from cloudflare to tailscale is still up — and
that silent degradation is exactly the kind of thing that otherwise goes
unnoticed until the fallback fails too.

Central addresses come from server.identity.json. Everything a node needs to
find home lives in one file.
"""
import json
import threading
import time
import urllib.error
import urllib.request

from kernel import identity as _id

INTERVAL = 30
TIMEOUT = 8

_state = {'last_path': None, 'last_ok': None, 'last_error': None,
          'beats': 0, 'failures': 0}
_lock = threading.Lock()


def state():
    with _lock:
        return dict(_state)


# 20200341  _targets — the fallback chain, in order, from the identity file
def _targets():
    d = _id.load()
    out = []
    for key, label in (('central_url', 'cloudflare'),
                       ('central_tailscale', 'tailscale'),
                       ('central_lan', 'lan')):
        url = (d.get(key) or '').rstrip('/')
        if url:
            out.append((label, url + '/api/heartbeat'))
    return out


# 20200342  _post — one attempt against one path
def _post(url, payload, token):
    # The cloudflare path goes through Access, which refuses anything without
    # a service token -- the node hostnames are deliberately closed to humans.
    # So the credential rides along when we hold one. Over tailscale or lan
    # there is no Access in the way and these headers are simply ignored.
    #
    # The User-Agent is not decoration. Cloudflare's Browser Integrity Check
    # sits in FRONT of Access and answers 403/1010 to anything that looks
    # automated, which reads exactly like the token being rejected.
    headers = {'Content-Type': 'application/json',
               'X-Flare-Token': token or '',
               'User-Agent': 'FlareSHub-Node/1.0'}
    try:
        from kernel import svctoken as _svc
        headers.update(_svc.edge_headers())
    except Exception:
        pass          # no token: tailscale and lan still work
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode(),
        headers=headers,
        method='POST')
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        return r.status, r.read(2048).decode('utf-8', 'replace')


# 20200343  beat — one heartbeat across the fallback chain
def beat(payload_fn, _retry=True):
    """Returns (path, status) on success, (None, error) on total failure.

    A node that cannot reach central on ANY path is not broken — central may
    simply be down. It keeps running and keeps trying; no data is lost because
    the next beat carries current state anyway.

    RE-REGISTERS ONCE IF CENTRAL DOES NOT KNOW THIS NODE. A beat no longer
    creates a fleet record — central refuses an unknown server_id with 403
    unknown_server_id (kernel/fleet._bound), which is what closes "invent a
    node". The honest consequence is that a central which lost db/fleet.json
    would refuse this node's beats until something registered it again, and
    registration otherwise only happens at node startup: the fleet would sit
    blind for as long as this process stayed up. So the refusal is ACTED ON
    rather than just logged. Bounded to one attempt per beat by _retry, because
    a node that cannot register must not turn one failure into a loop.
    """
    targets = _targets()
    if not targets:
        return None, 'no central address in server.identity.json'
    try:
        payload = payload_fn()
    except Exception as e:
        return None, f'payload build failed: {e}'

    token = ''
    try:
        token = _id.issue(_id.server_id() or 'node', 'operator', ttl=120)
    except Exception:
        pass   # unsigned beat is still better than no beat

    last_err = None
    unknown_here = False
    for label, url in targets:
        try:
            status, _body = _post(f'{url}?path={label}', payload, token)
            if 200 <= status < 300:
                with _lock:
                    _state.update({'last_path': label, 'last_ok': time.time(),
                                   'last_error': None})
                    _state['beats'] += 1
                return label, status
            last_err = f'{label}: HTTP {status}'
        except urllib.error.HTTPError as e:
            last_err = f'{label}: HTTP {e.code}'
            if e.code == 403:
                # The two refusals a node can actually FIX by re-registering.
                # A machine_id_mismatch is deliberately NOT one of them: that
                # means another record already owns this server_id, and a node
                # must not try to take it — an operator has to look.
                try:
                    detail = e.read(512).decode('utf-8', 'replace')
                except Exception:
                    detail = ''
                if 'unknown_server_id' in detail or 'record_unbound' in detail:
                    unknown_here = True
                    last_err = f'{label}: HTTP 403, central does not know this node'
        except Exception as e:
            last_err = f'{label}: {type(e).__name__}'
    if unknown_here and _retry:
        register(payload_fn)
        return beat(payload_fn, _retry=False)
    with _lock:
        _state.update({'last_error': last_err})
        _state['failures'] += 1
    return None, last_err


# 20200345  register — announce this node to central before the first beat
def register(payload_fn):
    """The spec is register -> heartbeat. Without this the first beat creates
    the record implicitly and ENROLLING never happens, so central cannot tell
    a node that just joined from one that has always been there.

    Best-effort and idempotent: central flags a re-registration rather than
    rejecting it, so retrying on every start is safe.
    """
    targets = [(l, u.replace('/api/heartbeat', '/api/mesh/register'))
               for l, u in _targets()]
    if not targets:
        return None, 'no central address'
    try:
        p = payload_fn()
    except Exception as e:
        return None, str(e)
    body = {
        'server_id':    _id.server_id(),
        'name':         _id.node_name(),
        'machine_id':   _id.machine_id(),
        'reachability': [k for k, v in (('lan', p.get('local_ip')),
                                        ('tailscale', p.get('tailscale_ip')),
                                        ('public', p.get('public'))) if v],
    }
    token = ''
    try:
        token = _id.issue(_id.server_id() or 'node', 'operator', ttl=120)
    except Exception:
        pass
    last = None
    for label, url in targets:
        try:
            status, _b = _post(url, body, token)
            if 200 <= status < 300:
                return label, status
            last = f'{label}: HTTP {status}'
        except Exception as e:
            last = f'{label}: {type(e).__name__}'
    return None, last


# 20200344  loop — background emitter, node mode only
def loop(payload_fn, log_fn=None):
    """Started from the bootstrap. Exits immediately in central mode —
    central receives beats, it does not send them."""
    if _id.is_central():
        return
    prev_path = None
    # Announce before the first beat so central sees ENROLLING -> HEALTHY
    # rather than a node appearing already healthy out of nowhere.
    try:
        path, info = register(payload_fn)
        if log_fn:
            log_fn(f'mesh register via {path}' if path else f'mesh register failed: {info}')
    except Exception:
        pass
    while True:
        try:
            path, info = beat(payload_fn)
            if path and path != prev_path and log_fn:
                where = f'{prev_path} -> {path}' if prev_path else path
                log_fn(f'heartbeat path: {where}')
                prev_path = path
            elif path:
                prev_path = path
        except Exception:
            pass       # never let the emitter kill the thread
        time.sleep(INTERVAL)


def start(payload_fn, log_fn=None):
    if _id.is_central():
        return None
    t = threading.Thread(target=loop, args=(payload_fn, log_fn), daemon=True)
    t.start()
    return t
