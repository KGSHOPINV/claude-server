#!/usr/bin/env python3
"""
# 20200011  kernel.fleet — the fleet registry and status state machine

THE ZONE IS THE FLEET REGISTER. Corrected 2026-09-26.

This file used to open by declaring hub-and-spoke: "central is the only
aggregator", "node -> node NEVER, no lateral mesh". That was wrong, and it was
wrong in the expensive direction — it made one box a single point of failure
for the ability to SEE the fleet, and it invented a hierarchy nobody asked for.

The entry is the centre. Every server is a node. Nobody is special.

What makes that work was already true and merely unused: enroll.sh publishes
every node at a hostname DERIVED FROM ITS OWN SERVER ID,

    flareshub-<server-id-with-underscore-as-hyphen>.<zone>

so listing `flareshub-*` on the zone ENUMERATES THE FLEET. No heartbeat, no
election, no central box, no agreement to maintain. Confirmed live against
flarevault.dev on 2026-09-26: two records, flareshub-fvn-3b8c1b and
flareshub-fvn-685a59. The register is the thing the fleet is already built on.

So the registry now has TWO sources, and they answer different questions:

    zone DNS        WHO EXISTS.   Authoritative, no peer's cooperation needed.
    heartbeats      WHAT IS TRUE NOW.  Live payload: containers, projects,
                    attention, os, uptime. Enrichment, never the register.

A node known only from DNS is `enrolled`: we know it exists and we have never
heard from it. It is never `healthy` — DISCOVERING THAT A NODE EXISTS IS NOT A
CLAIM ABOUT ITS HEALTH, and collapsing those two would turn the register into
the same kind of lie a stuck sweeper produces.

A BEAT IS BOUND TO THE RECORD IT CLAIMS. Corrected 2026-09-27.

"There is still only ever one writer of a node's state: that node" was the rule
and it was not enforced. The sid came entirely from the request body and
`heartbeat()` did `_fleet.get(sid, {...default...})`, so anything that could
reach :8765 could overwrite any node's row or invent a node that does not
exist — and `register()` persisted while `heartbeat()` did not, which made the
DURABLE half of the fleet the half whose key the caller picked.

Two changes make the rule true with what already exists, and no new credential:

    register()   is now the ONLY thing that creates a record. It requires a
                 machine_id, because that is what later beats are checked
                 against, and it refuses to rekey a known server_id from the
                 body.
    heartbeat()  refuses an unknown server_id outright, and refuses a beat whose
                 machine_id is not the one the record was registered with. It
                 persists, so both halves are now durable and both are bound.

See _bound for what each arrival path ends up trusting, and why the Cloudflare
edge identity is checked where present but can never be required.

WHAT IS STILL TRUE. Nothing here writes to another box, ever. The lateral call
this file enables is a READ, and only the read the lobby already made:
kernel/svctoken.py's headers_for/node_url, over Cloudflare, service token only.
"No lateral mesh" was a rule about state; it is now a rule about WRITES, which
is the part that actually prevented split-brain. There is still only ever one
writer of a node's state: that node.

Status is DERIVED from last_seen on every read rather than written by a
sweeper. A timer that stops running would otherwise leave every node frozen at
"healthy" — the failure mode where the monitor lies rather than alarms.

PERSISTED, as of 2026-09-25. It used to be memory only, on the reasoning that
losing the registry costs one heartbeat interval because every node re-reports
within 30s. That is true and it is still the worst case -- but during a working
session it meant a node that had been healthy for hours vanished on every hub
restart, and a drill-in to it answered 404 no_such_server. Three separate times
that looked like a broken product rather than a 30-second window.

Status is still DERIVED on read, so a restored record cannot lie: a node that
stopped beating while central was down comes back as degraded or unreachable
on the first read, exactly as it would have without persistence. What is
restored is the KNOWLEDGE that the node exists, never a claim about its health.
"""
import json
import os
import re
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone

HEARTBEAT_INTERVAL = 30          # seconds; nodes push on this cadence
DEGRADED_AFTER = 3               # missed beats
UNREACHABLE_AFTER = 6            # missed beats

