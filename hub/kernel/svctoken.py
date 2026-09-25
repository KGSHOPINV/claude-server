#!/usr/bin/env python3
"""
# 20200016  kernel.svctoken — the lobby's Cloudflare Access service token

WHAT THIS IS FOR
----------------
Per the FlareVault login-flow spec, every node endpoint is published as

    flareshub-<server-id-with-underscore-as-hyphen>.<zone>

and sits behind a Cloudflare Access application whose ONLY policy is

    {"decision":"non_identity","include":[{"any_valid_service_token":{}}]}

That policy refuses humans outright — there is no identity provider in it to
succeed against. The single human door is login.<zone>; the lobby (this hub in
central mode, served at dashboard.<zone>) is the only thing that talks to a
node, and it does so by presenting a Cloudflare Access SERVICE TOKEN: the two
headers `CF-Access-Client-Id` and `CF-Access-Client-Secret`.

This module owns exactly four jobs:

    recording a service token the operator minted in Cloudflare
    holding it on this box as safely as this box actually permits
    producing the headers for one outbound call to one node
    turning a node id into the https URL that Access is protecting

It makes no outbound call itself. It has no route. handlers/lobby.py is the
only intended caller.


LAW V, AND WHY THIS IS NOT IN bank.py
-------------------------------------
CONSTITUTION.md, Law V:

    "Credentials are never here. Pointers only."

A Cloudflare Access service token is a credential, full stop. So this file is
a second, narrower exception to Law V, and like kernel/bank.py it is only
defensible while it says so in the open. The difference is the SHAPE of the
secret, and that shape is why it must not live in bank.py:

    bank.py holds a HANDOFF. Read-once on project scope, TTL 24h, and
    exception_open() FAILS install-preflight for as long as anything is in
    there. Every one of those properties assumes the secret is leaving soon.

    This token is the opposite: long-lived, read on every single lobby→node
    request, and expected to still be there in six months.

Putting it in the bank breaks the bank in two ways, both silent:

  1. TTL would expire the lobby's only credential on a timer. The fleet view
     would go dark 24 hours after it was set up and the cause would look like
     a Cloudflare problem, not a storage-policy problem.
  2. It would hold exception_open() permanently TRUE. `install-preflight
     --strict` could then never pass clean on any central node — so the one
     assertion that keeps the bank's exception temporary would become
     permanent background noise, and a warning nobody can ever clear is a
     warning nobody reads. That assertion is the whole reason the bank
     exception is tolerable; parking a permanent resident in it destroys it.

So: ITS OWN FILE, mode 0600, at ~/.flare/svctoken.json — beside node.json and
server.identity.json, which enroll.sh and identity.ensure_file() already write
0600 in that same directory. server.identity.json holds `jwt_secret`, a
long-lived unattended credential of exactly this class, in that exact way.
This is the established precedent on this box, not a new one.


WHAT ACTUALLY PROTECTS IT — honestly, in order
----------------------------------------------
    file mode 0600      the real control. Owner only. Enforced on read
                        (see _read): a widened file is REFUSED, the way ssh
                        refuses a group-readable private key.
    outside backup      true today only by SCOPE, not by an exclusion:
                        hub/tools/backup.sh names server.db and control.db and
                        nothing in $HOME/.flare. A broader backup would sweep
                        this file up. Do not rely on this.
    never logged        this module writes no log line, ever. See below.
    obfuscated at rest  NOT a guarantee. See below.

The stored value is XORed with a keystream derived from /etc/machine-id plus a
0600 salt file. That means a copy of svctoken.json carried off this machine is
not plaintext. It means nothing else. THE KEY IS ON THE SAME BOX: anything the
hub can read unattended, root can read, and the hub must read this unattended
on every request or it is not useful. Anyone with root here has the token.

The version that is actually strong — a key the operator holds, so the box
never has both halves — is FlareVault's job, and this file should be deleted
the day FlareVault brokers node calls itself.

The keystream construction is deliberately DUPLICATED from bank.py rather than
imported. bank.py is written to be deleted; a hard import of a module whose
stated purpose is to disappear would take this one with it.


WHY THE SECRET CANNOT REACH A LOG OR A TRACEBACK
------------------------------------------------
Intent is not a mechanism, so this is structural:

  * The secret is only ever held inside `_Secret`, whose __repr__, __str__
    and __format__ all return a redaction marker. Anything that interpolates
    it — an f-string, %s, logging, a traceback that prints locals — gets
    '<svctoken:redacted>'. Its __reduce__ refuses, so it cannot be pickled,
    and it has no JSON encoder, so json.dumps() on a structure containing one
    raises TypeError instead of serialising the token into a response body.
  * __slots__, so there is no instance __dict__ for a generic object dumper
    to walk.
  * The plaintext leaves _Secret at exactly ONE place: the dict built inside
    headers_for(). Nowhere else calls .reveal().
  * Every public function catches Exception WITHOUT binding it and returns a
    safe empty value. An exception object built from a line that was handling
    the secret never escapes this module, so it can never be formatted by a
    caller or a framework error page.
  * status() is assembled from fields that structurally cannot contain the
    secret — a boolean, a timestamp, a path, a mode, and a truncated SHA-256
    of the CLIENT ID (which is not the secret half, and which an operator
    needs in order to tell which token is installed after a rotation).
  * This module logs nothing at all. Not because the event is uninteresting,
    but because the code path that formats a log line is the code path that
    leaks. lobby.py may log that it called a node; it never sees the
    credential.


FAIL CLOSED
-----------
headers_for() returns {} and never raises. {} means "this hub has no way to
authenticate to that node". The caller MUST treat {} as do-not-call. A request
sent to a node without these headers does not quietly succeed — Access refuses
it — but it does burn a round trip and produce a 302-to-nowhere that looks like
a network fault. That is the failure mode to avoid, and it is the caller's to
avoid; this module cannot enforce it from here and does not pretend to.
"""
import hashlib
import hmac
import json
import os
import re
import stat
from datetime import datetime, timezone

