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


def _truthy(v):
    return (v or '') in ('1', 'true', 'yes', 'on')


# AGE IS NOT IN THIS API, AND THAT IS A DECISION.
#
# Every timestamp the exchange holds is an ISO string on the server's clock:
# `published`, `at`, `staged_at`, `collected_at`, `closed_at`. No route
# returns "2d ago", and none will. Two clocks are involved in any age -- the
# one the row was written on and the one the reader is looking at -- and the
# only way to get an age with no skew in it is to take BOTH ends from the same
# clock. So every response below carries `now`: the server's clock at the
# moment it answered. The page subtracts, and both operands came from here.
#
# Doing it the other way round -- the server returning `age_seconds` -- is the
# same arithmetic done early, and it goes stale the instant the response is
# cached, proxied or left open in a tab. A board that has been on screen for
# forty minutes would still say "2 minutes ago". `now` does not rot: a stale
# `now` visibly lags, and the page can say so.
#
# What the API therefore owes, and what is checked below: every timestamp a
# screen needs must actually be returned. `published` is on every bulletin
# row, `at` on every matrix row and every trail row, `at` and `closed_at` on
# every ticket.


# ── Bulletins ────────────────────────────────────────────────────────────────

# 20315715  GET /api/bulletins — every bulletin on this server
def get_all_bulletins(handler, path, params):
    """# 20315715  The board's list. Gate 1: reading, not publishing.

    POST /api/bulletins existed and GET did not, so "every bulletin on this
    server" was a question with no address. The only listing route named a
    project, which meant a bulletin scoped to a project you did not think to
    name was invisible -- published, stored, and findable only by opening the
    database by hand.

    ?scope=<project>  only bulletins addressed to exactly that scope
    ?limit=<n>        newest n
    ?readers=1        carry the matrix with the list

    READERS IS OPT-IN AND STAYS OPT-IN. Drawing the board was 1 + N calls:
    the list, then /api/bulletin-readers/<n> once per bulletin -- about 36
    requests across the two boxes for one page. One flag collapses that to
    one request, and it is a flag rather than the default because a caller
    that wants a cheap list must be able to get a cheap list. A bulk matrix
    route would have been the other option; it would have meant two round
    trips to draw one screen, and a second route that can disagree with this
    one about which bulletins exist.

    No pin, ever. The list selects named columns (control.BULLETIN_COLUMNS),
    never `pin` or `secret`.
    """
    scope = (params.get('scope') or '').strip().lower()
    try:
        limit = int(params.get('limit') or 0)
    except Exception:
        limit = 0
    items = _ctl.all_bulletins(scope=scope, limit=limit)
    out = {'ok': True, 'who': _who(), 'now': _ctl.now(),
           'total': len(items), 'scope': scope or 'any',
           'bulletins': items}
    if _truthy(params.get('readers')):
        matrix = _ctl.read_matrix([b['n'] for b in items])
        for b in items:
            m = matrix.get(b['n'])
            if m:
                b['read_count'] = m['read']
                b['told'] = m['total']
                b['readers'] = m['readers']
        out['readers'] = 'included'
    else:
        out['readers'] = ('not included — add ?readers=1, or '
                          'GET /api/bulletin-readers/<n> one at a time')
    handler.send_json(out)


# 20315717  GET /api/bulletin-trail/<n>
def get_bulletin_trail(handler, path, params):
    """# 20315717  Every acknowledgement of one bulletin, in order.

    `reads` is append-only and nothing read it back as a sequence, so a
    project that answered twice showed only its second answer. Same shape as
    outbox's trail, on purpose: one pattern for "what happened to this
    thing", not two.
    """
    raw = _target(path, '/api/bulletin-trail/')
    try:
        n = int(raw)
    except Exception:
        handler.send_json({'ok': False, 'error': 'bulletin number required'}, 400)
        return
    if not _ctl.bulletin(n):
        handler.send_json({'ok': False, 'error': 'no bulletin %d' % n}, 404)
        return
    events = _ctl.bulletin_trail(n)
    handler.send_json({'ok': True, 'bulletin': n, 'who': _who(),
                       'now': _ctl.now(), 'events': len(events),
                       'trail': events})


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
        # Names the project in the hint, because the readout is per recipient
        # now and a bare /api/bulletin/<n> is refused for want of one.
        'next': ('GET /api/bulletin/<n>?project=%s to read one' % project if items
                 else 'nothing waiting'),
    })


