#!/usr/bin/env python3
"""
# 20204015  handlers.exchange — the URLs a project reads and answers on

kernel/control.py has held all of this since it was written and none of it was
reachable, so it could only be called from a tool on the box. Which meant the
operator was still carrying every message by hand -- the exact thing the
exchange exists to stop.

This file is routing and nothing else. No logic lives here: every function
below hands straight to control.py or bank.py. If something needs deciding, it
gets decided there, once, for every caller.

THE LADDER
    rung 1  you are already in this server
    rung 2  where this server is going
    rung 3  what that means for you

Ordered, because a project cannot judge what is CHANGING until it has confirmed
what IS. bulletins_for returns oldest first for that reason.

NOTHING HERE BLOCKS ANYTHING. A bulletin that stopped a deploy would make
reading it a chore to route around. One that only records who read it makes
reading it the cheapest way to avoid a surprise.
"""
from kernel import control as _ctl
from kernel import bank as _bank
from kernel import identity as _id


def _who():
    return {'node': _id.node_name(), 'server_id': _id.server_id(),
            'mode': _id.mode()}


def _target(path, prefix):
    """The project name out of the tail of the path."""
    return path[len(prefix):].split('?')[0].strip('/')


# ── Bulletins ────────────────────────────────────────────────────────────────

# 20315701  GET /api/bulletins/<project>
def get_bulletins(handler, path, params):
    """# 20315701  What this project has not read yet.

    ?all=1 includes what it has already acknowledged.
    """
    project = _target(path, '/api/bulletins/')
    if not project:
        handler.send_json({'ok': False, 'error': 'name the project'}, 400)
        return
    unread_only = (params.get('all') or '') not in ('1', 'true', 'yes')
    items = _ctl.bulletins_for(project, unread_only=unread_only)
    handler.send_json({
        'ok': True, 'project': project, 'who': _who(),
        'unread': len(items), 'bulletins': items,
        'next': ('GET /api/bulletin/<n> to read one' if items
                 else 'nothing waiting'),
    })


# 20315702  GET /api/bulletin/<n>
def get_bulletin(handler, path, params):
    """# 20315702  One bulletin, in full.

    The PIN IS IN THE BODY TEXT, not returned as a field. That is the entire
    mechanism: quoting it back is what proves the thing was actually read
    rather than acknowledged blind.
    """
    raw = _target(path, '/api/bulletin/')
    try:
        n = int(raw)
    except Exception:
        handler.send_json({'ok': False, 'error': 'bulletin number required'}, 400)
        return
    b = _ctl.bulletin(n)
    if not b:
        handler.send_json({'ok': False, 'error': 'no bulletin %d' % n}, 404)
        return
    # THE PIN IS RENDERED INTO THE READOUT, not returned as a field.
    #
    # It cannot be written into the stored body: control.publish derives it
    # FROM that body, so a body containing it could not exist. And returning it
    # as its own JSON key would let a project ack by reading one field, which
    # is the exact skim the PIN exists to prevent.
    #
    # So it is woven into the text at the end, where you reach it by reading to
    # the end. Self-contained, no links out -- what makes the PIN mean
    # absorption rather than a glance.
    readout = '\n'.join([
        b['title'],
        '=' * len(b['title']),
        '',
        b['body'],
        '',
        '--- confirm you read this ---',
        'The one thing you do: %s' % (b['action'] or 'nothing right now'),
        'Confirmation code: %s' % b['pin'],
        '',
    ])

    handler.send_json({
        'ok': True, 'n': b['n'], 'rung': b['rung'], 'scope': b['scope'],
        'title': b['title'], 'readout': readout, 'action': b['action'],
        'published': b['published'], 'who': _who(),
        'how_to_acknowledge':
            'POST /api/bulletin/%d/read with {"project":"<you>",'
            ' "pin":"<the confirmation code at the end of the readout>",'
            ' "answer":"<what you will do, or none>"}' % n,
    })


# 20315703  POST /api/bulletin/<n>/read
def post_bulletin_read(handler, path, params, body):
    """# 20315703  Acknowledge, with proof.

    A wrong PIN is REFUSED rather than recorded, because a recorded wrong PIN
    is a lie in the matrix. Refused, NOT locked: re-reading is the correct
    response to getting it wrong, and locking would punish the only useful
    reaction.

    An empty answer is refused too. "none" is a valid answer; silence is not.
    """
    raw = _target(path, '/api/bulletin/').replace('/read', '')
    try:
        n = int(raw)
    except Exception:
        handler.send_json({'ok': False, 'error': 'bulletin number required'}, 400)
        return
    project = (body.get('project') or '').strip()
    if not project:
        handler.send_json({'ok': False, 'error': 'name yourself: {"project":"..."}'}, 400)
        return
    got, note = _ctl.read_bulletin(project, n, body.get('pin', ''),
                                   body.get('answer', ''))
    if got is None:
        handler.send_json({'ok': False, 'error': note, 'project': project,
                           'reread': 'GET /api/bulletin/%d' % n}, 400)
        return
    handler.send_json({'ok': True, 'bulletin': n, 'project': project,
                       'note': note, 'who': _who(),
                       'remaining': len(_ctl.bulletins_for(project))})


