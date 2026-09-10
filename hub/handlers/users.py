#!/usr/bin/env python3
"""
# 20204005  handlers.users -- auth, session, users, TOTP endpoints
Hub handler module: users layer (module 05).
Imports only from kernel/. No direct DB access except via kernel.db.
"""
import hashlib
import json
import secrets
import time
from datetime import datetime

from kernel.db   import db_conn
from kernel.auth import (
    check_auth, gate_check, gate_create,
    _totp_hotp, totp_verify, totp_new_secret, totp_verify_secret, totp_uri,
    _sessions, _users_lock, _gate_sessions, _gate_lock,
)

# ── Helpers (local to this module) ────────────────────────────────────────────

def _user_auth(username, password):
    """SHA-256 password check, returns user row or None."""
    try:
        h = hashlib.sha256(password.encode()).hexdigest()
        conn = db_conn()
        row = conn.execute(
            "SELECT * FROM users WHERE username=? AND password_hash=?", (username, h)
        ).fetchone()
        conn.close()
        return dict(row) if row else None
    except Exception:
        return None


def _users_list():
    """SELECT all users (no password_hash)."""
    try:
        conn = db_conn()
        rows = conn.execute(
            "SELECT id,username,display,role,created FROM users ORDER BY id"
        ).fetchall()
        conn.close()
        return [dict(r) for r in rows]
    except Exception:
        return []


def _config_get(key, default=None):
    """SELECT single value from hub_config."""
    try:
        conn = db_conn()
        row = conn.execute("SELECT value FROM hub_config WHERE key=?", (key,)).fetchone()
        conn.close()
        return row['value'] if row else default
    except Exception:
        return default


def _config_set(key, value):
    """UPSERT key/value in hub_config."""
    try:
        conn = db_conn()
        ts = datetime.now().isoformat()
        conn.execute(
            "INSERT INTO hub_config(key,value,updated) VALUES(?,?,?) "
            "ON CONFLICT(key) DO UPDATE SET value=?,updated=?",
            (key, value, ts, value, ts)
        )
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        return str(e)


def _journal_add(type_, body, user=''):
    """INSERT into journal."""
    try:
        conn = db_conn()
        conn.execute(
            "INSERT INTO journal(ts,type,body,user) VALUES(?,?,?,?)",
            (datetime.now().isoformat(), type_, body, user)
        )
        conn.commit()
        conn.close()
    except Exception:
        pass

# One function per route.

# 20305701  GET /api/auth/check — check auth status
def get_auth_check(handler):
    sess = check_auth(handler)
    if sess:
        handler.send_json({'ok': True, 'user': sess['user']})
    else:
        handler.send_json({'ok': False}, 401)


# 20305702  GET /api/users — list users
def get_users(handler):
    handler.send_json(_users_list())


# 20305703  GET /api/totp/status — TOTP enabled/disabled
def get_totp_status(handler):
    secret = _config_get('totp_secret', '')
    with _gate_lock:
        now = time.time()
        gates = [
            {
                'level': v['level'],
                'user': v['user'],
                'expires_in': int(v['expires'] - now),
            }
            for v in _gate_sessions.values() if v['expires'] > now
        ]
    handler.send_json({'configured': bool(secret), 'gates': gates})


# 20305704  GET /api/totp/setup — generate TOTP setup URI
def get_totp_setup(handler):
    # Always generate a fresh temp secret — never saved to DB here.
    # The status endpoint tells the UI whether 2FA is already active.
    # This endpoint is only called when the user wants to begin setup.
    new_secret = totp_new_secret()
    sess = check_auth(handler)
    account = sess['user'] if sess else 'admin'
    handler.send_json({
        'secret': new_secret,
        'uri': totp_uri(new_secret, account),
    })


# 20305705  POST /api/auth/login — login with password
def post_auth_login(handler, body):
    username = body.get('username', '').strip()
    password = body.get('password', '')
    user = _user_auth(username, password)
    if user:
        token = secrets.token_hex(32)
        with _users_lock:
            _sessions[token] = {
                'user': username,
                'role': user.get('role', 'admin'),
                'created': datetime.now().isoformat(),
            }
        handler.send_json({
            'ok': True,
            'token': token,
            'user': username,
            'role': user.get('role', 'admin'),
        })
    else:
        handler.send_json({'ok': False, 'error': 'Invalid username or password'}, 401)


