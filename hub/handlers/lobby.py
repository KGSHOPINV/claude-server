#!/usr/bin/env python3
"""
# 20204016  handlers.lobby — the one room behind the one door (module 16)

The FlareVault login-flow spec, which this file implements the ServerHub half
of:

    flarevault.dev            public landing        FlareVault builds it
    login.flarevault.dev      CF Access gate        FlareVault owns the policy
    dashboard.flarevault.dev  THE LOBBY             this file, central mode
    flareshub-<id>....dev     node endpoints        service token only

Four rules from that spec shape every line below:

  ONE DOOR IN.       login.flarevault.dev is the only human-facing gate. This
                     file therefore never authenticates anybody. It reads a
                     role out of a token FlareVault already issued, and decides
                     what that role may SEE. Authentication is upstream;
                     authorisation is here.

  LOBBY FIRST.       After login you always land here. So this endpoint must
                     answer for every role, including the ones that can see
                     almost nothing — an empty lobby is a correct lobby.

  ROLE SHAPES VIEW.  Same room, different doors. The JWT `role` claim decides
                     what renders. Not the URL, not a query parameter, not the
                     UI's own idea of who it is talking to.

  DEEPER = MORE.     Reading the fleet is layer 1. Containers and console are
                     layer 2. Destructive is layer 3. Vault is layer 4.

THE THING THAT MUST NOT HAPPEN. A client must never learn that another
server exists. Not its id, not its name, not a count, not an "N others" badge,
not a 403 that a 404 would have hidden. Existence is the leak — everything
else follows from it. Every filter in this file runs BEFORE any aggregate is
computed, for that reason: a summary built from the full fleet and then
trimmed has already counted the servers it was supposed to hide.

GATES DO NOT ENFORCE HERE. kernel/router.py runs gate checks in SHADOW MODE
unless HUB_ENFORCE_GATES is set, and it is not set on either live box. The
`gate` column in the route table is a DECLARATION of intent, not a guard. So
every check in this file is done by this file. If you are reading this after
the enforcement flip, the checks are now belt and braces — leave them, because
the route gate cannot express "this role may see these three servers and no
others" and never will.

L3 AND L4 ARE HOOKS, NOT IMPLEMENTATIONS. Destructive actions (PIN/TOTP) and
the vault/kill switch belong to FlareVault. The seams exist here so the UI has
a stable URL to call and a clear answer to render; they return 501 and say who
owns the missing half. A stub that half-does a destructive action is worse
than no stub at all.

CONSTITUTION Law V: credentials are never here. The service token used to
reach a node is fetched at call time from kernel.svctoken, sent, and dropped.
It is never cached in this module, never logged, and never appears in a
response body. Law IV: report, never repair — a node that will not answer
produces a finding and the command to check it, not a retry loop.
"""
import json
import re
import urllib.error
import urllib.request
from datetime import datetime, timezone

from kernel import fleet as _fleet
from kernel import identity as _id

# ── Roles, layers, doors ─────────────────────────────────────────────────────
# The layer a role can reach AT MOST. This is a ceiling, not a grant: reaching
# layer 3 still requires FlareVault's PIN/TOTP step, which is not built.
#
# master and operator sit at the same ceiling deliberately. The spec groups
# them ("MASTER/OPERATOR: fleet view ... vault/kill switch"), and the real
# separation between them is the USB/PIN proof at L4, which FlareVault holds.
# Splitting them here would invent a policy this node is not the authority for.
ROLE_LAYER = {
    'master':        4,
    'operator':      4,
    'client-full':   2,
    'client-viewer': 1,
}

# Roles that see the whole fleet. Everything not named here sees only what its
# token names. Written as a frozenset rather than a `not in ('client-...')`
# test so that a NEW role added to identity.ROLES defaults to scoped, not
# fleet-wide. A new role should fail closed on the day it is added, not on the
# day someone remembers to update this file.
FLEET_ROLES = frozenset(('master', 'operator'))