# 20315704  POST /api/bulletins  — the operator publishes
def post_bulletins(handler, path, params, body):
    """# 20315704  Publish a bulletin. Gate 2: this speaks FOR the server."""
    title = (body.get('title') or '').strip()
    text = (body.get('body') or '').strip()
    if not title or not text:
        handler.send_json({'ok': False, 'error': 'title and body required'}, 400)
        return
    n, pin = _ctl.publish(title, text, action=body.get('action', 'none'),
                          scope=body.get('scope', 'all'),
                          rung=int(body.get('rung', 1) or 1))
    handler.send_json({
        'ok': True, 'bulletin': n, 'pin': pin, 'who': _who(),
        'reminder': 'Put the PIN in the BODY text. A PIN nobody can find in '
                    'what they read proves nothing.',
    })


# 20315705  GET /api/bulletin/<n>/readers — the matrix
def get_bulletin_readers(handler, path, params):
    """# 20315705  Who has read it and who has not.

    The most useful thing the server knows: not whether a project is on the
    current code ref, but whether it has been TOLD. A project can be perfectly
    current and never have heard a word.
    """
    raw = _target(path, '/api/bulletin/').replace('/readers', '')
    try:
        n = int(raw)
    except Exception:
        handler.send_json({'ok': False, 'error': 'bulletin number required'}, 400)
        return
    rows = _ctl.who_read(n)
    handler.send_json({'ok': True, 'bulletin': n, 'who': _who(),
                       'read': sum(1 for r in rows if r['read']),
                       'total': len(rows), 'readers': rows})


# ── Tickets ──────────────────────────────────────────────────────────────────

# 20315706  GET /api/tickets
def get_tickets(handler, path, params):
    """# 20315706  Open tickets, optionally ?project=<name>."""
    handler.send_json({'ok': True, 'who': _who(),
                       'tickets': _ctl.open_tickets(params.get('project'))})


# 20315707  POST /api/tickets
def post_tickets(handler, path, params, body):
    """# 20315707  File BEFORE self-fixing.

    Closing takes `resolution`: what the project ACTUALLY DID. An unrecorded
    self-fix is indistinguishable from drift six weeks later.
    """
    action = (body.get('action') or 'open').strip()
    if action == 'open':
        project = (body.get('project') or '').strip()
        problem = (body.get('problem') or '').strip()
        if not project or not problem:
            handler.send_json({'ok': False,
                               'error': 'project and problem required'}, 400)
            return
        tid, state = _ctl.ticket(project, problem, body.get('what_i_see', ''))
        handler.send_json({'ok': True, 'ticket': tid, 'state': state,
                           'who': _who(),
                           'note': 'An open ticket blocks auto-baseline for '
                                   'this project. Silence is not evidence.'})
        return
    try:
        tid = int(body.get('ticket'))
    except Exception:
        handler.send_json({'ok': False, 'error': 'ticket id required'}, 400)
        return
    if action == 'diagnose':
        got, state = _ctl.diagnose(tid, body.get('diagnosis', ''))
    elif action == 'close':
        res = (body.get('resolution') or '').strip()
        if not res:
            handler.send_json({'ok': False, 'error':
                               'resolution required: say what you actually did'}, 400)
            return
        got, state = _ctl.close_ticket(tid, res)
    else:
        handler.send_json({'ok': False,
                           'error': 'action must be open|diagnose|close'}, 400)
        return
    handler.send_json({'ok': True, 'ticket': got, 'state': state, 'who': _who()})


# ── A project's own log, kept outside its container ──────────────────────────

# 20315708  GET /api/project-log/<project>
def get_project_log(handler, path, params):
    """# 20315708  What this project has recorded about itself."""
    project = _target(path, '/api/project-log/')
    if not project:
        handler.send_json({'ok': False, 'error': 'name the project'}, 400)
        return
    try:
        limit = int(params.get('limit') or 50)
    except Exception:
        limit = 50
    handler.send_json({'ok': True, 'project': project, 'who': _who(),
                       'activity': _ctl.activity(project, limit)})