# ── Where things live ────────────────────────────────────────────────────────
# ~/.flare is already the node's credential-adjacent directory: enroll.sh
# writes node.json 0600 there, identity.ensure_file() writes
# server.identity.json 0600 there. One directory, one mode, one thing to check.
FLARE_DIR = os.path.expanduser('~/.flare')

TOKEN_FILE = os.environ.get('HUB_SVCTOKEN_FILE',
                            os.path.join(FLARE_DIR, 'svctoken.json'))

# Written by enroll.sh step 8. Absent on a node that has never enrolled, which
# is a legitimate state and not an error — it simply has no zone yet.
NODE_FILE = os.environ.get('HUB_NODE_FILE', os.path.join(FLARE_DIR, 'node.json'))

_SALT_FILE = os.path.join(FLARE_DIR, '.svctoken-salt')

# Cloudflare's own names for these, used verbatim so an operator can paste what
# the dashboard gave them into the environment without a translation step.
ENV_ID = 'CF_ACCESS_CLIENT_ID'
ENV_SECRET = 'CF_ACCESS_CLIENT_SECRET'

# The hostname label rule enroll.sh enforces, applied again here. This is not
# belt-and-braces: node_url() builds a URL that the lobby will then fetch, so
# an unvalidated node id is an SSRF — 'x/../@evil.com' would send the lobby,
# carrying the fleet's service token, somewhere the operator never named.
_LABEL_OK = re.compile(r'^[a-z0-9][a-z0-9-]{0,62}[a-z0-9]$')
_ZONE_OK = re.compile(r'^[a-z0-9][a-z0-9.-]{0,251}[a-z0-9]$')

_REDACTED = '<svctoken:redacted>'


class _Secret:
    """A string that refuses to print itself.

    Everything about this class exists so that the secret half cannot arrive
    in a log line, an error page, a JSON body or a traceback by accident. The
    plaintext is reachable only through .reveal(), which has exactly one
    caller in this file.
    """
    __slots__ = ('_v',)

    def __init__(self, v):
        object.__setattr__(self, '_v', v)

    def __repr__(self):
        return _REDACTED

    def __str__(self):
        return _REDACTED

    def __format__(self, spec):
        return _REDACTED

    def __reduce__(self):
        # Refuses pickle/copy. The message names no value.
        raise TypeError('service token is not serialisable')

    def __len__(self):
        # Length only, so a caller can sanity-check "did anything land" without
        # ever holding the characters.
        return len(self._v)

    def __bool__(self):
        return bool(self._v)

    def reveal(self):
        return self._v


def _utc():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