# The ownership claim. FlareVault puts the server ids a client may see here.
#
# NOT `server_id`. identity.issue() stamps `server_id` with the id of the
# machine that MINTED the token — always central, for anything central issues.
# Reading it as ownership would hand every client a row for the central box,
# which is the one row they must never see. Named here once so the mistake has
# to be made on purpose.
OWNS_CLAIM = 'servers'

# What renders in the lobby, and the layer each door needs. The UI asks for
# this rather than hardcoding a role list of its own — two places deciding who
# sees the kill switch is one place too many.
DOORS = (
    ('fleet',      'Fleet',                  1),
    ('server',     'Server console',         2),
    ('containers', 'Containers',             2),
    ('power',      'Start / stop / restart', 3),
    ('vault',      'Vault & kill switch',    4),
)

# What an action costs, in layers. Unknown actions are layer 4 — the most
# expensive — so a typo or a newly invented verb is refused rather than
# silently treated as a read.
ACTION_LAYER = {
    'read':       1,
    'logs':       2,
    'console':    2,
    'containers': 2,
    'start':      3,
    'stop':       3,
    'restart':    3,
    'prune':      3,
    'vault':      4,
    'kill':       4,
}

# A node id is a FlareVault-minted fvn_xxxxxx. Anything outside this alphabet
# is not an id, and must not reach svctoken.node_url() where it could steer a
# request. Belt to the braces of the visibility check below, which already
# refuses ids that are not in this caller's fleet.
_ID_OK = re.compile(r'^[A-Za-z0-9_.-]{1,64}$')

PROXY_TIMEOUT = 8


def _now():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


# 20316705  _identity — the caller's verified claims, or nothing
def _identity(handler):
    """Returns (claims, reason). claims is None on ANY doubt.

    Fail closed is the whole contract here. An unparseable token, an expired
    one, a signature that does not check, a role that is not in
    identity.ROLES — all of them land on the same answer: no identity, see
    nothing. There is deliberately no branch that ends in "assume operator" or
    "default to read-only fleet", because a default is what turns a broken
    token into a fleet disclosure.

    A hub SESSION is not a lobby identity. kernel.auth sessions carry a role
    string of their own ('admin', or HUB_CF_ROLE) that has never been one of
    identity.ROLES, and mapping one onto the other here would invent an
    authority this node does not have. A session is consulted for one purpose
    only: telling 'you are not logged in' apart from 'you are logged in but
    your token carries no role I can read', because those two have completely
    different fixes and a single 401 hides which one you have.
    """
    tok = (handler.headers.get('X-Flare-Token', '') or '').strip()
    if not tok:
        auth = (handler.headers.get('Authorization', '') or '').strip()
        if auth[:7].lower() == 'bearer ':
            tok = auth[7:].strip()
    if not tok:
        try:
            from kernel.auth import check_auth   # noqa: PLC0415
            if check_auth(handler) is not None:
                return None, 'session_without_role_token'
        except Exception:
            pass
        return None, 'no_token'
    claims = _id.verify(tok)
    if claims is None:
        # verify() folds bad signature, bad encoding and expiry into one None
        # on purpose. Distinguishing them here would tell an attacker which
        # half of the token to keep working on.
        return None, 'token_rejected'
    if claims.get('role') not in ROLE_LAYER:
        # A role that verify() accepted (it is in identity.ROLES) but this file
        # has no layer for. That is a deploy skew — ROLES grew, this map did
        # not — and the safe reading of skew is zero access, not full access.
        return None, 'role_not_mapped'
    return claims, ''


# 20316706  _max_layer — the ceiling a role may reach
def _max_layer(role):
    """0 for anything unrecognised. 0 means 'cannot even read', which is the
    correct reading of a role nobody has defined yet."""
    return ROLE_LAYER.get(role, 0)


# 20316707  _allows — may this role attempt an action at this layer
def _allows(role, action):
    """Returns (allowed, needed_layer). The layer for an unknown action is 4,
    so a verb this file has never heard of is refused rather than admitted.

    This answers MAY THEY ATTEMPT IT. It is not the proof itself: layers 3 and
    4 additionally require FlareVault's PIN/TOTP and USB step, which do not
    exist yet. A True here plus a missing proof is still a refusal downstream.
    """
    need = ACTION_LAYER.get(str(action or '').strip().lower(), 4)
    return (_max_layer(role) >= need), need