ENROLLING = 'enrolling'
HEALTHY = 'healthy'
DEGRADED = 'degraded'
UNREACHABLE = 'unreachable'
RECOVERING = 'recovering'

# Known from the zone, never heard from. Distinct from ENROLLING, which means
# "it announced itself and its first beat has not landed yet" — a node that has
# begun talking to us. ENROLLED means we found it in the register and it has
# said nothing at all, which may be permanent and is not a fault.
ENROLLED = 'enrolled'

_fleet = {}                      # server_id -> record, written by heartbeats
_lock = threading.Lock()

# ── Storage findings carried from a beat ──────────────────────────────────────
# Only these two reach the fleet record. `info` findings are shape advice
# ("docker keeps images on / while the big disk sits idle") — true, worth
# acting on, and not a reason to mark a node as wanting a human. A flag that
# fires on every correctly-built node is one operators learn to scroll past.
# Ordered worst-first, and the order is load-bearing: see storage_flags.
STORAGE_SEVERITIES = ('high', 'warn')

# Both bounds exist because a beat is input from a machine central does not
# control. kernel.storage has four rules today, so four is a bound and not an
# expectation; a node with a broken rule could otherwise put an unbounded list
# of unbounded strings into every fleet read.
STORAGE_FLAG_MAX = 4
STORAGE_DETAIL_MAX = 160         # chars; a flag is a pointer, not the report

# ── Zone discovery ───────────────────────────────────────────────────────────
CF_API = 'https://api.cloudflare.com/client/v4'
DISCOVERY_TTL = 300             # seconds; the register changes at enrolment pace
DISCOVERY_TIMEOUT = 8           # one read must not hold a page open
DISCOVERY_MAX_PAGES = 10        # 1000 records; a bound, not an expectation

# The escape hatch, because a box that must not make outbound API calls is a
# legitimate configuration and should not have to have its zone taken away to
# get there. Unset means on.
DISCOVERY_ON = os.environ.get('HUB_FLEET_DISCOVERY', '1').strip() != '0'

_disc = {'at': 0.0, 'nodes': {}, 'meta': None}
_disc_lock = threading.Lock()

# Beside control.db: this is what central knows about the fleet, and it belongs
# with the other things that cannot be re-derived from this box alone.
_BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATE_FILE = os.environ.get(
    'HUB_FLEET_STATE', os.path.join(os.path.dirname(_BASE), 'db', 'fleet.json'))
_loaded = False


# 20200336  _persist — write the registry, atomically
def _persist():
    """Called with the lock held. Best effort: a fleet that cannot be written
    is not a reason to drop a heartbeat, so failure is silent here and visible
    in the next read returning less than expected."""
    try:
        os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
        tmp = STATE_FILE + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(_fleet, f)
        os.replace(tmp, STATE_FILE)      # atomic; a torn file reads as no file
    except Exception:
        pass


# 20200337  _restore — load it once, on first use
def _restore():
    global _loaded
    if _loaded:
        return
    _loaded = True
    try:
        with open(STATE_FILE, encoding='utf-8') as f:
            data = json.load(f)
        if isinstance(data, dict):
            _fleet.update(data)
    except Exception:
        pass


def _now():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


