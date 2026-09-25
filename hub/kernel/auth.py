#!/usr/bin/env python3
"""
# 20200005  kernel.auth — session auth, gate tokens, TOTP
Hub kernel: authentication and authorization layer.
Auth is enforced at the router level — no handler can skip it.
"""
import base64
import hashlib
import hmac
import os
import secrets
import struct
import threading
import time

# Shared session state
_sessions = {}          # token → {user, role, created, expires}
_users_lock = threading.Lock()
_gate_sessions = {}     # token → {level, user, expires}
_gate_lock = threading.Lock()

# ── Session persistence ───────────────────────────────────────────────────────
# _sessions used to be ONLY this dict, so every hub restart logged everyone out.
# That is not a cosmetic annoyance: it is what made the Runbooks view -- 48
# executable steps, the feature that exists so an operator can run routine work
# without help -- unreachable in practice. You would land on the login screen
# every time the hub was deployed or restarted and give up.
#
# The dict stays as the READ path, because a session check happens on nearly
# every request and SQLite on each one would be silly. SQLite is the write-
# through and the survivor: changes go to both, and the dict is rehydrated from
# the table at startup.
#
# Gate tokens are deliberately NOT persisted. A gate is short-lived proof for a
# dangerous operation (shell, vault, TOTP); surviving a restart is exactly what
# it should not do.
SESSION_TTL_DAYS = 30

_loaded = False


def _now():
    return time.time()


def _iso(ts):
    return __import__('datetime').datetime.fromtimestamp(ts).isoformat()


# 20200309  _session_load — hydrate the dict from SQLite, once
def _session_load():
    """Best effort. A hub that cannot read its session table must still serve
    the login page, so every failure here degrades to 'no sessions' rather
    than refusing to start."""
    global _loaded
    if _loaded:
        return
    _loaded = True
    try:
        from kernel.db import db_conn
        conn = db_conn()
        now = _iso(_now())
        conn.execute("DELETE FROM sessions WHERE expires < ?", (now,))
        rows = conn.execute(
            "SELECT token, user, role, created, expires, via FROM sessions").fetchall()
        conn.commit()
        with _users_lock:
            for r in rows:
                _sessions[r['token']] = {
                    'user': r['user'], 'role': r['role'],
                    'created': r['created'], 'expires': r['expires'],
                    'via': r['via'] or 'local',
                }
        conn.close()
    except Exception:
        pass


# 20200310  session_put — create a session that survives a restart
def session_put(token, user, role='admin', via='local'):
    expires = _iso(_now() + SESSION_TTL_DAYS * 86400)
    rec = {'user': user, 'role': role, 'created': _iso(_now()),
           'expires': expires, 'via': via}
    with _users_lock:
        _sessions[token] = rec
    try:
        from kernel.db import db_conn
        conn = db_conn()
        conn.execute(
            "INSERT OR REPLACE INTO sessions (token,user,role,created,expires,via) "
            "VALUES (?,?,?,?,?,?)",
            (token, user, role, rec['created'], expires, via))
        conn.commit()
        conn.close()
    except Exception:
        pass   # an unpersisted session still works until the next restart
    return rec


# 20200314  session_pop — end a session in both places
def session_pop(token):
    with _users_lock:
        rec = _sessions.pop(token, None)
    try:
        from kernel.db import db_conn
        conn = db_conn()
        conn.execute("DELETE FROM sessions WHERE token = ?", (token,))
        conn.commit()
        conn.close()
    except Exception:
        pass
    return rec


def session_count():
    _session_load()
    with _users_lock:
        return len(_sessions)

# ── Cloudflare Access (FlareHub door) ──────────────────────────────────────────
# Two doors, one identity:
#   LAN / Tailscale  -> hub username + password (always available, never disabled)
#   Cloudflare tunnel -> Access already verified the user with Google
#
# The email header is trusted ONLY on requests arriving from the tunnel's own
# address. Anything reaching the hub over Tailscale or LAN can forge that header,
# so path is what makes it safe, not the header itself.
#
# Unset HUB_CF_TRUST_IP (the default) disables all of this -- zero behavior change.
CF_TRUST_IP = os.environ.get('HUB_CF_TRUST_IP', '').strip()
CF_HEADER   = 'Cf-Access-Authenticated-User-Email'
CF_EMAILS   = [e.strip().lower() for e in os.environ.get('HUB_CF_EMAILS', '').split(',') if e.strip()]
CF_ROLE     = os.environ.get('HUB_CF_ROLE', 'admin')

