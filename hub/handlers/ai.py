#!/usr/bin/env python3
"""
# 20204007  handlers.ai -- AI chat, AI config endpoints
Hub handler module: AI layer (module 07).
AI stack stays OFF unless explicitly enabled.

LAW V, AND WHY THIS FILE NO LONGER NEEDS AN EXCEPTION TO IT
-----------------------------------------------------------
CONSTITUTION.md, Law V:

    "Credentials are never here. Pointers only."

This file used to break that silently. POST /api/ai/config took an `api_key`
out of a request body and wrote it into the `hub_config` table of
`db/server.db` in plaintext -- and hub/tools/backup.sh copies server.db BY
NAME, so the key would have been duplicated into every nightly backup set on
the data disk, with no TTL, no revocation and nothing saying it was there. The
Gemini branch additionally put it in a URL QUERY STRING, which is the one place
a secret is guaranteed to be written down by something you do not control.

Zero rows held a key on either box when this was found, so nothing leaked. It
was latent, which is the only reason this is a repair and not an incident.

The repo has two Law V exceptions and this is not a third:

    kernel/bank.py      a TEMPORARY handoff. Read-once, 24h TTL, and
                        exception_open() FAILS install-preflight for as long as
                        anything is in it, so it cannot quietly become
                        architecture.
    kernel/svctoken.py  a PERMANENT resident that has nowhere else to live. Own
                        0600 file, never the database, never a log, and it says
                        so in every status() response.

The AI key is the shape svctoken.py explicitly warns must never go in the bank
-- long-lived, read on every request, expected to still be here in six months
-- so the bank is wrong for it: the TTL would silently expire it and it would
hold exception_open() permanently true, destroying the one assertion that keeps
the bank's exception temporary.

But it does not need svctoken's exception either, because unlike a service
token it ALREADY HAD a pointer source: $HUB_AI_KEY, which _ai_chat has read as
a fallback the whole time. So the answer is neither exception. The key is not
stored here at all; the hub reads a pointer.

WHAT THAT MEANS IN PRACTICE:

  * post_ai_config REFUSES an api_key and names the two places to put it.
  * _ai_key reads $HUB_AI_KEY, then ~/.server-alerts.conf -- the same file
    kernel/log.py already sources NTFY_TOKEN from, mode 0600.
  * a key left in hub_config from before this change does not quietly keep
    working. Every AI route REFUSES while that row exists and says how to
    clear it, which is the same discipline bank.py applies: the exception
    fails something for as long as it is open.
  * no function here returns, logs or interpolates the value. get_ai_config
    reports the SOURCE NAME and nothing else.
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

# The two places a key may come from. Both are POINTERS: an environment
# variable this process was started with, and a 0600 file this box already
# uses for exactly this class of value. Neither is written by the hub.
KEY_ENV  = 'HUB_AI_KEY'
KEY_CONF = '~/.server-alerts.conf'
KEY_CONF_NAMES = ('HUB_AI_KEY', 'ANTHROPIC_API_KEY')

# The row that must not exist. Named once, here, so the detector and the
# refusal cannot drift apart.
LEGACY_ROW = 'ai_api_key'


# 20207303  _ai_key — the key, from a pointer, never from the database
def _ai_key():
    """Return (value, source_name). The VALUE is never logged or returned to a
    caller; only the source name is ever printed anywhere."""
    v = os.environ.get(KEY_ENV, '').strip()
    if v:
        return v, '$' + KEY_ENV
    try:
        with open(os.path.expanduser(KEY_CONF), encoding='utf-8') as fh:
            for line in fh:
                line = line.strip()
                for name in KEY_CONF_NAMES:
                    if line.startswith(name + '='):
                        val = line.split('=', 1)[1].strip().strip('\'"')
                        if val:
                            return val, '%s (%s=)' % (KEY_CONF, name)
    except Exception:
        pass
    return '', ''


# 20207304  _legacy_key_row — the Law V breach, if one is still in the database
def _legacy_key_row():
    """True while a plaintext key sits in hub_config.

    This is the announce-and-refuse half. bank.py's exception_open() fails
    install-preflight while the bank holds anything; this fails the AI routes
    while server.db holds a key, for the same reason: an exception that stops
    complaining has become architecture. Reads whether the row EXISTS. It never
    reads the value.
    """
    try:
        conn = db_conn()
        row = conn.execute(
            "SELECT 1 FROM hub_config WHERE key=? AND value IS NOT NULL AND value!=''",
            (LEGACY_ROW,)).fetchone()
        conn.close()
        return bool(row)
    except Exception:
        return False


LEGACY_REFUSAL = (
    'A plaintext AI key is stored in hub_config in db/server.db. That file is '
    'copied by tools/backup.sh by name, so the key is in every backup set. The '
    'AI routes refuse until it is gone. Clear it with: '
    'sqlite3 db/server.db "DELETE FROM hub_config WHERE key=\'ai_api_key\';" '
    'then put the key in $HUB_AI_KEY or in ~/.server-alerts.conf (mode 600).'
)


# 20207301  _ai_system_prompt — server-aware system prompt from cached status
def _ai_system_prompt():
    """Build a concise server-aware system prompt from live state."""
    # Reach into server's live cache for current stats; degrade gracefully if unavailable.
    try:
        from kernel import collect as _srv
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


# 20207302  _ai_chat — dispatch to Claude/OpenAI/Gemini by configured provider
def _ai_chat(message, image_b64=None, image_type='image/jpeg'):
    """Call Claude or OpenAI depending on which key is configured."""
    if _legacy_key_row():
        return {'error': LEGACY_REFUSAL}
    provider = _config_get('ai_provider', 'claude')
    api_key, source = _ai_key()
    if not api_key:
        return {'error': 'No AI API key available. Set $%s, or add a %s line to %s '
                         '(mode 600). The hub does not store keys.'
                         % (KEY_ENV, KEY_CONF_NAMES[0], KEY_CONF)}

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
            # HEADER, NOT ?key=. A query string is the one place a secret is
            # guaranteed to be written down by something you do not control:
            # proxy logs, the server's own access log, a browser history, a
            # Referer. x-goog-api-key is Google's documented equivalent and
            # carries the same value in a place nothing routinely records.
            url = ('https://generativelanguage.googleapis.com/v1beta/models/'
                   'gemini-2.0-flash:generateContent')
            req = urllib.request.Request(url, data=payload,
                headers={'content-type': 'application/json',
                         'x-goog-api-key': api_key}, method='POST')
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
    """# 20307701  GET /api/ai/config

    Reports the SOURCE, never the value. `key_source` is an environment
    variable name or a file path — a pointer, which is the only thing Law V
    allows this hub to hold.
    """
    key, source = _ai_key()
    out = {
        'provider':   _config_get('ai_provider', 'claude'),
        'has_key':    bool(key),
        'key_source': source or None,
        'key_accepted_from': ['$' + KEY_ENV, '%s (%s=)' % (KEY_CONF, KEY_CONF_NAMES[0])],
        'stores_key': False,
    }
    # Said out loud rather than left to be discovered, the way
    # svctoken.status() announces its own exception.
    if _legacy_key_row():
        out['law_v_breach_open'] = LEGACY_REFUSAL
    handler.send_json(out)


def post_ai_chat(handler, path, params, body):
    """# 20307702  POST /api/ai/chat"""
    message    = body.get('message', '').strip()
    image_b64  = body.get('image')       # base64 string, no data-URI prefix
    image_type = body.get('image_type', 'image/jpeg')
    ctx        = body.get('context', '')  # server context string from frontend
    if _legacy_key_row():
        handler.send_json({'error': LEGACY_REFUSAL}, 409)
        return
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
    """# 20307703  POST /api/ai/config

    Sets the provider. REFUSES a key.

    This used to accept `api_key` and write it straight into hub_config. The
    refusal is a 400 rather than a silent drop because a settings form that
    says "saved" and stored nothing is worse than one that says no: the
    operator would believe the key was in place and spend the next hour
    debugging the AI provider.
    """
    provider = body.get('provider', '').strip()
    if body.get('api_key', '').strip():
        handler.send_json({
            'error': 'This hub does not store API keys. Put the key in $%s, or '
                     'in %s as %s=<key> with mode 600, and restart the hub. '
                     'Law V: credentials are never here, pointers only.'
                     % (KEY_ENV, KEY_CONF, KEY_CONF_NAMES[0]),
            'accepted_from': ['$' + KEY_ENV, '%s (%s=)' % (KEY_CONF, KEY_CONF_NAMES[0])],
        }, 400)
        return
    if provider:
        _config_set('ai_provider', provider)
    handler.send_json({'ok': True, 'stores_key': False})