# 20200316  _bound — is this beat entitled to the record it is claiming
def _bound(sid, rec, claimed_machine, edge_identity):
    """Returns (True, via) or (False, refusal). `via` names WHAT was checked.

    THE KEY USED TO COME ENTIRELY FROM THE BODY. A beat said `server_id: X` and
    this module wrote X's row, so anything that could reach :8765 could rewrite
    any node's row or invent a node that does not exist. Nothing bound the
    caller to the key it supplied.

    There is no join token to check — that is FlareVault's and it does not
    exist yet (see handlers/mesh.py, the seam). So the binding is built from
    what every record and every beat ALREADY carries:

      machine_id     the key on the thing that does not change. This project
                     learned that lesson when peers were keyed by URL and every
                     box that moved became a dead peer. A record's machine_id is
                     written by an explicit registration; a beat claiming that
                     record has to carry the same one.

      edge identity  Cloudflare Access forwards a service token's common_name
                     (kernel/auth.service_identity). A beat arriving over the
                     edge carries one; over tailscale or LAN there is none to
                     carry. So it is checked when the record HAS one recorded
                     and the beat presents one, and it is never required —
                     requiring it would refuse the tailnet path, which is the
                     failsafe the whole fallback chain exists for.

    A refusal is a dict rather than a sentence because the two kinds are not the
    same answer: a malformed beat is the sender's bug, and a beat claiming a
    record it cannot prove is a refusal. Flattening them into one string would
    lose the distinction the receiver needs to answer 400 or 403.
    """
    if rec is None:
        # THE "INVENT A NODE" HOLE, CLOSED. Registration is an explicit act with
        # its own endpoint; a beat is a report about a record that already
        # exists. Creating from a beat meant a typo and an intrusion produced
        # the identical result: a new, healthy-looking node.
        return False, {
            'error': 'unknown_server_id',
            'detail': 'no server %s is registered here, and a beat does not '
                      'create a fleet record' % sid,
            'fix': 'POST /api/mesh/register {"server_id":"%s","name":"...",'
                   '"machine_id":"..."} from that box first' % sid}
    known = (rec.get('machine_id') or '').strip()
    if not known:
        # A record with no machine_id cannot vouch for anything, and adopting
        # the first machine_id that turns up would hand the row to whoever beats
        # first. Re-registration is the way back, and it says so.
        return False, {
            'error': 'record_unbound',
            'detail': 'server %s was recorded without a machine_id, so no beat '
                      'can be bound to it' % sid,
            'fix': 'POST /api/mesh/register from that box to bind the record to '
                   'its machine_id'}
    if not claimed_machine:
        return False, {
            'error': 'machine_id_required',
            'detail': 'server %s is registered to machine %s, and this beat '
                      'carries no machine_id' % (sid, known),
            'fix': "the beat payload is the node's /api/node response, which "
                   'already contains machine_id — send it unchanged'}
    if claimed_machine != known:
        # Shaped like outbox.acknowledge's refusal on purpose: name the record,
        # name what it says, name what was presented.
        return False, {
            'error': 'machine_id_mismatch',
            'detail': 'server %s is registered to machine %s, not %s'
                      % (sid, known, claimed_machine),
            'fix': 'if that box was reprovisioned, POST /api/mesh/register from '
                   'it — a beat must not silently rekey a record'}
    via = 'machine_id'
    recorded_edge = (rec.get('edge_identity') or '').strip()
    if recorded_edge and edge_identity:
        if recorded_edge != edge_identity:
            return False, {
                'error': 'edge_identity_mismatch',
                'detail': 'server %s registered from edge identity %s, and this '
                          'beat arrived as %s'
                          % (sid, recorded_edge, edge_identity),
                'fix': 'a changed service token needs a fresh '
                       'POST /api/mesh/register from that box'}
        via = 'edge+machine_id'
    return True, via


