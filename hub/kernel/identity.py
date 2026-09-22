#!/usr/bin/env python3
"""
# 20200010  kernel.identity — server identity, mode, and HS256 tokens

The FlareVault handshake (2026-09-22). This node reads its identity from
server.identity.json rather than deriving or assuming it:

    {
      "server_id":  "fvn_xxxxxx",     authoritative. FlareVault mints these.
      "machine_id": "2ebe78c6...",    hardware anchor, from /etc/machine-id
      "name":       "ksgcohub",
      "role":       "node",           node | central  -> sets the engine mode
      "jwt_secret": "...",            HS256 shared secret, vault-provisioned
      "jwt_issuer": "self"            self | flarevault
    }

Two identifiers on purpose. `server_id` is authoritative and can be reissued;
`machine_id` is the hardware underneath it. A reimaged box keeps its machine_id
and gets a new server_id, which makes the reimage *detectable* — one identifier
could not tell you that.

HS256 rather than RS256 because the hub is stdlib-only, by recorded decision.
hmac + hashlib are in the standard library; RSA verification is not. FlareVault
agreed to issue HS256 so this code does not change when the issuer flips.
"""
import base64
import hashlib
import hmac
import json
import os
import time

# ── Roles ────────────────────────────────────────────────────────────────────
# FlareVault's USB tier names, used verbatim so there is never a translation
# layer between the two systems.
ROLES = ('master', 'operator', 'client-full', 'client-viewer')
ROLE_RANK = {'client-viewer': 10, 'client-full': 20, 'operator': 50, 'master': 100}

MODE_NODE = 'node'
MODE_CENTRAL = 'central'

IDENTITY_FILE = os.environ.get(
    'HUB_IDENTITY_FILE', os.path.expanduser('~/.flare/server.identity.json'))

_cache = None


# 20200321  _machine_id — hardware anchor
def _machine_id():
    try:
        with open('/etc/machine-id', encoding='utf-8') as f:
            return f.read().strip()
    except Exception:
        return ''


# 20200322  _derive_server_id — reproducible fvn_ id until FlareVault mints one
def _derive_server_id(machine_id):
    """Derived, not random, so regenerating a lost identity file yields the
    same id. Replaced wholesale when FlareVault mints the real one."""
    if not machine_id:
        return ''
    return 'fvn_' + hashlib.sha256(machine_id.encode()).hexdigest()[:6]


# 20200323  load — read identity, creating a self-issued one if absent
def load(refresh=False):
    global _cache
    if _cache is not None and not refresh:
        return _cache

    data = {}
    try:
        with open(IDENTITY_FILE, encoding='utf-8') as f:
            data = json.load(f)
    except Exception:
        pass

    mid = data.get('machine_id') or _machine_id()
    data.setdefault('machine_id', mid)
    data.setdefault('server_id', _derive_server_id(mid))
    data.setdefault('name', os.uname().nodename if hasattr(os, 'uname') else '')
    data.setdefault('role', MODE_NODE)
    data.setdefault('jwt_issuer', 'self')
    # A self-issued secret until the vault provisions one. Per-node, not shared.
    data.setdefault('jwt_secret', hashlib.sha256(
        (mid + '|flareshub').encode()).hexdigest())

    _cache = data
    return data


# 20200324  ensure_file — write the identity file if it does not exist yet
def ensure_file():
    """Persist a self-issued identity. Never overwrites a provisioned file."""
    if os.path.exists(IDENTITY_FILE):
        return False
    d = load()
    try:
        os.makedirs(os.path.dirname(IDENTITY_FILE), exist_ok=True)
        with open(IDENTITY_FILE, 'w', encoding='utf-8') as f:
            json.dump(d, f, indent=2)
        os.chmod(IDENTITY_FILE, 0o600)   # holds jwt_secret
        return True
    except Exception:
        return False


def server_id():   return load().get('server_id', '')
def machine_id():  return load().get('machine_id', '')
def node_name():   return load().get('name', '')
def jwt_issuer():  return load().get('jwt_issuer', 'self')


# 20200325  mode — the two-mode engine switch
def mode():
    """CENTRAL aggregates every node and serves the fleet view.
    NODE reports its own Docker landscape and heartbeats to central.
    Same codebase; this one field decides which."""
    return MODE_CENTRAL if load().get('role') == MODE_CENTRAL else MODE_NODE


def is_central(): return mode() == MODE_CENTRAL


def public_hostname(zone=None):
    """flareshub-{server_id}.{zone} — flat, one level deep, so Cloudflare's
    free wildcard cert covers it. Nested would need Advanced Certificate
    Manager."""
    z = zone or load().get('zone') or ''
    sid = server_id()
    return f'flareshub-{sid}.{z}' if (sid and z) else ''


# ── HS256 tokens ─────────────────────────────────────────────────────────────

def _b64(raw):
    return base64.urlsafe_b64encode(raw).rstrip(b'=').decode()


def _unb64(s):
    return base64.urlsafe_b64decode(s + '=' * (-len(s) % 4))


# 20200326  issue — mint an HS256 JWT
def issue(subject, role, ttl=86400, extra=None):
    """Claims deliberately match what FlareVault will issue, so when the
    issuer flips from self to flarevault nothing downstream changes."""
    if role not in ROLES:
        raise ValueError('unknown role: %s' % role)
    d = load()
    now = int(time.time())
    header = {'alg': 'HS256', 'typ': 'JWT'}
    payload = {
        'sub': subject,
        'role': role,
        'iss': d.get('jwt_issuer', 'self'),
        'server_id': d.get('server_id', ''),
        'iat': now,
        'exp': now + int(ttl),
    }
    if extra:
        payload.update(extra)
    h = _b64(json.dumps(header, separators=(',', ':')).encode())
    p = _b64(json.dumps(payload, separators=(',', ':')).encode())
    signing_input = f'{h}.{p}'.encode()
    sig = hmac.new(d['jwt_secret'].encode(), signing_input, hashlib.sha256).digest()
    return f'{h}.{p}.{_b64(sig)}'


# 20200327  verify — validate an HS256 JWT, returns claims or None
def verify(token):
    """Constant-time signature check, then expiry. Returns None on any
    failure — callers must treat None as unauthenticated, never as a default."""
    try:
        h, p, s = token.split('.')
    except Exception:
        return None
    d = load()
    expected = hmac.new(d['jwt_secret'].encode(), f'{h}.{p}'.encode(),
                        hashlib.sha256).digest()
    try:
        if not hmac.compare_digest(expected, _unb64(s)):
            return None
        claims = json.loads(_unb64(p))
    except Exception:
        return None
    if int(claims.get('exp', 0)) < int(time.time()):
        return None
    if claims.get('role') not in ROLES:
        return None
    return claims


# 20200328  role_allows — tier comparison using FlareVault's rank order
def role_allows(claim_role, required):
    return ROLE_RANK.get(claim_role, 0) >= ROLE_RANK.get(required, 999)