# 20316708  _visible — the server ids this identity may see, and nothing else
def _visible(claims):
    """THE role gate. Everything else in this file filters through this set.

    master / operator   every server in the fleet, plus this machine.
    client-*            exactly the ids named in the token's `servers` claim,
                        intersected with the fleet so a stale or hopeful claim
                        cannot conjure a row that does not exist.
    anything else       the empty set.

    The intersection direction matters. Iterating the CLAIM and looking each id
    up would let a client probe for existence by watching which ids come back
    populated and which come back empty. Iterating the FLEET and keeping only
    what the claim names produces a set the client cannot use as an oracle: an
    id they do not own and an id that does not exist are both simply absent.
    """
    if not claims:
        return set()
    role = claims.get('role')
    known = set(_fleet.fleet().keys())
    self_id = _id.server_id()
    if self_id:
        known.add(self_id)
    if role in FLEET_ROLES:
        return known
    owned = claims.get(OWNS_CLAIM)
    if not isinstance(owned, (list, tuple)):
        # A client token with no `servers` claim owns nothing. Not everything.
        # This is the single most dangerous line in the file to get backwards.
        return set()
    wanted = {str(s).strip() for s in owned if str(s).strip()}
    return {sid for sid in known if sid in wanted}


# 20316709  _row — one server's summary, shaped for the lobby
def _row(sid, rec):
    """What the lobby list shows per server. Derived from the fleet record,
    which is itself derived from last_seen at read time — so a node that
    stopped beating an hour ago reads as unreachable here without anything
    having to sweep.

    Deliberately NOT included: `path` (which wire the beat came in on) and
    `authenticated` (whether the beat carried a token). Both are facts about
    the mesh's own plumbing, useful at /api/mesh/fleet where an operator is
    looking at the mesh, and noise-or-worse in a room a client can enter.
    """
    status, missed = rec.get('status', ''), rec.get('missed_beats', 0)
    return {
        'server_id':    sid,
        'name':         rec.get('name') or sid,
        'status':       status,
        'missed_beats': missed,
        'last_seen':    rec.get('last_seen'),
        'reachability': rec.get('reachability', []),
        'projects':     rec.get('projects'),
        'containers':   rec.get('containers'),
        # The count, not the list. The list names containers, and a name is a
        # detail that belongs behind the drill-in, not on the front page.
        'attention':    len(rec.get('attention') or []),
        'os':           rec.get('os', ''),
        'uptime':       rec.get('uptime', ''),
        'self':         False,
        'source':       'heartbeat',
    }


# 20316710  _self_row — the central machine's own row
def _self_row():
    """Central runs containers too, and it never beats to itself, so
    kernel.fleet has no record of it. Without this row the operator's fleet
    view is missing the box they are standing on — which reads as "central is
    not a server" rather than "central is the one asking".

    status 'self' rather than 'healthy': this row was read now, not remembered,
    and the two must not be presentable as the same kind of fact.
    """
    return {
        'server_id':    _id.server_id(),
        'name':         _id.node_name(),
        'status':       'self',
        'missed_beats': 0,
        'last_seen':    _now(),
        'reachability': [],
        'projects':     None,
        'containers':   None,
        'attention':    0,
        'os':           '',
        'uptime':       '',
        'self':         True,
        'source':       'derived',
    }


# 20316711  _doors — which doors this role may see at all
def _doors(role):
    """Doors above the role's ceiling are OMITTED, not disabled.

    A greyed-out kill switch tells a client-viewer that a kill switch exists
    and that someone has it. That is the same class of disclosure as a server
    count: information about the system they are not part of. Hidden costs
    nothing and leaks nothing.
    """
    top = _max_layer(role)
    return [{'id': d, 'label': label, 'layer': lvl}
            for (d, label, lvl) in DOORS if lvl <= top]