# 20315702  GET /api/bulletin/<n>
def get_bulletin(handler, path, params):
    """# 20315702  One bulletin, in full.

    The PIN IS IN THE BODY TEXT, not returned as a field. That is the entire
    mechanism: quoting it back is what proves the thing was actually read
    rather than acknowledged blind.

    ?project=<you> IS NOW REQUIRED, because the code is per recipient. It used
    to be one code printed to everybody, which meant every recipient held the
    proof every other recipient needed — so a project could ack as another. Ask
    for your own copy and you get your own code; the bulletin text is identical.
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
    project = (params.get('project') or '').strip().lower()
    if not project:
        handler.send_json({
            'ok': False, 'error': 'name yourself: ?project=<you>',
            'why': 'the confirmation code is per recipient, so there is no copy '
                   'of this bulletin that is not addressed to somebody',
            'how': 'GET /api/bulletin/%d?project=<you>' % n}, 400)
        return
    pin = _ctl.bulletin_pin(n, project)
    if not pin:
        # Either the bulletin is not addressed to this project, or the project is
        # not one this server knows. Answered as one refusal on purpose: the two
        # are the same outcome and separating them would let a caller enumerate
        # which projects a scoped bulletin was sent to.
        handler.send_json({
            'ok': False, 'error': 'bulletin %d has no copy addressed to %s'
                                  % (n, project),
            'hint': 'GET /api/bulletins/%s lists what is addressed to you'
                    % project}, 404)
        return
    # THE PIN IS RENDERED INTO THE READOUT, not returned as a field.
    #
    # It is not in the stored body either: the body is one text shared by every
    # recipient and the code is not shared, so a code written into the body would
    # be the same code for everybody -- which is exactly what was wrong before.
    # And returning it as its own JSON key would let a project ack by reading one
    # field, which is the skim the PIN exists to prevent.
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
        # Says whose code it is, because it is no longer the bulletin's code. A
        # project pasting a number it was handed by someone else should be able
        # to see, in the text it pasted from, that the number was never its own.
        'Confirmation code for %s: %s' % (project, pin),
        '',
    ])

    handler.send_json({
        'ok': True, 'n': b['n'], 'rung': b['rung'], 'scope': b['scope'],
        'project': project,
        'title': b['title'], 'readout': readout, 'action': b['action'],
        'published': b['published'], 'who': _who(),
        'how_to_acknowledge':
            'POST /api/bulletin/%d/read with {"project":"%s",'
            ' "pin":"<the confirmation code at the end of the readout>",'
            ' "answer":"<what you will do, or none>"}' % (n, project),
        'note': 'the code is yours, not the bulletin\'s -- another project\'s '
                'code will be refused',
    })


# 20315703  POST /api/bulletin/<n>/read
def post_bulletin_read(handler, path, params, body):
    """# 20315703  Acknowledge, with proof.

    A wrong PIN is REFUSED rather than recorded, because a recorded wrong PIN
    is a lie in the matrix. Refused, NOT locked: re-reading is the correct
    response to getting it wrong, and locking would punish the only useful
    reaction.

    An empty answer is refused too. "none" is a valid answer; silence is not.

    WHAT THIS ENDPOINT TRUSTS. `project` is a claim in the body, exactly as
    before -- there is no per-project credential on this server. What changed is
    that the pin is now per (bulletin, project) and derived from a secret the
    server never publishes, so presenting it is proof the caller holds THAT
    project's copy. A project cannot ack as another because it does not hold the
    other's code. See kernel/control.read_bulletin for the three checks.
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
        # 403 when the caller was refused the identity it claimed, 400 when the
        # request was simply incomplete. A project retrying in a loop should be
        # able to tell "I sent the wrong thing" from "this is not mine to ack".
        code = 404 if note == 'no such bulletin' else (
            400 if 'answer required' in note else 403)
        handler.send_json({'ok': False, 'error': note, 'project': project,
                           'reread': 'GET /api/bulletin/%d?project=%s'
                                     % (n, project)}, code)
        return
    handler.send_json({'ok': True, 'bulletin': n, 'project': project,
                       'note': note, 'who': _who(),
                       'remaining': len(_ctl.bulletins_for(project))})