# 20200331  register — a node joins the mesh
def register(server_id, name, machine_id, reachability=None, edge_identity=None):
    """Returns (record, note). `note` flags anything an operator should see.

    THE ONE PLACE A FLEET RECORD IS CREATED. Beats no longer create one; see
    _bound. So this is where the binding a beat will later be held to gets
    written, which is why a registration WITHOUT a machine_id is now refused: it
    would write a record no beat could ever prove it owns.

    A known server_id re-registering (a reimage or a restart) is still fine, but
    it may NOT rekey the record from the body — that is the same caller-supplied
    key hole one endpoint over. A box whose machine_id genuinely changed
    registers under the new one after the old record is removed, and the refusal
    says so rather than leaving an operator to guess.

    Two situations stay notes rather than refusals, because both are legitimate
    and both are worth an operator seeing: a re-registration, and a known
    machine_id arriving under a DIFFERENT server_id — the same physical box
    claiming a new identity. The second cannot overwrite anybody: it keys a new
    row.
    """
    _restore()
    if not server_id:
        return None, 'server_id required'
    machine_id = (machine_id or '').strip()
    if not machine_id:
        return None, ("machine_id required — the fleet binds a node's beats to "
                      'its machine_id, and a record without one can never '
                      'accept one')
    note = None
    with _lock:
        prior = _fleet.get(server_id)
        if prior:
            known = (prior.get('machine_id') or '').strip()
            if known and known != machine_id:
                return None, ('server %s is registered to machine %s, not %s — '
                              'remove the old record before rekeying it'
                              % (server_id, known, machine_id))
            if known:
                note = 're-registration of a known server_id'
            else:
                # A row from before beats were bound. Binding it is the only way
                # to make it usable again, and it is said out loud because this
                # is the one moment a binding is CHOSEN rather than checked.
                note = ('server %s had no machine_id recorded; this registration '
                        'bound it to %s' % (server_id, machine_id))
        else:
            for sid, rec in _fleet.items():
                if rec.get('machine_id') == machine_id:
                    note = (f'machine_id already registered as {sid} — same hardware, '
                            f'new server_id (reimage or reprovision?)')
                    break
        rec = prior or {}
        rec.update({
            'server_id':    server_id,
            'name':         name or rec.get('name', ''),
            'machine_id':   machine_id,
            'reachability': reachability or rec.get('reachability', []),
            'registered':   rec.get('registered', _now()),
            'status':       rec.get('status', ENROLLING),
            'last_seen':    rec.get('last_seen'),
            'path':         rec.get('path'),
            'misses':       rec.get('misses', 0),
        })
        # Recorded only when the registration actually arrived over the edge. An
        # absent value must stay absent rather than be written as '', or a box
        # that registered over tailscale would look like one whose edge identity
        # is empty, and _bound would have two states to tell apart where there
        # is only one fact.
        if edge_identity:
            rec['edge_identity'] = edge_identity
        _fleet[server_id] = rec
        _persist()
        return dict(rec), note


# 20200315  storage_flags — a node's storage findings, as fleet attention
def storage_flags(findings):
    """`findings` is attention.storage from a node's /api/node payload.

    WHY THIS EXISTS. handlers/node.py puts kernel.storage.landscape()
    ['findings'] into attention.storage precisely so an authority can see which
    nodes are quietly filling their disks, and /api/node IS the heartbeat
    payload — so the answer already travelled to central on every beat. It then
    died at the door, because heartbeat() copied two of the four attention keys
    and dropped this one. The question was answerable for the box you were
    already standing on and for no other, which is the exact thing a heartbeat
    exists to avoid.

    WHAT IS KEPT, AND WHY IT IS NOT A SECOND COPY. Severity and detail only —
    never the `fix` command, never the mounts, never the landscape. A flag is a
    pointer at the node's own /api/node, which owns the report; central storing
    the report would be the two-sources bug _record_registry in handlers/mesh.py
    refuses to commit, and between beats central's copy would be wrong besides.
    Attention flags are the one thing the fleet record already carries on the
    node's behalf, so this rides an existing channel rather than opening one.

    BOUNDED TWICE, and it says so when a bound bites. A truncated list that
    looked complete would be worse than no list: the node's own total is
    reported instead, the same rule _record_registry applies when it prefers a
    node's count over a recount of a list the node truncated.
    """
    if not isinstance(findings, list):
        # A node that sent a dict, a string or nothing is not a node with no
        # findings, but there is nothing here to read. Silence beats inventing
        # a flag, and /api/node still answers for that box directly.
        return []

    ranked = []
    for f in findings:
        if not isinstance(f, dict):
            continue
        sev = str(f.get('severity', '')).strip().lower()
        if sev not in STORAGE_SEVERITIES:
            continue
        # Collapse whitespace: a detail with a newline in it would break the
        # one-line-per-flag shape every other consumer of this list assumes.
        detail = ' '.join(str(f.get('detail', '')).split())
        if not detail:
            # An id is a poor sentence and a fine pointer. Better than a flag
            # that says a severity and nothing about what triggered it.
            detail = str(f.get('id', '')).strip() or 'unspecified finding'
        if len(detail) > STORAGE_DETAIL_MAX:
            detail = detail[:STORAGE_DETAIL_MAX - 1] + '…'
        ranked.append((STORAGE_SEVERITIES.index(sev), f'storage {sev}: {detail}'))

    # Worst first, so when the bound bites it is an `info`-adjacent warn that
    # falls off the end and never the finding that says the disk is full.
    # Python's sort is stable, so findings of equal severity keep the order the
    # node listed them in — that order is the node's, not ours to reshuffle.
    ranked.sort(key=lambda r: r[0])
    out = [flag for _, flag in ranked[:STORAGE_FLAG_MAX]]
    dropped = len(ranked) - len(out)
    if dropped:
        out.append(f'storage: {dropped} more finding(s) — see /api/node on that node')
    return out