# 20316712  _target — the node id and sub-action inside one prefix route
def _target(path, prefix):
    """kernel/router.resolve matches on the longest LITERAL prefix, and the id
    sits in the middle of /api/lobby/server/<id>/action — so /action cannot be
    a route entry of its own. Same split registry.py had to make, same reason.

    Returns ('', '') for a bare prefix rather than raising. A missing id is a
    bad request, not a stack trace in the one room every user lands in.
    """
    tail = path.split('?', 1)[0]
    tail = tail[len(prefix):] if tail.startswith(prefix) else tail
    parts = [s for s in tail.strip('/').split('/') if s]
    return ((parts[0].strip() if parts else ''),
            (parts[1].strip().lower() if len(parts) > 1 else ''))


# What the lobby will fetch from another node on an operator's behalf.
#
# Read-only and enumerated. These are the views a fleet operator needs to see
# about a box they are not standing on; each is a GET the node already answers
# and none of them change anything. Adding to this list means deciding that the
# lobby's service token -- which opens EVERY node -- may reach one more place.
PROXY_ALLOW = {
    'node', 'status', 'containers', 'services', 'ports', 'storage',
    'docker/images', 'docker/volumes', 'docker/stats', 'docker/diagnostics',
    'integrations', 'activity', 'incidents', 'events/self', 'manifest',
}


# 20316713  _proxy_node — fetch a node's self-description over a service token
def _proxy_node(node_id, sub='node'):
    """Returns (payload, error_dict). Exactly one of the two is None.

    Rule 6 of the spec: the flareshub-<id> endpoints refuse humans entirely.
    The human is here, in the lobby, and the lobby reaches the node on their
    behalf with a SERVICE token. That is the only reason this function exists —
    without it the operator has nowhere to drill in from, and the alternative
    everyone reaches for is putting a human policy on the node hostname, which
    is precisely what the spec forbids.

    kernel.svctoken owns the token and the URL. This module asks for both at
    call time and keeps neither: no module-level cache, no echo into the
    response, nothing written to the journal. Constitution Law V — the node
    holds pointers, never credentials, and a credential cached in a handler is
    a credential held.

    Import is INSIDE the function on purpose. svctoken is being written in
    parallel; an import at module scope would make this entire file fail to
    load if that file is not on the box yet, and the failure would present as
    "the lobby is gone", not "one dependency is missing".
    """
    try:
        from kernel import svctoken   # noqa: PLC0415
    except Exception as e:
        return None, {'error': 'svctoken_unavailable', 'detail': str(e),
                      'fix': 'kernel/svctoken.py is not deployed on this host — '
                             'check the deploy, then restart the hub'}
    try:
        base = (svctoken.node_url(node_id) or '').rstrip('/')
        headers = svctoken.headers_for(node_id) or {}
    except Exception as e:
        return None, {'error': 'svctoken_failed', 'detail': str(e),
                      'fix': 'the service token for this node could not be '
                             'resolved — check its enrolment with FlareVault'}
    if not base:
        return None, {'error': 'node_url_unknown',
                      'fix': 'FlareVault has no hostname recorded for this node'}
    if not headers:
        # svctoken's stated contract: {} means DO NOT CALL. Calling anyway gets
        # a 302 to a Cloudflare Access login this process can never complete,
        # which arrives back here looking like a network fault — so the
        # operator spends the evening on the tunnel while the real answer is
        # that no service token is stored. Stop here and say which it is.
        return None, {'error': 'no_service_token',
                      'fix': 'no usable Access service token on this host — '
                             'check `python3 -c "from kernel import svctoken; '
                             'print(svctoken.status())"`'}
    if not base.lower().startswith('https://'):
        # A plaintext hop would carry the service token in the clear across
        # whatever sits between here and the node. Refusing is the only safe
        # reading: the token is the credential that makes the whole drill-in
        # work, and one cleartext request is enough to lose it.
        return None, {'error': 'insecure_node_url',
                      'fix': 'node_url must be https — refusing to send a '
                             'service token over plaintext'}
    # PASSTHROUGH, ON AN ALLOWLIST.
    #
    # Without this the lobby proxies /api/node and nothing else, so every view
    # but the picker is refused for a remote server -- which makes the frontend
    # bilateral in name only. The alternative the UI would otherwise reach for
    # is answering from the LOCAL box, silently showing you ksgcohub's
    # containers under a card labelled fks-services. That is the worst bug a
    # fleet UI can have, so the path is opened deliberately here rather than
    # papered over there.
    #
    # An ALLOWLIST, not sanitisation. The lobby holds a credential that opens
    # every node; forwarding an arbitrary caller-supplied path with it is a
    # confused-deputy hole -- the browser cannot reach a node, but it could ask
    # the lobby to. Read-only, no query strings, no traversal, and anything not
    # named here is refused by default rather than filtered.
    if sub not in PROXY_ALLOW:
        return None, {'error': 'remote_path_unsupported', 'path': sub,
                      'allowed': sorted(PROXY_ALLOW),
                      'fix': 'the lobby only proxies read-only views a node '
                             'publishes; writes are a layer-3 step-up and '
                             'belong to FlareVault'}
    req = urllib.request.Request(base + '/api/' + sub, headers=dict(headers))
    try:
        with urllib.request.urlopen(req, timeout=PROXY_TIMEOUT) as r:
            return json.loads(r.read().decode('utf-8')), None
    except urllib.error.HTTPError as e:
        # The node's own refusal, reported as the node's, not reinterpreted.
        # A 403 here means the service token was not accepted, and saying so
        # plainly is the difference between a five-minute fix and an evening.
        return None, {'error': 'node_refused', 'status': e.code,
                      'fix': 'the node rejected the service token — re-issue it '
                             'from FlareVault for this node'}
    except Exception as e:
        return None, {'error': 'node_unreachable', 'detail': str(e),
                      'fix': 'the node did not answer within %ss — check its '
                             'tunnel and its hub service' % PROXY_TIMEOUT}