# 20200401  _node_facts — the zone, read from the machine rather than hardcoded
# 20200412  edge_headers — the Access credential, not bound to any node
def edge_headers():
    """The service token headers alone, for a call whose URL is already known.

    headers_for(node_id) validates the id because it also builds the URL. The
    heartbeat does not need that: its target comes from central_url in the
    identity file, and the token is account-wide -- the node policy is
    any_valid_service_token, so one token opens every node.

    Returns {} when no token is held, which means DO NOT CALL. A heartbeat
    that goes out without the credential is refused at the edge and reads as
    the node being down.
    """
    try:
        if not have_token():
            return {}
        cid, sec, _ = _read()
        if not cid or not sec:
            return {}
        return {'CF-Access-Client-Id': cid,
                'CF-Access-Client-Secret': sec.reveal(),
                'User-Agent': USER_AGENT}
    except Exception:
        return {}


# Sent on every outbound node call. See headers_for() for why this matters.
USER_AGENT = 'FlareSHub-Lobby/1.0'


def _node_facts():
    """Law I: derive, do not maintain. The zone is whatever enroll.sh actually
    put in ~/.flare/node.json, not a constant in this file that drifts the
    first time someone enrolls into a different zone.

    Env override for the case node.json cannot cover: a central hub that runs
    the lobby but was never itself enrolled as a node, so no enroll.sh has ever
    written that file. Returns {} rather than raising when there is nothing —
    "never enrolled" is a state, not a fault.
    """
    facts = {}
    try:
        with open(NODE_FILE, encoding='utf-8') as f:
            raw = json.load(f)
        if isinstance(raw, dict):
            facts = raw
    except Exception:
        facts = {}
    zone = str(facts.get('zone') or '').strip().lower()
    if not zone:
        zone = (os.environ.get('FLARE_ZONE')
                or os.environ.get('HUB_ZONE') or '').strip().lower()
    if zone and not _ZONE_OK.match(zone):
        zone = ''          # a malformed zone builds a malformed URL. Refuse.
    return {'zone': zone,
            'hostname': str(facts.get('hostname') or ''),
            'enrolled': bool(facts)}


# 20200402  _label — a server id as a legal hostname label
def _label(node_id):
    """fvn_685a59 -> fvn-685a59. Underscores are not legal in a hostname label,
    which is the same swap enroll.sh makes when it builds HOSTNAME_FQDN. If the
    two ever disagreed the lobby would address a name the node does not answer
    to, so the rule is written the same way on both sides on purpose.

    Returns '' for anything that is not a clean label. '' is the refusal.
    """
    try:
        s = str(node_id or '').strip().lower().replace('_', '-')
    except Exception:
        return ''
    return s if _LABEL_OK.match(s) else ''


# 20200403  node_url — a node id to the https URL Access is protecting
def node_url(node_id):
    """'https://flareshub-<label>.<zone>', or '' if this hub cannot say.

    '' happens for three honest reasons and the caller need not tell them
    apart, because all three mean the same thing: do not call.
      - node_id is not a legal label (refused, see _LABEL_OK)
      - there is no zone (this box has never enrolled and no env names one)
      - the zone on disk is malformed

    LIMIT, stated rather than hidden: this assumes ONE zone for the whole
    fleet, because one zone is all the machine can tell us — node.json records
    the zone THIS box enrolled into, not the zone of the node being addressed.
    A multi-zone fleet needs the zone carried per peer in kernel/fleet.py and
    passed in here. Until that exists, a cross-zone call silently builds the
    wrong hostname, which fails to resolve rather than reaching the wrong box.
    Never raises.
    """
    try:
        label = _label(node_id)
        if not label:
            return ''
        zone = _node_facts()['zone']
        if not zone:
            return ''
        return 'https://flareshub-%s.%s' % (label, zone)
    except Exception:
        return ''


# 20200404  _key — machine-bound, so a copied file is useless elsewhere
def _key():
    """SHA-256 over a local 0600 salt plus /etc/machine-id.

    Protects against the file leaving this machine. Does NOT protect against
    anyone who is ON this machine as root — the hub decrypts unattended on
    every request, so the key is by definition available to whoever can run as
    the hub. Saying more than that would be a claim this project does not get
    to make.

    If the salt cannot be written (read-only home, wrong owner) the key still
    derives — from machine-id alone, or from nothing at all on a box with
    neither. That degrades the obfuscation to none and keeps the hub running;
    the 0600 mode check in _read is the control that still holds in that case.
    """
    salt = b''
    try:
        with open(_SALT_FILE, 'rb') as f:
            salt = f.read().strip()
    except Exception:
        pass
    if not salt:
        salt = os.urandom(32).hex().encode()
        try:
            os.makedirs(FLARE_DIR, exist_ok=True)
            fd = os.open(_SALT_FILE, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, 'wb') as f:
                f.write(salt)
        except Exception:
            pass
    machine = ''
    try:
        with open('/etc/machine-id', encoding='utf-8') as f:
            machine = f.read().strip()
    except Exception:
        pass
    return hashlib.sha256(salt + b'|svctoken|' + machine.encode()).digest()