# The SERVICE door. Cloudflare Access forwards Cf-Access-Client-Id to the
# origin when a SERVICE TOKEN authenticated the request -- which is how the
# lobby reaches a node, because node hostnames refuse humans outright.
#
# Without this a drill-in delivers the node's real UI and then shows its login
# box, because app.html calls /api/auth/check and the node has no human
# session to check: the lobby came with a machine credential, not a person.
# Two logins for one door, which is the thing the entry chain exists to
# remove.
#
# Trusted on the SAME terms as the email: only from the tunnel's own address.
# Anything on the tailnet or the LAN can invent this header, so the path is
# what makes it safe, never the header.
#
# The session it grants is deliberately the SAME level as the Google door --
# layer 1 and 2. A service token must not be a way to reach further than the
# human who is holding it, and gate 2/3 still demand their own proof.
CF_CLIENT_HEADER = 'Cf-Access-Client-Id'
# Which client ids may act as the lobby. Empty means any id Access accepted,
# which is already narrow: Access only forwards the header after validating
# the token against the app's own policy.
CF_CLIENTS  = [c.strip().lower() for c in
               os.environ.get('HUB_CF_CLIENTS', '').split(',') if c.strip()]


# ── Internal helpers ───────────────────────────────────────────────────────────

def _config_get(key, default, db_conn_fn):
    """Read a single key from hub_config via the supplied db connection factory."""
    try:
        conn = db_conn_fn()
        row = conn.execute("SELECT value FROM hub_config WHERE key=?", (key,)).fetchone()
        conn.close()
        return row['value'] if row else default
    except Exception:
        return default

# ── Auth ───────────────────────────────────────────────────────────────────────

# 20200312  access_identity — Cloudflare Access email, trusted only via the tunnel
def access_identity(handler):
    """Return the Access-verified email, or None.

    Returns None unless HUB_CF_TRUST_IP is set AND the request arrived from that
    address. The trust is in the network path: cloudflared only forwards requests
    Access has already approved.
    """
    if not CF_TRUST_IP:
        return None
    try:
        src = handler.client_address[0]
    except Exception:
        return None
    if src != CF_TRUST_IP:
        return None
    email = (handler.headers.get(CF_HEADER, '') or '').strip().lower()
    if not email:
        return None
    if CF_EMAILS and email not in CF_EMAILS:
        return None
    return email


# 20200313  service_identity — the lobby, arriving with a service token
def service_identity(handler):
    """Return a name for the calling SERVICE, or None.

    Same rule as access_identity: HUB_CF_TRUST_IP must be set AND the request
    must have arrived from that address. cloudflared only forwards what Access
    already approved, so the network path is the proof.

    Returns a pseudo-user, not a person. Whoever reads the session should be
    able to tell a machine from a human, so the name says which.
    """
    if not CF_TRUST_IP:
        return None
    try:
        src = handler.client_address[0]
    except Exception:
        return None
    if src != CF_TRUST_IP:
        return None
    cid = (handler.headers.get(CF_CLIENT_HEADER, '') or '').strip().lower()
    if not cid:
        return None
    if CF_CLIENTS and cid not in CF_CLIENTS:
        return None
    # Never the whole id in a session record that gets logged and listed.
    return 'lobby:' + cid.split('.')[0][:12]