# 20305706  POST /api/auth/logout — logout / clear session
def post_auth_logout(handler, body):
    token = body.get('token', '')
    with _users_lock:
        _sessions.pop(token, None)
    handler.send_json({'ok': True})


# 20305707  POST /api/users — create/update user
def post_users(handler, body):
    action = body.get('action', '')
    if action == 'add':
        username = body.get('username', '').strip()
        password = body.get('password', '')
        display  = body.get('display', username)
        role     = body.get('role', 'viewer')
        if not username or not password:
            handler.send_json({'ok': False, 'error': 'Username and password required'}, 400)
            return
        h = hashlib.sha256(password.encode()).hexdigest()
        try:
            conn = db_conn()
            conn.execute(
                "INSERT INTO users(username,display,password_hash,role,created) VALUES(?,?,?,?,?)",
                (username, display, h, role, datetime.now().isoformat())
            )
            conn.commit()
            conn.close()
            handler.send_json({'ok': True})
        except Exception as e:
            handler.send_json({'ok': False, 'error': str(e)})
    elif action == 'delete':
        uid = body.get('id')
        try:
            conn = db_conn()
            conn.execute("DELETE FROM users WHERE id=? AND username != 'admin'", (uid,))
            conn.commit()
            conn.close()
            handler.send_json({'ok': True})
        except Exception as e:
            handler.send_json({'ok': False, 'error': str(e)})
    elif action == 'passwd':
        uid = body.get('id')
        pw  = body.get('password', '')
        if not pw:
            handler.send_json({'ok': False, 'error': 'Password required'}, 400)
            return
        h = hashlib.sha256(pw.encode()).hexdigest()
        try:
            conn = db_conn()
            conn.execute("UPDATE users SET password_hash=? WHERE id=?", (h, uid))
            conn.commit()
            conn.close()
            handler.send_json({'ok': True})
        except Exception as e:
            handler.send_json({'ok': False, 'error': str(e)})
    else:
        handler.send_json({'ok': False, 'error': 'Unknown action'}, 400)


# 20305708  POST /api/totp/confirm — confirm TOTP enrollment
def post_totp_confirm(handler, body):
    # Activate 2FA: verify code against a temp secret, save only if valid.
    # This is called during setup — not for gate unlock.
    secret = str(body.get('secret', '')).strip()
    code   = str(body.get('code', '')).strip()
    if not secret:
        handler.send_json({'ok': False, 'error': 'No secret provided'}, 400)
        return
    if not totp_verify_secret(secret, code):
        handler.send_json({'ok': False, 'error': 'Invalid code — check your authenticator app'}, 401)
        return
    # Code is valid → save secret → 2FA is now active
    _config_set('totp_secret', secret)
    _journal_add('security', '2FA enabled via setup confirmation', '')
    handler.send_json({'ok': True})


# 20305709  POST /api/totp/verify — verify TOTP code
def post_totp_verify(handler, body):
    code     = str(body.get('code', '')).strip()
    level    = max(1, min(4, int(body.get('level', 3))))
    duration = int(body.get('duration_s', 1800))
    if not totp_verify(code, db_conn):
        handler.send_json({'ok': False, 'error': 'Invalid or expired code'}, 401)
        return
    sess = check_auth(handler)
    user = sess['user'] if sess else 'api'
    gate_token, expires = gate_create(level, user, duration)
    _journal_add('gate_unlock', f'Level {level} gate opened ({duration//60}m) by {user}', user)
    handler.send_json({
        'ok': True,
        'gate_token': gate_token,
        'expires_at': datetime.fromtimestamp(expires).isoformat(),
        'expires_in': int(expires - time.time()),
        'level': level,
    })


# 20305710  POST /api/totp/disable — disable TOTP
def post_totp_disable(handler, body):
    code = str(body.get('code', '')).strip()
    if not totp_verify(code, db_conn):
        handler.send_json({'ok': False, 'error': 'Invalid code'}, 401)
        return
    _config_set('totp_secret', '')
    with _gate_lock:
        _gate_sessions.clear()
    _journal_add('gate_unlock', 'TOTP disabled', '')
    handler.send_json({'ok': True})
