#!/usr/bin/env python3
"""
# 20204004  handlers.config -- vault, config, journal, issues endpoints
Hub handler module: config layer (module 04).
Imports only from kernel/. No direct DB access except via kernel.db.
"""
import json
from datetime import datetime

from kernel.db   import db_conn
from kernel.auth import check_auth, gate_check

# One function per route. Each takes (handler, path, params) for GET,
# (handler, path, params, body) for POST.


# 20304701  GET /api/vault -- read vault blob
def get_vault(handler, path, params):
    try:
        conn = db_conn()
        row = conn.execute("SELECT value FROM notes WHERE key='vault_blob' LIMIT 1").fetchone()
        conn.close()
        blob = row['value'] if row else None
    except Exception:
        blob = None
    handler.send_json({'blob': blob})


# 20304702  GET /api/issues -- list all issues
def get_issues(handler, path, params):
    try:
        conn = db_conn()
        rows = conn.execute("SELECT * FROM issues ORDER BY id DESC").fetchall()
        conn.close()
        handler.send_json([dict(r) for r in rows])
    except Exception:
        handler.send_json([])


# 20304703  GET /api/journal -- read journal entries
def get_journal(handler, path, params):
    limit = 100
    if '?' in handler.path:
        for part in handler.path.split('?', 1)[1].split('&'):
            if part.startswith('limit='):
                try: limit = int(part[6:])
                except: pass
    try:
        conn = db_conn()
        rows = conn.execute("SELECT * FROM journal ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        conn.close()
        handler.send_json([dict(r) for r in rows])
    except Exception:
        handler.send_json([])


# 20304704  GET /api/config -- read hub config key/value store
def get_config(handler, path, params):
    try:
        conn = db_conn()
        rows = conn.execute("SELECT key,value FROM hub_config").fetchall()
        conn.close()
        handler.send_json({r['key']: r['value'] for r in rows})
    except Exception:
        handler.send_json({})


# 20304705  POST /api/vault -- write encrypted vault blob (gate 2)
def post_vault(handler, path, params, body):
    blob = body.get('blob')
    if blob is None:
        handler.send_json({'ok': False, 'error': 'No blob'}, 400)
        return
    if not gate_check(handler.headers, 2, db_conn):
        handler.send_json({'error': 'gate_required', 'layer': 2,
                           'message': 'Vault writes require TOTP verification'}, 403)
        return
    try:
        conn = db_conn()
        ts = datetime.now().isoformat()
        row = conn.execute("SELECT id FROM notes WHERE key='vault_blob' LIMIT 1").fetchone()
        if row:
            conn.execute("UPDATE notes SET value=?, updated=? WHERE key='vault_blob'", (blob, ts))
        else:
            conn.execute(
                "INSERT INTO notes (category, key, value, updated) VALUES ('vault','vault_blob',?,?)",
                (blob, ts))
        conn.commit()
        conn.close()
        handler.send_json({'ok': True})
    except Exception as e:
        handler.send_json({'ok': False, 'error': str(e)})


# 20304706  POST /api/config -- write hub config values (gate 2)
def post_config(handler, path, params, body):
    if not gate_check(handler.headers, 2, db_conn):
        handler.send_json({'error': 'gate_required', 'layer': 2,
                           'message': 'Config writes require TOTP verification'}, 403)
        return
    for k, v in body.items():
        try:
            conn = db_conn()
            ts = datetime.now().isoformat()
            conn.execute(
                "INSERT INTO hub_config(key,value,updated) VALUES(?,?,?)"
                " ON CONFLICT(key) DO UPDATE SET value=?,updated=?",
                (k, str(v), ts, str(v), ts))
            conn.commit()
            conn.close()
        except Exception:
            pass
    handler.send_json({'ok': True})


# 20304707  POST /api/journal -- append journal entry
def post_journal(handler, path, params, body):
    body_text = body.get('body', '').strip()
    if body_text:
        try:
            conn = db_conn()
            conn.execute(
                "INSERT INTO journal(ts,type,body,user) VALUES(?,?,?,?)",
                (datetime.now().isoformat(), body.get('type', 'manual'), body_text, body.get('user', '')))
            conn.commit()
            conn.close()
        except Exception:
            pass
        handler.send_json({'ok': True})
    else:
        handler.send_json({'ok': False, 'error': 'No body'}, 400)