# 20315704  POST /api/bulletins  — the operator publishes
def post_bulletins(handler, path, params, body):
    """# 20315704  Publish a bulletin. Gate 2: this speaks FOR the server.

    NO LONGER RETURNS A PIN, and the old reminder to paste it into the body is
    gone with it: there is no single code any more. Each recipient's readout
    carries that recipient's own, which is what makes presenting one proof of
    whose copy was read.
    """
    title = (body.get('title') or '').strip()
    text = (body.get('body') or '').strip()
    if not title or not text:
        handler.send_json({'ok': False, 'error': 'title and body required'}, 400)
        return
    n, codes = _ctl.publish(title, text, action=body.get('action', 'none'),
                            scope=body.get('scope', 'all'),
                            rung=int(body.get('rung', 1) or 1))
    handler.send_json({
        'ok': True, 'bulletin': n, 'codes': codes, 'who': _who(),
        'reminder': 'Do NOT put a code in the body text. There is one per '
                    'recipient and the readout adds it; a code in the body '
                    'would be the same code for everybody, which proves '
                    'nothing about who read it.',
    })


# 20315705  GET /api/bulletin/<n>/readers — the matrix
def get_bulletin_readers(handler, path, params):
    """# 20315705  Who has read it and who has not.

    The most useful thing the server knows: not whether a project is on the
    current code ref, but whether it has been TOLD. A project can be perfectly
    current and never have heard a word.
    """
    # The ROUTE is /api/bulletin-readers/<n>; this stripped '/api/bulletin/'.
    # So _target() found no prefix to remove, returned '', and int('') raised
    # -- every call answered 400 "bulletin number required", for every input.
    #
    # The readers matrix is the most useful thing the server knows: told vs not
    # told, which is a different question from current vs stale. It has never
    # once answered it.
    raw = _target(path, '/api/bulletin-readers/')
    try:
        n = int(raw)
    except Exception:
        handler.send_json({'ok': False, 'error': 'bulletin number required'}, 400)
        return
    # `total` is now the number of projects the bulletin was ADDRESSED to, not
    # the number of projects on the box. who_read had no scope filter, so a
    # bulletin sent to one project reported "0 of 4" and named the other three
    # as having ignored it. Same field, same meaning it always claimed to have;
    # it just answers truthfully now. Each row also carries `answer` -- what
    # that project said it would do, which the exchange has always insisted on
    # collecting and never once returned.
    rows = _ctl.who_read(n)
    handler.send_json({'ok': True, 'bulletin': n, 'who': _who(),
                       'now': _ctl.now(),
                       'read': sum(1 for r in rows if r['read']),
                       'total': len(rows), 'readers': rows})


# ── Tickets ──────────────────────────────────────────────────────────────────

# 20315706  GET /api/tickets
def get_tickets(handler, path, params):
    """# 20315706  Tickets, optionally ?project=<name>.

    ?state=open|closed|all — DEFAULT STAYS open, so every caller that exists
    today gets exactly what it got before.

    Closed tickets had no address at all. `resolution` is what the project
    actually did about the problem, and the moment it was written was the
    moment it became unreadable: the system could close a ticket and then
    never show why.
    """
    state = (params.get('state') or 'open').strip().lower()
    rows = _ctl.tickets(params.get('project'), state=state)
    handler.send_json({'ok': True, 'who': _who(), 'now': _ctl.now(),
                       'state': state, 'total': len(rows), 'tickets': rows})


# 20315716  GET /api/tickets/<id>
def get_ticket(handler, path, params):
    """# 20315716  One ticket, whatever state it is in.

    Including diagnosis and resolution, which is the whole point: a closed
    ticket is the only record of a self-fix, and nothing could fetch one.
    """
    raw = _target(path, '/api/tickets/')
    try:
        tid = int(raw)
    except Exception:
        handler.send_json({'ok': False, 'error': 'ticket id required'}, 400)
        return
    t = _ctl.ticket_by_id(tid)
    if not t:
        handler.send_json({'ok': False, 'error': 'no ticket %d' % tid}, 404)
        return
    handler.send_json({'ok': True, 'who': _who(), 'now': _ctl.now(),
                       'ticket': t})


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