def _deny(handler, reason, status=401):
    """One shape for every refusal, so the UI has one branch. The reason names
    what is missing, never what exists."""
    handler.send_json({'ok': False, 'error': reason,
                       'door': 'login.flarevault.dev'}, status)


def _not_central(handler):
    """A node is not the lobby. Saying 'not_central' is the honest answer and
    matches what /api/heartbeat already does; returning an empty lobby instead
    would read as 'you have no servers', which is a different and wrong fact.
    """
    handler.send_json({'ok': False, 'error': 'not_central', 'mode': _id.mode(),
                       'lobby': 'dashboard.flarevault.dev'}, 409)


# 20316701  GET /api/lobby — the room, shaped by the role that walked in
def get_lobby(handler, path, params):
    """# 20316701  GET /api/lobby

    What this identity may see: its role, the servers visible to it, and a
    health summary per server. Nothing else exists as far as this response is
    concerned.

    The summary at the bottom is computed over the VISIBLE rows only. Computing
    it over the fleet and then filtering the list would leave the counts
    describing servers the caller must not know about — the classic version of
    this bug is a client seeing `nodes: 7` beside their single row.
    """
    if not _id.is_central():
        _not_central(handler)
        return

    claims, reason = _identity(handler)
    if claims is None:
        _deny(handler, reason)
        return

    role = claims.get('role')
    allowed = _visible(claims)

    rows = []
    self_id = _id.server_id()
    f = _fleet.fleet()
    for sid, rec in f.items():
        if sid in allowed and sid != self_id:
            rows.append(_row(sid, rec))
    if self_id and self_id in allowed:
        rows.append(_self_row())
    rows.sort(key=lambda r: (not r['self'], (r['name'] or '').lower()))

    by_status = {}
    for r in rows:
        by_status[r['status']] = by_status.get(r['status'], 0) + 1

    handler.send_json({
        'ok':        True,
        'mode':      _id.mode(),
        'generated': _now(),
        'identity': {
            # Echoed from the verified token, never from a header or a
            # parameter. The UI renders whoever the token says, so that a
            # spoofed display name is impossible rather than merely unlikely.
            'sub':    claims.get('sub', ''),
            'role':   role,
            'issuer': claims.get('iss', ''),
            'expires': claims.get('exp'),
        },
        'layer': {
            'max':      _max_layer(role),
            'enforced': [1, 2],
            # Said out loud because the UI must not offer what nothing checks.
            'pending':  {'3': 'FlareVault: PIN / TOTP step-up',
                         '4': 'FlareVault: USB + PIN vault'},
        },
        'doors':   _doors(role),
        'servers': rows,
        'summary': {'servers': len(rows), 'by_status': by_status},
    })