# 20200332  heartbeat — record a beat, return any transition worth logging
def heartbeat(payload, path='unknown', authenticated=False, edge_identity=None):
    """payload is the node's /api/node response, unchanged.

    Returns (record, event) when the beat is ACCEPTED, where event is a
    human-readable transition or None. Returns (None, refusal) when it is not,
    and refusal is a dict — see _bound for why a refusal is structured.

    A BEAT IS A REPORT ABOUT A RECORD THAT ALREADY EXISTS, never the thing that
    creates one. It used to be `_fleet.get(sid, {...default...})`, so any id
    that arrived got a row: the fleet view could be grown, or any node's row
    overwritten, by anything that could reach this port.

    Two things are events: a status change, and a PATH change — a node that fell
    back from cloudflare to tailscale is still up, but the fact it had to is
    exactly the sort of quiet degradation that otherwise goes unseen.
    """
    _restore()
    sid = payload.get('server_id') or payload.get('machine_id')
    if not sid:
        return None, {'error': 'no_identity',
                      'detail': 'heartbeat without server_id or machine_id',
                      'fix': "send the node's /api/node response unchanged"}

    with _lock:
        rec = _fleet.get(sid)
        ok, verdict = _bound(sid, rec, (payload.get('machine_id') or '').strip(),
                             edge_identity)
        if not ok:
            return None, verdict
        prev_status = rec.get('status', ENROLLING)
        prev_path = rec.get('path')

        # Coming back from a bad state announces itself once, then settles.
        if prev_status in (DEGRADED, UNREACHABLE):
            new_status = RECOVERING
        else:
            new_status = HEALTHY

        attention = payload.get('attention') or {}
        flags = []
        for c in attention.get('unassigned_containers', []) or []:
            flags.append(f'unassigned: {c}')
        if attention.get('not_enrolled'):
            flags.append('not enrolled')
        # Storage last, because the flags above name a container and this one
        # describes the box. See storage_flags for what is kept and what is
        # deliberately left with the node.
        flags.extend(storage_flags(attention.get('storage')))

        reach = [k for k, v in (
            ('lan', payload.get('local_ip')),
            ('tailscale', payload.get('tailscale_ip')),
            ('public', payload.get('public')),
        ) if v]

        rec.update({
            'name':          payload.get('node') or payload.get('hostname') or rec.get('name', ''),
            # machine_id is NOT taken from the payload any more. _bound has
            # already proved this beat carries the one the record was registered
            # with, so a write here could only ever be a no-op — and a write is
            # how a body-supplied value finds its way back in.
            'status':        new_status,
            'last_seen':     _now(),
            'path':          path,
            # Still means exactly what it always meant: the beat carried a
            # FlareVault-style join token this box could verify. It is NOT the
            # binding — `bound_by` is — and the two stay apart so that the day a
            # real token exists, nothing has to be un-taught.
            'authenticated': authenticated,
            # What this beat was actually held to. An operator reading a row
            # should not have to infer it from which fields happen to be there.
            'bound_by':      verdict,
            'reachability':  reach,
            'containers':    sum(len(p.get('containers', [])) for p in payload.get('projects', [])),
            'projects':      len(payload.get('projects', [])),
            'attention':     flags,
            'os':            payload.get('os', ''),
            'uptime':        payload.get('uptime', ''),
            'misses':        0,
        })
        _fleet[sid] = rec
        # register() persisted and heartbeat() did not, so the DURABLE half of
        # the fleet was the half whose key the caller picked. Both halves are
        # bound now, and both are written: a restart must not come back holding
        # only the record shape this file used to trust least.
        _persist()

        event = None
        if prev_status != new_status:
            event = f'{rec["name"] or sid}: {prev_status} -> {new_status}'
        elif prev_path and prev_path != path:
            event = f'{rec["name"] or sid}: heartbeat path changed {prev_path} -> {path}'
        return dict(rec), event