# 20200405  _obfuscate — symmetric keystream XOR. Obfuscation, not protection.
def _obfuscate(data: bytes) -> bytes:
    """HMAC-SHA256 counter keystream, XORed. Stdlib only, by the project's own
    rule. Symmetric, so one call both directions.

    Named _obfuscate and not _encrypt deliberately. It makes a stray copy
    unreadable off-box. It is not a security boundary and must never be cited
    as one; the 0600 mode is the boundary.

    Duplicated from bank.py rather than imported — bank.py exists to be
    deleted, and importing it would make this module die with it.
    """
    key = _key()
    out = bytearray()
    counter = 0
    while len(out) < len(data):
        out.extend(hmac.new(key, counter.to_bytes(8, 'big'),
                            hashlib.sha256).digest())
        counter += 1
    return bytes(a ^ b for a, b in zip(data, out))


# 20200406  store — record a token the operator minted in Cloudflare
def store(client_id, client_secret):
    """Returns (ok: bool, message: str). The message NEVER contains any part of
    either value — not a prefix, not a length, not a hint.

    Written O_EXCL-free but created at 0600 by os.open's mode argument and then
    os.replace()d into place. Creating at 0600 rather than chmod-ing afterwards
    closes the window in which the file exists world-readable; os.replace makes
    the swap atomic, so a crash mid-write leaves the previous token intact
    rather than a truncated one that fails every call.
    """
    try:
        cid = str(client_id or '').strip()
        csec = str(client_secret or '').strip()
        if not cid or not csec:
            return False, 'both client id and client secret are required'
        if len(cid) > 512 or len(csec) > 1024:
            return False, 'value is longer than any Cloudflare service token'
        note = ''
        if not cid.endswith('.access'):
            # Reported, not enforced. enroll.sh learned this the hard way with
            # /user/tokens/verify: a format check that refuses a working
            # credential costs more than one that only remarks on it.
            note = ' (note: client id does not end in .access — unusual)'

        payload = json.dumps({
            'client_id': cid,
            'client_secret': csec,
        }, separators=(',', ':')).encode()

        os.makedirs(FLARE_DIR, exist_ok=True)
        record = {
            'v': 1,
            'blob': _obfuscate(payload).hex(),
            'recorded': _utc(),
            # Lets an operator confirm WHICH token is installed after a
            # rotation without the file ever showing the credential. A hash of
            # the id half only; the secret half is not an input.
            'client_id_fp': hashlib.sha256(cid.encode()).hexdigest()[:12],
        }
        tmp = TOKEN_FILE + '.tmp'
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            json.dump(record, f)
        os.replace(tmp, TOKEN_FILE)
        try:
            os.chmod(TOKEN_FILE, 0o600)   # in case an old file was wider
        except Exception:
            pass
        return True, 'service token recorded at %s (0600)%s' % (TOKEN_FILE, note)
    except Exception:
        # Deliberately not binding or formatting the exception. The line that
        # failed was holding the secret; its message is not something this
        # function is willing to hand back.
        return False, 'could not write the token file (check %s is writable)' % FLARE_DIR