# 20316702  GET /api/lobby/server/<id> — drill in, via the service token
def get_lobby_server(handler, path, params):
    """# 20316702  GET /api/lobby/server/<id>

    The operator drills into a node. The lobby proxies to that node's /api/node
    with a service token, because the node endpoint refuses humans by design.

    A server this caller may not see returns 404, NOT 403. 403 means "it is
    there and you cannot have it" — which answers the one question a client
    must never be able to ask. An id they do not own and an id that was never
    minted produce byte-identical responses.

    The read itself is layer 1, not 2. A client-viewer drilling into their own
    server is reading the same facts the lobby row already summarised, one
    level of detail deeper; refusing it would leave the read-only role with a
    lobby it cannot use. Layer 2 begins where CONTROLS begin, and the `can`
    block below is what the UI renders buttons from.
    """
    if not _id.is_central():
        _not_central(handler)
        return

    claims, reason = _identity(handler)
    if claims is None:
        _deny(handler, reason)
        return

    node_id, _action = _target(path, '/api/lobby/server/')
    role = claims.get('role')
    allowed = _visible(claims)

    # Both failures answer the same way, on purpose: a malformed id and an
    # unowned one are indistinguishable from outside.
    if not node_id or not _ID_OK.match(node_id) or node_id not in allowed:
        handler.send_json({'ok': False, 'error': 'no_such_server'}, 404)
        return

    self_id = _id.server_id()
    can = {name: _allows(role, name)[0]
           for name in ('logs', 'console', 'containers', 'restart', 'vault')}

    # ?view= names which of the node's read-only views to fetch. Default is
    # its self-description, so the existing drill-in call is unchanged.
    sub = (params.get('view') or 'node').strip().strip('/')

    if node_id == self_id:
        # Central describing itself. Reading its own node payload locally is
        # not a proxy hop, and pretending otherwise (looping through its own
        # public hostname and service token) would make the lobby depend on
        # its own tunnel being up to describe the machine it is running on.
        #
        # For any other view of itself the caller should just call /api/<view>
        # directly -- it is the same origin. Saying so beats quietly proxying
        # the local box to itself and burning a tunnel round trip.
        if sub != 'node':
            handler.send_json({'ok': False, 'server': _self_row(), 'can': can,
                               'source': 'derived',
                               'finding': {'error': 'self_is_local',
                                           'fix': 'this is the box you are '
                                                  'already talking to — call '
                                                  '/api/%s directly' % sub}}, 400)
            return
        try:
            from handlers.node import node_payload   # noqa: PLC0415
            payload, err = node_payload(), None
        except Exception as e:
            payload, err = None, {'error': 'self_read_failed', 'detail': str(e)}
        source = 'derived'
    else:
        payload, err = _proxy_node(node_id, sub)
        source = 'proxy'

    rec = _fleet.fleet().get(node_id) or {}
    server = _self_row() if node_id == self_id else _row(node_id, rec)

    if err is not None:
        # Report, never repair. The finding and the command go back; nothing
        # retries, and nothing here decides the node is fine after all.
        handler.send_json({'ok': False, 'server': server, 'can': can,
                           'source': source, 'finding': err}, 502)
        return

    try:
        from kernel.db import db_conn          # noqa: PLC0415
        from kernel.log import log_activity    # noqa: PLC0415
        log_activity(db_conn,
                     'lobby: %s (%s) opened %s' % (claims.get('sub', '?'), role,
                                                   server.get('name') or node_id),
                     'lobby', 'server', node_id, 'info')
    except Exception:
        # An audit line that cannot be written must not take the drill-in down.
        # It is recorded as missing by its absence, which is the honest state.
        pass

    handler.send_json({'ok': True, 'generated': _now(), 'source': source,
                       'server': server, 'can': can, 'node': payload})