# 20200333  _derive_status — staleness decides status, computed at read time
def _derive_status(rec):
    last = rec.get('last_seen')
    if not last:
        return rec.get('status', ENROLLING), 0
    try:
        seen = datetime.fromisoformat(last)
        age = (datetime.now(timezone.utc) - seen).total_seconds()
    except Exception:
        return rec.get('status', ENROLLING), 0
    # Clamp: a future-dated last_seen (clock skew between node and central)
    # would otherwise yield negative misses and silently report healthy.
    missed = max(0, int(age // HEARTBEAT_INTERVAL))
    if missed >= UNREACHABLE_AFTER:
        return UNREACHABLE, missed
    if missed >= DEGRADED_AFTER:
        return DEGRADED, missed
    # A node that reported while RECOVERING settles to HEALTHY on the next read.
    if rec.get('status') == RECOVERING:
        return HEALTHY, missed
    return rec.get('status', HEALTHY), missed


# 20200346  _cf_token — the same places enroll.sh looks, and the VALUE NEVER LEAVES
def _cf_token():
    """Returns (token, source). `source` names $CF_API_TOKEN or a file PATH and
    is safe to put in an API response; the token itself is used here and goes
    nowhere else — not into a return value a handler renders, not into a log
    line, not into an exception message.

    The same three places enroll.sh, cf-check.py, situation.py and tracks.py
    look, written out again rather than imported because those are all in
    hub/tools/ and tools import kernel, never the other way round. Reversing
    that for four lines would put a diagnostic tool on the hub's startup path.
    """
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


# 20200347  _cf_get — one Cloudflare read. GET only, structurally.
def _cf_get(token, path, timeout=DISCOVERY_TIMEOUT):
    """Returns (body, why). Exactly one is falsy.

    No method parameter, the same shape situation.py's _cf has and for the same
    reason: this module cannot be edited into something that writes by passing
    a string. Discovering the fleet must not be able to change it.

    `why` is a short human sentence. It never contains the token — the only
    place the token appears is the Authorization header built two lines down.
    """
    if not token:
        return None, 'no Cloudflare API token on this box'
    req = urllib.request.Request(
        CF_API + path,
        headers={'Authorization': 'Bearer ' + token,
                 'Content-Type': 'application/json',
                 # Same reason as kernel/svctoken.USER_AGENT: anything this
                 # project sends through Cloudflare identifies itself.
                 'User-Agent': 'FlareSHub-Fleet/1.0'})
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


# 20200348  _id_from_hostname — a zone record back to the server id that made it
def _id_from_hostname(host, zone):
    """'flareshub-fvn-3b8c1b.flarevault.dev' -> 'fvn_3b8c1b', or ''.

    THE REVERSE OF svctoken.node_url, AND VERIFIED AS SUCH. The forward
    direction lowercases the id and swaps '_' for '-' (svctoken._label). This
    undoes the swap on the FIRST hyphen and then runs the candidate back
    through _label, requiring it to reproduce the label we were given. A
    reverse mapping that is not checked against the forward one is how the
    lobby ends up addressing a hostname no node answers to.

    AMBIGUITY, STATED. 'fvn-a-b' has more than one preimage ('fvn_a-b' and
    'fvn_a_b' both map to it), and this returns the first-hyphen one. It does
    not bite because a FlareVault id is 'fvn_' plus six hex characters — one
    underscore, in one place. If ids ever grow a second, the register must
    carry the id rather than only the name it was built from, and this function
    is where that would be read.

    '' is the refusal, and it is also the correct answer for every OTHER record
    in the zone: the apex, www, a mail record. Those are not nodes.
    """
    try:
        from kernel import svctoken as _svc    # noqa: PLC0415
        h = str(host or '').strip().rstrip('.').lower()
        z = str(zone or '').strip().rstrip('.').lower()
        if not h or not z or not h.endswith('.' + z):
            return ''
        label = h[:-(len(z) + 1)]
        pref = _svc.hostname_prefix()
        if not label.startswith(pref):
            return ''
        rest = label[len(pref):]
        if not rest:
            return ''
        candidate = rest.replace('-', '_', 1)
        # The round trip. If this does not hold, we cannot address the node we
        # think we found, so we have not found it.
        return candidate if _svc._label(candidate) == rest else ''
    except Exception:
        return ''


# 20200349  discover — enumerate the fleet from the zone, with no peer's help
def discover(force=False):
    """Returns (nodes, meta). Never raises, never writes, never persists.

    nodes is {server_id: record} for every `flareshub-*` record on this box's
    zone EXCEPT this box's own id. Each record says only what DNS can support:
    the id, the hostname, and where it came from. No status beyond `enrolled`,
    no last_seen, no reachability — a CNAME existing is not a claim that
    anything answers on it, and writing one in would be inventing health.

    THIS BOX IS EXCLUDED on purpose. A row reading "we have never heard from
    the machine we are running on" is true and useless; the lobby already
    derives its own row live (handlers/lobby._self_row), which is a better fact
    than a remembered one.

    meta is safe to render. It carries `cf_token_source` — a path or the name of
    an environment variable, NEVER the value — because "there is no token" and
    "the token cannot see this zone" send an operator to two different places.

    Cached for DISCOVERY_TTL, FAILURES INCLUDED. A box with no token would
    otherwise attempt an outbound call on every read of the fleet and answer
    slowly forever; caching the refusal makes the cost of being unconfigured
    one call per five minutes instead of one per page.
    """
    now = time.time()
    with _disc_lock:
        if (not force and _disc['meta'] is not None
                and (now - _disc['at']) < DISCOVERY_TTL):
            m = dict(_disc['meta'])
            m['cached'] = True
            return dict(_disc['nodes']), m

    nodes = {}
    meta = {'ok': False, 'source': 'zone-dns', 'zone': '',
            'cf_token_source': None, 'records': 0, 'nodes': 0,
            'checked': _now(), 'cached': False, 'why': None, 'fix': None}

    def _done():
        meta['nodes'] = len(nodes)
        with _disc_lock:
            _disc['at'] = time.time()
            _disc['nodes'] = dict(nodes)
            _disc['meta'] = dict(meta)
        return dict(nodes), dict(meta)

    if not DISCOVERY_ON:
        meta['source'] = None
        meta['why'] = 'zone discovery is switched off (HUB_FLEET_DISCOVERY=0)'
        meta['fix'] = 'unset HUB_FLEET_DISCOVERY to let this box read the register'
        return _done()

    try:
        from kernel import svctoken as _svc    # noqa: PLC0415
        zone = _svc.zone()
    except Exception as e:
        meta['why'] = 'the zone could not be read on this box: %s' % str(e)[:80]
        meta['fix'] = 'check kernel/svctoken.py is deployed, then restart the hub'
        return _done()

    meta['zone'] = zone
    if not zone:
        # The honest refusal, and the common one: this box has never been
        # enrolled, so nothing has written ~/.flare/node.json and no
        # environment names a zone. It is a state, not a fault.
        meta['why'] = ('this box has no zone, so it cannot name the register '
                       '(no ~/.flare/node.json and no FLARE_ZONE)')
        meta['fix'] = ('enroll this box: ./enroll.sh --node <name> --zone <zone>, '
                       'or set FLARE_ZONE=<zone> if it is enrolled elsewhere')
        return _done()

    token, src = _cf_token()
    meta['cf_token_source'] = src or None
    if not token:
        meta['why'] = ('no Cloudflare API token on this box, so the zone\'s DNS '
                       'records cannot be listed')
        meta['fix'] = ('set CF_API_TOKEN, or write ~/.cf-token (chmod 600) with a '
                       'token holding Zone:DNS:Read on ' + zone)
        return _done()

    body, why = _cf_get(token, '/zones?name=' + zone)
    if not body:
        meta['why'] = 'zone lookup failed: %s' % why
        meta['fix'] = ('the token named by cf_token_source cannot read zone %s — '
                       'check its Zone:DNS:Read scope' % zone)
        return _done()
    result = (body or {}).get('result') or []
    if not result:
        meta['why'] = 'zone %s is not visible to this token' % zone
        meta['fix'] = 'check the token\'s zone scope, or the zone name on this box'
        return _done()
    zone_id = str((result[0] or {}).get('id') or '')
    if not zone_id:
        meta['why'] = 'zone %s resolved to no id' % zone
        return _done()

    # PAGED, and bounded. A zone larger than DISCOVERY_MAX_PAGES pages reports
    # what it read and says it was truncated, rather than looking complete.
    page = 1
    while page <= DISCOVERY_MAX_PAGES:
        body, why = _cf_get(
            token, '/zones/%s/dns_records?per_page=100&page=%d' % (zone_id, page))
        if not body:
            meta['why'] = 'DNS listing failed on page %d: %s' % (page, why)
            meta['fix'] = ('the token can see zone %s but not its DNS records — '
                           'it needs Zone:DNS:Read' % zone)
            return _done()
        recs = (body or {}).get('result') or []
        meta['records'] += len(recs)
        for r in recs:
            sid = _id_from_hostname((r or {}).get('name'), zone)
            if not sid:
                continue
            nodes[sid] = {
                'server_id': sid,
                'hostname':  str((r or {}).get('name') or ''),
                'source':    'zone',
                'status':    ENROLLED,
                # Said explicitly rather than left absent, because _derive_status
                # reads last_seen and "never" must not be confused with "stale".
                'last_seen': None,
                'misses':    0,
            }
        info = (body or {}).get('result_info') or {}
        total_pages = int(info.get('total_pages') or 1)
        if page >= total_pages:
            break
        page += 1
    else:
        meta['why'] = ('stopped after %d pages — the register may be incomplete'
                       % DISCOVERY_MAX_PAGES)

    # This box is in its own register. It is not news.
    try:
        from kernel import identity as _idm    # noqa: PLC0415
        nodes.pop(_idm.server_id(), None)
    except Exception:
        pass

    meta['ok'] = True
    return _done()


# 20200334  fleet — full state for the UI
def fleet():
    """Heartbeat records and zone discovery, merged. Status stays DERIVED.

    THE MERGE RULE, and it only goes one way: DNS may add a node, and may never
    change what a node said about itself. A record that has been heard from
    keeps its own status, last_seen, container counts and everything else; all
    discovery contributes to it is `hostname` and the note that the register
    also knows it. A node found only in DNS arrives as `enrolled` with no
    last_seen, which _derive_status leaves alone.

    Discovered rows are NOT persisted into db/fleet.json. That file is what
    beats have told us, and a node removed from the zone should disappear on
    the next read rather than linger in a file forever.
    """
    _restore()
    out = {}
    with _lock:
        items = list(_fleet.items())
    for sid, rec in items:
        r = dict(rec)
        status, missed = _derive_status(rec)
        r['status'] = status
        r['missed_beats'] = missed
        r.setdefault('source', 'heartbeat')
        out[sid] = r

    found, _meta = discover()
    for sid, drec in found.items():
        if sid in out:
            # Heard from. Discovery adds the address and says nothing else.
            out[sid]['hostname'] = out[sid].get('hostname') or drec.get('hostname')
            out[sid]['in_register'] = True
            continue
        r = dict(drec)
        r['missed_beats'] = 0
        r['in_register'] = True
        out[sid] = r
    return out


def summary():
    """Counts, plus WHERE THE COUNT CAME FROM.

    The `register` block is the discovery meta verbatim, because a fleet of one
    has two completely different meanings — "there is one node" and "this box
    cannot read the register" — and a bare count cannot tell them apart. It
    carries cf_token_source (a path or an env var NAME) and never a token.
    """
    _restore()
    f = fleet()
    counts = {}
    for r in f.values():
        counts[r['status']] = counts.get(r['status'], 0) + 1
    _nodes, reg = discover()
    return {
        'nodes': len(f),
        'by_status': counts,
        'interval': HEARTBEAT_INTERVAL,
        'degraded_after': DEGRADED_AFTER,
        'unreachable_after': UNREACHABLE_AFTER,
        'register': reg,
    }
