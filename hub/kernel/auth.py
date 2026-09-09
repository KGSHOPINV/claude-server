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
_sessions = {}          # token → {user, created}
_users_lock = threading.Lock()
_gate_sessions = {}     # token → {level, user, expires}
_gate_lock = threading.Lock()

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

# 20200304  check_auth — validate session token from header or query param
def check_auth(handler):
    token = handler.headers.get('X-Hub-Token','')
    if not token:
        # Also accept from query string
        qs = handler.path.split('?',1)[1] if '?' in handler.path else ''
        for part in qs.split('&'):
            if part.startswith('token='):
                token = part[6:]
    with _users_lock:
        return _sessions.get(token)

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