# 20316703  POST /api/lobby/server/<id>/action — layer 3 seam, deliberately empty
def post_lobby_action(handler, path, params, body):
    """# 20316703  POST /api/lobby/server/<id>/action

    THE SEAM, NOT THE ACTION. Start, stop, restart and prune are layer 3: they
    require a step-up proof (PIN / TOTP) that FlareVault owns and has not
    built. This endpoint exists so the UI has a stable URL and a truthful
    answer, and it returns 501 with the owner named.

    It still runs the full visibility and role check first, and in that order.
    Answering 'not implemented' to a caller who may not see the server would
    confirm the server exists — the 501 must sit BEHIND the 404, not in front
    of it.
    """
    if not _id.is_central():
        _not_central(handler)
        return

    claims, reason = _identity(handler)
    if claims is None:
        _deny(handler, reason)
        return

    node_id, _sub = _target(path, '/api/lobby/server/')
    role = claims.get('role')
    if not node_id or not _ID_OK.match(node_id) or node_id not in _visible(claims):
        handler.send_json({'ok': False, 'error': 'no_such_server'}, 404)
        return

    action = str((body or {}).get('action', '')).strip().lower()
    if action not in ACTION_LAYER:
        # An unknown verb is a bad request, and must say so. Letting it fall
        # through to the 501 below would answer 'FlareVault has not built that
        # yet' about an action nobody has ever defined — a wrong answer that
        # sends the reader to the wrong system.
        handler.send_json({'ok': False, 'error': 'unknown_action',
                           'action': action or None,
                           'known': sorted(ACTION_LAYER)}, 400)
        return
    ok, need = _allows(role, action)
    if not ok:
        # The role's ceiling is below this action. That is a real refusal and
        # it is this hub's to make — it does not depend on the missing L3 proof.
        handler.send_json({'ok': False, 'error': 'insufficient_layer',
                           'action': action or None, 'needs_layer': need,
                           'your_layer': _max_layer(role)}, 403)
        return

    handler.send_json({
        'ok': False,
        'error': 'not_implemented',
        'action': action,
        'needs_layer': need,
        'owner': 'FlareVault',
        'detail': 'layer 3 step-up (PIN / TOTP) is FlareVault\'s to implement. '
                  'ServerHub provides this seam and performs no destructive '
                  'action without that proof.',
    }, 501)


# 20316704  POST /api/lobby/vault — layer 4 seam, deliberately empty
def post_lobby_vault(handler, path, params, body):
    """# 20316704  POST /api/lobby/vault

    The vault and the kill switch. Layer 4, USB + PIN, entirely FlareVault's.

    Constitution Law V says credentials are never here, so this is not a stub
    waiting to be filled in on this side — there is nothing for ServerHub to
    implement behind it. The seam exists so the lobby can render a door for the
    roles that have one and get a clear answer when it is pushed, rather than a
    404 that reads as "this feature was removed".
    """
    if not _id.is_central():
        _not_central(handler)
        return

    claims, reason = _identity(handler)
    if claims is None:
        _deny(handler, reason)
        return

    role = claims.get('role')
    ok, need = _allows(role, 'vault')
    if not ok:
        handler.send_json({'ok': False, 'error': 'insufficient_layer',
                           'needs_layer': need,
                           'your_layer': _max_layer(role)}, 403)
        return

    handler.send_json({
        'ok': False,
        'error': 'not_implemented',
        'needs_layer': 4,
        'owner': 'FlareVault',
        'detail': 'the vault and kill switch live with the authority. '
                  'ServerHub holds pointers, never credentials '
                  '(CONSTITUTION law V), so there is nothing here to build.',
    }, 501)
