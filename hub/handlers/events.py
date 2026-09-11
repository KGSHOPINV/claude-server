#!/usr/bin/env python3
"""
# 20204006  handlers.events -- incidents, activity log endpoints
Hub handler module: events layer (module 06).
"""
import json
from urllib.parse import parse_qs, urlparse

from kernel.db  import db_conn
from kernel.auth import check_auth, gate_check
from kernel.log  import log_activity, activity_recent

# One function per route. Each takes (handler, path, params) or (handler, path, params, body).


def get_incidents(handler, path, params):
    """# 20306701  GET /api/incidents"""
    try:
        conn = db_conn()
        rows = conn.execute(
            "SELECT id, title, body, severity, created_at FROM incidents ORDER BY id DESC LIMIT 50"
        ).fetchall()
        conn.close()
        handler.send_json({'ok': True, 'incidents': [dict(r) for r in rows]})
    except Exception as e:
        handler.send_json({'ok': False, 'error': str(e)}, 500)


def get_activity(handler, path, params):
    """# 20306702  GET /api/activity"""
    # GET /api/activity?limit=100&category=docker
    qs = parse_qs(urlparse(handler.path).query)
    limit = int(qs.get('limit', ['100'])[0])
    cat   = qs.get('category', [None])[0]
    handler.send_json({'ok': True, 'events': activity_recent(db_conn, limit, cat)})


def post_incidents(handler, path, params, body):
    """# 20306703  POST /api/incidents"""
    # POST { title, body?, severity? }
    title = body.get('title', '').strip()
    if not title:
        handler.send_json({'ok': False, 'error': 'title required'}, 400)
        return
    severity = body.get('severity', 'info').strip()
    if severity not in ('info', 'warn', 'critical'):
        severity = 'info'
    incident_body = body.get('body', '')
    try:
        conn = db_conn()
        cur = conn.execute(
            "INSERT INTO incidents (title, body, severity) VALUES (?, ?, ?)",
            (title, incident_body, severity)
        )
        new_id = cur.lastrowid
        conn.commit()
        row = conn.execute(
            "SELECT id, title, body, severity, created_at FROM incidents WHERE id=?",
            (new_id,)
        ).fetchone()
        conn.close()
        handler.send_json({'ok': True, 'incident': dict(row)}, 201)
    except Exception as e:
        handler.send_json({'ok': False, 'error': str(e)}, 500)


def post_activity(handler, path, params, body):
    """# 20306704  POST /api/activity"""
    # POST { action, source?, category?, detail?, level? }
    action = body.get('action', '').strip()
    if not action:
        handler.send_json({'ok': False, 'error': 'action required'}, 400)
        return
    log_activity(
        action   = action,
        source   = body.get('source', 'user'),
        category = body.get('category', 'note'),
        detail   = body.get('detail', ''),
        level    = body.get('level', 'info'),
    )
    handler.send_json({'ok': True})