# 20200304  check_auth — validate session token from header or query param
def check_auth(handler):
    token = handler.headers.get('X-Hub-Token','')
    if not token:
        # Also accept from query string
        qs = handler.path.split('?',1)[1] if '?' in handler.path else ''
        for part in qs.split('&'):
            if part.startswith('token='):
                token = part[6:]
    _session_load()            # first call after a restart refills the dict
    with _users_lock:
        sess = _sessions.get(token)
    if sess:
        # An expired row that survived the startup sweep (a long-running
        # process crossing the TTL) must not authenticate.
        exp = sess.get('expires')
        if exp and exp < _iso(_now()):
            session_pop(token)
            return None
        return sess
    # Second door: Cloudflare Access already vetted this user with Google, so do
    # not ask for a password again. Grants a user-level session only -- gate 2/3
    # operations (vault, shell, TOTP) still demand the stronger proof.
    email = access_identity(handler)
    if email:
        return {'user': email, 'role': CF_ROLE, 'via': 'cf-access'}
    # Third door: the lobby, holding a service token. Checked AFTER the human
    # doors so a real person is always identified as themselves rather than as
    # the machine that carried their request.
    svc = service_identity(handler)
    if svc:
        return {'user': svc, 'role': CF_ROLE, 'via': 'cf-service'}
    return None

# ── TOTP ──────────────────────────────────────────────────────────────────────

# 20205303  _totp_hotp — raw HOTP: base32 secret + counter → 6-digit code
def _totp_hotp(secret, counter):
    try:
        key = base64.b32decode(secret.upper().replace(' ', ''))
        msg = struct.pack('>Q', counter)
        h = hmac.new(key, msg, hashlib.sha1).digest()
        offset = h[-1] & 0x0f
        code = struct.unpack('>I', bytes(h[offset:offset+4]))[0] & 0x7fffffff
        return str(code % 1_000_000).zfill(6)
    except Exception:
        return ''

# 20205304  totp_verify — verify code ±1 time-step against saved totp_secret
def totp_verify(code, db_conn_fn):
    secret = _config_get('totp_secret', '', db_conn_fn)
    if not secret:
        return False
    t = int(time.time()) // 30
    code = str(code).strip().zfill(6)
    return any(_totp_hotp(secret, t + d) == code for d in (-1, 0, 1))

# 20205305  totp_new_secret — generate 20-byte random base32 secret
def totp_new_secret():
    # Generate only — does NOT save to DB.
    # Caller must call /api/totp/confirm with a valid code to activate.
    return base64.b32encode(os.urandom(20)).decode()

# 20205306  totp_verify_secret — verify code against any given secret
def totp_verify_secret(secret, code):
    """Verify a code against any given secret (not necessarily the saved one)."""
    if not secret:
        return False
    t = int(time.time()) // 30
    code = str(code).strip().zfill(6)
    return any(_totp_hotp(secret, t + d) == code for d in (-1, 0, 1))

# 20205307  totp_uri — build otpauth://totp/ URI for QR display
def totp_uri(secret, account='admin'):
    import urllib.parse as _up
    params = _up.urlencode({'secret': secret, 'issuer': 'ServerHub',
                            'algorithm': 'SHA1', 'digits': '6', 'period': '30'})
    return f'otpauth://totp/ServerHub%3A{account}?{params}'

# ── Gate sessions ─────────────────────────────────────────────────────────────

# 20200306  gate_create — mint gate token with level + expiry
def gate_create(level, user, duration_s=1800):
    token   = secrets.token_hex(24)
    expires = time.time() + duration_s
    with _gate_lock:
        now = time.time()
        stale = [k for k, v in _gate_sessions.items() if v['expires'] < now]
        for k in stale:
            del _gate_sessions[k]
        _gate_sessions[token] = {'level': level, 'user': user, 'expires': expires}
    return token, expires

# 20200305  gate_check — return True if TOTP not configured or valid gate token
def gate_check(headers, required_level, db_conn_fn):
    """Return True if TOTP not configured OR valid gate token found at required_level+."""
    if not _config_get('totp_secret', '', db_conn_fn):
        return True
    token = headers.get('X-Gate-Token', '')
    if not token:
        return False
    with _gate_lock:
        g = _gate_sessions.get(token)
    if not g:
        return False
    if g['level'] < required_level:
        return False
    if time.time() > g['expires']:
        with _gate_lock:
            _gate_sessions.pop(token, None)
        return False
    return True
