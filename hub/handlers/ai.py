#!/usr/bin/env python3
"""
# 20204007  handlers.ai -- AI chat, AI config endpoints
Hub handler module: AI layer (module 07).
AI stack stays OFF unless explicitly enabled.
"""
import json
import os
import urllib.error
import urllib.request
from datetime import datetime

from kernel.db   import db_conn
from kernel.auth import check_auth, gate_check
from kernel.log  import log_activity
from kernel.ssh  import SSH_HOST, LOCAL_MODE

# One function per route.

# ── Private config helpers (pending move to kernel/config.py) ─────────────────

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
            "INSERT INTO hub_config(key,value,updated) VALUES(?,?,?) ON CONFLICT(key) DO UPDATE SET value=?,updated=?",
            (key, value, ts, value, ts))
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        return str(e)


# ── AI helpers ────────────────────────────────────────────────────────────────

def _ai_system_prompt():
    """Build a concise server-aware system prompt from live state."""
    # Reach into server's live cache for current stats; degrade gracefully if unavailable.
    try:
        import server as _srv
        status     = _srv._cache.get('status') or {}
        containers = _srv._cache.get('containers') or []
    except Exception:
        status, containers = {}, []
    running = [c['name'] for c in containers if c.get('running')]
    lines = [
        'You are an AI assistant with full context about this Linux server.',
        f'Hostname: {SSH_HOST}  |  OS: Ubuntu  |  Mode: {"local" if LOCAL_MODE else "remote"}',
        f'RAM: {status.get("ram_used_mb","?")}MB / {status.get("ram_total_mb","?")}MB  '
        f'|  Disk: {status.get("disk_used","?")} / {status.get("disk_total","?")} ({status.get("disk_pct","?")})',
        f'Load: {status.get("load","?")}  |  Uptime: {status.get("uptime","?")}',
        f'Running containers ({len(running)}): {", ".join(running[:12]) or "none"}',
        '',
        'Answer concisely. For server tasks suggest shell commands. '
        'If shown a photo, describe what you see and relate it to server/infrastructure context if relevant.',
    ]
    return '\n'.join(lines)


def _ai_chat(message, image_b64=None, image_type='image/jpeg'):
    """Call Claude or OpenAI depending on which key is configured."""
    provider = _config_get('ai_provider', 'claude')
    api_key  = _config_get('ai_api_key', os.environ.get('HUB_AI_KEY', ''))
    if not api_key:
        return {'error': 'No AI API key configured. Add one in Hub Settings → AI.'}

    system = _ai_system_prompt()

    try:
        if provider in ('claude', 'anthropic'):
            content = []
            if image_b64:
                content.append({'type': 'image', 'source': {
                    'type': 'base64', 'media_type': image_type, 'data': image_b64}})
            content.append({'type': 'text', 'text': message})
            payload = json.dumps({
                'model': 'claude-opus-5-20251101',
                'max_tokens': 1024,
                'system': system,
                'messages': [{'role': 'user', 'content': content}],
            }).encode()
            req = urllib.request.Request(
                'https://api.anthropic.com/v1/messages',
                data=payload,
                headers={
                    'x-api-key': api_key,
                    'anthropic-version': '2023-06-01',
                    'content-type': 'application/json',
                }, method='POST')
            with urllib.request.urlopen(req, timeout=30) as r:
                data = json.loads(r.read())
            return {'reply': data['content'][0]['text'], 'provider': 'claude'}

        elif provider in ('openai', 'gpt'):
            content = []
            if image_b64:
                content.append({'type': 'image_url', 'image_url': {
                    'url': f'data:{image_type};base64,{image_b64}'}})
            content.append({'type': 'text', 'text': message})
            payload = json.dumps({
                'model': 'gpt-4o',
                'max_tokens': 1024,
                'messages': [
                    {'role': 'system', 'content': system},
                    {'role': 'user', 'content': content if image_b64 else message},
                ],
            }).encode()
            req = urllib.request.Request(
                'https://api.openai.com/v1/chat/completions',
                data=payload,
                headers={
                    'Authorization': f'Bearer {api_key}',
                    'content-type': 'application/json',
                }, method='POST')
            with urllib.request.urlopen(req, timeout=30) as r:
                data = json.loads(r.read())
            return {'reply': data['choices'][0]['message']['content'], 'provider': 'openai'}

        elif provider == 'gemini':
            parts = []
            if image_b64:
                parts.append({'inline_data': {'mime_type': image_type, 'data': image_b64}})
            parts.append({'text': message})
            payload = json.dumps({
                'system_instruction': {'parts': [{'text': system}]},
                'contents': [{'parts': parts}],
                'generationConfig': {'maxOutputTokens': 1024},
            }).encode()
            url = f'https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={api_key}'
            req = urllib.request.Request(url, data=payload,
                headers={'content-type': 'application/json'}, method='POST')
            with urllib.request.urlopen(req, timeout=30) as r:
                data = json.loads(r.read())
            return {'reply': data['candidates'][0]['content']['parts'][0]['text'], 'provider': 'gemini'}

        else:
            return {'error': f'Unknown provider: {provider}'}

    except urllib.error.HTTPError as e:
        body = e.read().decode('utf-8', errors='replace')[:300]
        return {'error': f'API error {e.code}: {body}'}
    except Exception as e:
        return {'error': str(e)}


# ── Route handlers ─────────────────────────────────────────────────────────────

def get_ai_config(handler, path, params):
    """# 20307701  GET /api/ai/config"""
    handler.send_json({
        'provider': _config_get('ai_provider', 'claude'),
        'has_key': bool(_config_get('ai_api_key', os.environ.get('HUB_AI_KEY', ''))),
    })


def post_ai_chat(handler, path, params, body):
    """# 20307702  POST /api/ai/chat"""
    message    = body.get('message', '').strip()
    image_b64  = body.get('image')       # base64 string, no data-URI prefix
    image_type = body.get('image_type', 'image/jpeg')
    ctx        = body.get('context', '')  # server context string from frontend
    if not message and not image_b64:
        handler.send_json({'error': 'No message or image'}, 400)
        return
    full_msg = message or 'Describe this image in the context of my server.'
    if ctx:
        full_msg = f'[Server context: {ctx}]\n\n{full_msg}'
    result = _ai_chat(full_msg, image_b64, image_type)
    # Also log the chat interaction
    log_activity(db_conn, f'AI chat: {message[:80]}', 'user', 'aichat', result.get('provider',''), 'info')
    handler.send_json(result)


def post_ai_config(handler, path, params, body):
    """# 20307703  POST /api/ai/config"""
    provider = body.get('provider', '').strip()
    api_key  = body.get('api_key', '').strip()
    if provider: _config_set('ai_provider', provider)
    if api_key:  _config_set('ai_api_key', api_key)
    handler.send_json({'ok': True})