# 20200407  _read — the only place the stored value is unwrapped
def _read():
    """Returns (client_id, _Secret, meta_dict). (('', None, meta)) when there
    is nothing usable — and 'nothing usable' deliberately includes 'present but
    the file mode is too wide'.

    THE MODE CHECK. ssh refuses a group-readable private key and is right to:
    a credential that other local accounts can read is not a credential. If
    svctoken.json has drifted to 0644 — an editor, an rsync, a careless
    install script — this refuses to use it and says why in status(). The hub
    then fails closed and visibly rather than continuing to authenticate with a
    secret the whole box can read.

    Enforced only on posix. On Windows os.stat reports 0o666 for ordinary
    files, so the check would refuse everything; this module runs on the Linux
    nodes, and a Windows dev box is not where a real token lives.
    """
    meta = {'source': None, 'recorded': None, 'client_id_fp': None,
            'mode': None, 'problem': None}

    env_id = (os.environ.get(ENV_ID) or '').strip()
    env_secret = (os.environ.get(ENV_SECRET) or '').strip()
    if env_id and env_secret:
        # Env wins. Law III: when the operator has already answered the
        # question for this process, read the answer. status() names the
        # source, so an operator wondering why a rotated file had no effect is
        # told, rather than left to guess.
        meta['source'] = 'env'
        meta['client_id_fp'] = hashlib.sha256(env_id.encode()).hexdigest()[:12]
        return env_id, _Secret(env_secret), meta

    try:
        st = os.stat(TOKEN_FILE)
    except Exception:
        meta['problem'] = 'no token recorded'
        return '', None, meta

    mode = stat.S_IMODE(st.st_mode)
    meta['mode'] = '0%o' % mode
    if os.name == 'posix' and mode & 0o077:
        meta['problem'] = ('file mode 0%o is readable beyond its owner — '
                           'refusing to use it. Fix: chmod 600 %s'
                           % (mode, TOKEN_FILE))
        return '', None, meta

    try:
        with open(TOKEN_FILE, encoding='utf-8') as f:
            record = json.load(f)
        meta['recorded'] = record.get('recorded')
        meta['client_id_fp'] = record.get('client_id_fp')
        payload = json.loads(_obfuscate(bytes.fromhex(record['blob'])).decode())
        cid = str(payload.get('client_id') or '')
        csec = str(payload.get('client_secret') or '')
        if not cid or not csec:
            meta['problem'] = 'token file is present but incomplete'
            return '', None, meta
        meta['source'] = 'file'
        return cid, _Secret(csec), meta
    except Exception:
        # Most likely cause by far: the file was written on a different machine
        # or the salt was lost, so the keystream no longer matches and the
        # decode fails. Say that, and say the repair. Never echo the bytes.
        meta['problem'] = ('token file unreadable — it was recorded against a '
                           'different machine-id or salt. Record it again.')
        return '', None, meta


# 20200408  have_token — is there a usable credential at all
def have_token():
    """True only if a token is present AND usable. A 0644 file is False here,
    because 'present' and 'usable' being different things is exactly what the
    mode check exists to surface. Never raises.
    """
    try:
        cid, sec, _ = _read()
        return bool(cid and sec)
    except Exception:
        return False


# 20200409  headers_for — the outbound Access headers for one node
def headers_for(node_id):
    """The two headers that satisfy the node's any_valid_service_token policy,
    or {} — and {} means DO NOT CALL.

    THE CONTRACT, because getting it wrong is the whole risk: an empty dict is
    not "call it without auth". Access will refuse an unauthenticated request,
    so nothing leaks, but the caller gets a 302 to a login it can never
    complete and the operator sees what looks like a network fault. lobby.py
    must check for {} and stop.

    node_id is taken, validated, and then not used to select a credential —
    there is one token for the whole fleet today, because the node policy is
    any_valid_service_token rather than a named token id, precisely so that
    rotating the lobby's credential does not mean re-running enrolment on every
    node (enroll.sh step 6 says so). The parameter is here because per-node
    tokens are the obvious next shape and this signature should not have to
    change when they arrive. It is validated regardless, so a caller passing
    rubbish fails closed here rather than at the socket.

    Never raises. Never logs. The only .reveal() in this file is below.
    """
    try:
        if not _label(node_id):
            return {}
        cid, sec, _ = _read()
        if not cid or not sec:
            return {}
        # USER-AGENT IS NOT OPTIONAL, and this cost an hour to find.
        #
        # Cloudflare's Browser Integrity Check sits IN FRONT of Access and
        # blocks requests whose user agent looks automated. urllib sends
        # 'Python-urllib/3.x', so a perfectly valid service token came back
        # 403 with error code 1010 -- which reads exactly like Access
        # refusing the credential, and sent me auditing the token, the policy
        # and the app config while the request was never reaching Access at
        # all.
        #
        # 1010 is BIC. 403 from Access looks different. Anything calling a
        # node through the edge must identify itself.
        return {'CF-Access-Client-Id': cid,
                'CF-Access-Client-Secret': sec.reveal(),
                'User-Agent': USER_AGENT}
    except Exception:
        return {}