# 20315709  POST /api/project-log/<project>
def post_project_log(handler, path, params, body):
    """# 20315709  A project writes its own history.

    It lives in a container; this table does not. When the container is rebuilt
    or pruned its own logs go with it. Anything that must still be true
    afterwards belongs out here.

    Deliberately unstructured: a deploy, a decision, a rollback, a note to
    whoever reads it in six months. The server keeps it and does not interpret.
    """
    project = _target(path, '/api/project-log/')
    text = (body.get('body') or '').strip()
    if not project or not text:
        handler.send_json({'ok': False, 'error': 'project and body required'}, 400)
        return
    n, kind = _ctl.log_project(project, text, body.get('kind', 'note'))
    handler.send_json({'ok': True, 'entry': n, 'kind': kind,
                       'project': project, 'who': _who()})


# ── Baselines ────────────────────────────────────────────────────────────────

# 20315710  GET /api/baselines/<project>
def get_baselines(handler, path, params):
    """# 20315710  The ladder for this project, and whether auto is due.

    'saved' is a claim someone made. 'auto' is seven quiet days. Never merged,
    because a restore has to know which it is trusting.
    """
    project = _target(path, '/api/baselines/')
    if not project:
        handler.send_json({'ok': False, 'error': 'name the project'}, 400)
        return
    due, why = _ctl.auto_baseline_eligible(project)
    handler.send_json({'ok': True, 'project': project, 'who': _who(),
                       'baselines': _ctl.baselines(project),
                       'auto_due': due, 'auto_why': why})


# 20315711  POST /api/baselines/<project>
def post_baselines(handler, path, params, body):
    """# 20315711  save | checkpoint | release."""
    project = _target(path, '/api/baselines/')
    if not project:
        handler.send_json({'ok': False, 'error': 'name the project'}, 400)
        return
    action = (body.get('action') or 'save').strip()
    if action == 'save':
        n, kind = _ctl.save_baseline(project, body.get('label', ''))
    elif action == 'checkpoint':
        n, kind = _ctl.checkpoint(project, body.get('label', 'pre-deploy'))
    elif action == 'release':
        try:
            n, kind = _ctl.release_checkpoint(int(body.get('id')))
        except Exception:
            handler.send_json({'ok': False, 'error': 'id required'}, 400)
            return
    else:
        handler.send_json({'ok': False,
                           'error': 'action must be save|checkpoint|release'}, 400)
        return
    handler.send_json({'ok': True, 'baseline': n, 'kind': kind,
                       'project': project, 'who': _who()})


# ── The holding bank ─────────────────────────────────────────────────────────

# 20315712  GET /api/bank — what is held. NEVER the values.
def get_bank(handler, path, params):
    """# 20315712  What the bank holds, and that the exception is open.

    Slots, scopes, notes, expiry and read counts. No value is ever returned
    here, by any parameter, under any condition.
    """
    is_open, note = _bank.exception_open()
    handler.send_json({
        'ok': True, 'who': _who(), 'held': _bank.held(),
        'reads': _bank.read_log(20),
        'exception_open': is_open, 'note': note,
        'law': 'Breaks CONSTITUTION Law V on purpose and temporarily. While '
               'anything is held, install-preflight --strict cannot pass '
               'clean. Delete this the day FlareVault can do it properly.',
    })


# 20315713  POST /api/bank — deposit | revoke
def post_bank(handler, path, params, body):
    """# 20315713  Gate 2. Depositing means handing the server a secret."""
    action = (body.get('action') or 'deposit').strip()
    if action == 'revoke':
        slot, note = _bank.revoke((body.get('slot') or '').strip())
        handler.send_json({'ok': True, 'slot': slot, 'note': note})
        return
    slot, note = _bank.deposit(
        (body.get('slot') or '').strip(), body.get('value') or '',
        scope=body.get('scope', 'project'), owner=body.get('owner', ''),
        note=body.get('note', ''), ttl_hours=body.get('ttl_hours'))
    if slot is None:
        handler.send_json({'ok': False, 'error': note}, 400)
        return
    # The value is echoed back nowhere. Not on success, not in an error.
    handler.send_json({'ok': True, 'slot': slot, 'note': note, 'who': _who()})


# 20315714  POST /api/bank/collect — a project takes its secret
def post_bank_collect(handler, path, params, body):
    """# 20315714  Collect. Project scope is DELETED on collection.

    Account scope is not -- a second project would find it gone -- so that one
    is bounded by TTL and revocation instead, and every read is recorded. One
    project leaking a shared key burns all of them, and the log is what tells
    you which.
    """
    slot = (body.get('slot') or '').strip()
    project = (body.get('project') or '').strip()
    if not slot or not project:
        handler.send_json({'ok': False, 'error': 'slot and project required'}, 400)
        return
    value, note = _bank.collect(slot, project)
    if value is None:
        handler.send_json({'ok': False, 'error': note, 'slot': slot}, 404)
        return
    handler.send_json({'ok': True, 'slot': slot, 'value': value, 'note': note,
                       'warning': 'Store this properly now. It will not be '
                                  'served again.'})