# 20200410  forget — remove the stored token
def forget():
    """Returns (ok, message). Deletes the file. Does NOT touch the environment
    — this process cannot unset a variable for the systemd unit that set it, so
    if the source was env, say so plainly instead of reporting a success that
    changes nothing and leaves the lobby still authenticating.

    Deleting here does not revoke anything at Cloudflare. Revocation is a
    dashboard/API action against the service token itself; this only stops THIS
    box from using it. If the token is believed leaked, revoke it upstream —
    the message says so because the difference is easy to assume away.
    """
    msg = []
    try:
        if os.path.exists(TOKEN_FILE):
            os.remove(TOKEN_FILE)
            msg.append('token file removed')
        else:
            msg.append('no token file to remove')
    except Exception:
        return False, 'could not remove %s' % TOKEN_FILE
    if os.environ.get(ENV_ID) and os.environ.get(ENV_SECRET):
        msg.append('WARNING: %s/%s are still set in this process\'s '
                   'environment, so the lobby can still authenticate. Clear '
                   'them in the unit file and restart.' % (ENV_ID, ENV_SECRET))
    msg.append('this does not revoke the token at Cloudflare — do that in '
               'Zero Trust > Access > Service Auth if it may have leaked')
    return True, '; '.join(msg)


# 20200411  status — what an operator is allowed to be told
def status():
    """Whether a token exists, where it came from, when it was recorded, and
    what is wrong if anything. Never any part of the secret.

    Every field here is structurally incapable of carrying it: booleans, a
    timestamp, a path, an octal mode, a zone, and a truncated SHA-256 of the
    CLIENT ID — the non-secret half, included because after a rotation the only
    question an operator actually has is "is the new one installed?", and a
    fingerprint answers it without showing anything.

    Safe to render straight into an API response. Never raises.
    """
    try:
        cid, sec, meta = _read()
        facts = _node_facts()
        return {
            'present': bool(cid and sec),
            'source': meta['source'],
            'recorded': meta['recorded'],
            'client_id_fp': meta['client_id_fp'],
            'file': TOKEN_FILE,
            'mode': meta['mode'],
            'problem': meta['problem'],
            'zone': facts['zone'],
            'enrolled': facts['enrolled'],
            # Said out loud in every status response, so the exception cannot
            # quietly become architecture. Same reasoning as
            # bank.exception_open(); this one cannot fail preflight because it
            # is meant to be present, so it announces itself instead.
            'law_v_exception': ('a Cloudflare Access service token is held on '
                                'this box, 0600, machine-bound obfuscation '
                                'only. Root here can read it. Delete this '
                                'module when FlareVault brokers node calls.'),
        }
    except Exception:
        return {'present': False, 'source': None, 'recorded': None,
                'client_id_fp': None, 'file': TOKEN_FILE, 'mode': None,
                'problem': 'status could not be determined',
                'zone': '', 'enrolled': False, 'law_v_exception': ''}


# ─────────────────────────────────────────────────────────────────────────────
# HOW AN OPERATOR MINTS THE TOKEN AND FEEDS IT IN
#
# Dashboard:
#   Cloudflare Zero Trust > Access > Service Auth > Service Tokens
#   > Create Service Token. Name it for the lobby, e.g. "flareshub-lobby".
#   The Client Secret is shown ONCE and never again. Copy both halves then.
#
# API (same thing, if you already have a token with Access > Service Tokens
# > Edit). Run this from the operator's machine, not from a node:
#
#   curl -s -X POST \
#     "https://api.cloudflare.com/client/v4/accounts/$ACCOUNT_ID/access/service_tokens" \
#     -H "Authorization: Bearer $CF_API_TOKEN" \
#     -H "Content-Type: application/json" \
#     -d '{"name":"flareshub-lobby","duration":"8760h"}'
#
#   The response carries result.client_id and result.client_secret. The secret
#   is in that response body and nowhere else, ever again.
#
# Nothing else needs doing on the nodes: enroll.sh attaches
# any_valid_service_token, so this one token is accepted by every node already
# enrolled and by every node enrolled afterwards.
#
# Feeding it to the lobby — either way, on the CENTRAL box only:
#
#   python3 -c "from kernel import svctoken; \
#     print(svctoken.store('<client_id>', '<client_secret>'))"
#
#   or, if the operator would rather the systemd unit own it:
#     Environment=CF_ACCESS_CLIENT_ID=...
#     Environment=CF_ACCESS_CLIENT_SECRET=...
#   (env wins over the file; status()['source'] says which is in force)
#
# Confirm without revealing anything:
#   python3 -c "from kernel import svctoken; print(svctoken.status())"
# ─────────────────────────────────────────────────────────────────────────────
