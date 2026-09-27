#!/usr/bin/env python3
"""
# 20204017  handlers.outbox — the URLs the outbound side lives on (module 17)

    GET  /api/outbox                  the staging view: what is out, to whom,
                                      what state, whose move it is
    POST /api/outbox/<project>        stage a message. Operator-gated.
    GET  /api/outbox/<project>        THIS project collects what is waiting
    POST /api/outbox-ack/<n>          the project says what it will DO
    POST /api/outbox-address/<p>      the project registers its own callback

WHY THE LAST TWO ARE NOT UNDER /api/outbox/. Two reasons, and both are the
router's, not aesthetics. kernel/router.resolve matches the longest LITERAL
prefix and sorts stably, so a second entry on `/api/outbox/` could never win
against the first -- the same trap handlers/registry.py:_target documents, and
the reason `/api/bulletin-readers/` exists as its own path. And the gates
differ: staging speaks FOR the server (gate 2, the operator), while acking and
registering an address are things a PROJECT does about itself (gate 1). One
prefix cannot carry two gate levels.

This file is routing and refusal. Every decision is made in kernel/outbox.py,
once, for every caller.

NOTHING HERE SENDS ANYTHING BY ITSELF. A message exists because a POST created
it. The session this replaces broke by messaging projects that nobody asked to
be messaged, so the rule is load-bearing:

    "NO YOU DO MESSAGE MOTHER FUCKER THATS WHAT I HAVE BEEN SAYIGN THROUGH THE
     FUCKIGN SERVER."  -- outbound exists, through the server, when you ask.

REPORT, NEVER REPAIR. Nothing here reaches into a project, retries on a
project's behalf, or decides a message was received. Staged is reported as
staged until the project itself takes it.
"""
from kernel import identity as _id
from kernel import outbox as _out
from kernel.db import db_conn
from kernel.log import log_activity


def _who():
    return {'node': _id.node_name(), 'server_id': _id.server_id(),
            'mode': _id.mode()}


def _target(path, prefix):
    """The name or number out of the tail of the path."""
    return path[len(prefix):].split('?')[0].strip('/').lower()


def _pressed_by(handler):
    """Who pressed it. Best effort, and 'unattributed' when unknown -- never
    'system' and never 'serverhub', because a row that names the server as the
    sender is the exact fiction this endpoint exists to make impossible."""
    try:
        from kernel.auth import check_auth
        sess = check_auth(handler) or {}
        return sess.get('user') or 'unattributed'
    except Exception:
        return 'unattributed'


# 20317701  GET /api/outbox — the staging view
def get_outbox_board(handler, path, params):
    """# 20317701  What is staged, to whom, sent or unsent, and who owes what.

    THE-PLAN step 8: "HOLDING CONTIANERS WHERE U MOVE THE BALL EACH TIME".

    `never_collected` is surfaced at the top on purpose. It is the number that
    must never hide inside a total: every one of those is a message the server
    believes it has said and that nobody has read.

    `?project=<name>` narrows it. Reading the board NEVER marks anything
    collected -- see get_outbox_project for why that separation matters.
    """
    b = _out.board(params.get('project'))
    b['ok'] = True
    b['who'] = _who()
    b['reading_this'] = ('Nothing here has been delivered by being listed. '
                         '"staged" means it is sitting on this server and no '
                         'project has taken it.')
    handler.send_json(b)


# 20317702  GET /api/outbox/<project> — the project collects
def get_outbox_project(handler, path, params):
    """# 20317702  What THIS project has waiting. Collecting marks it collected.

    Idempotent: collecting twice returns the same messages and preserves the
    FIRST collection timestamp. A project whose container was rebuilt, or whose
    session lost its scrollback, must be able to come back for the message
    without erasing the record of when it first had it.

    `?peek=1` looks without marking. That exists for the operator, and the
    split is not a convenience: if looking marked things collected, the
    operator checking the board could manufacture evidence that a project had
    read something it has never seen.
    """
    project = _target(path, '/api/outbox/')
    if not project:
        handler.send_json({'ok': False, 'error': 'name the project'}, 400)
        return
    peek = (params.get('peek') or '') in ('1', 'true', 'yes')
    if peek:
        items = _out.waiting_for(project, include_collected=True)
        handler.send_json({
            'ok': True, 'project': project, 'who': _who(), 'peeked': True,
            'messages': items, 'note': 'peek — nothing was marked collected',
        })
        return
    items, note = _out.collect(project, note=params.get('note', ''))
    log_activity(db_conn, 'outbox: %s collected (%s)' % (project, note),
                 'outbox', 'collect', project, 'info')
    handler.send_json({
        'ok': True, 'project': project, 'who': _who(),
        'messages': items, 'note': note,
        'next': ('POST /api/outbox-ack/<message> with {"project":"%s",'
                 '"answer":"what you will do"} — collecting is not answering'
                 % project) if items else 'nothing waiting',
    })


# 20317703  POST /api/outbox/<project> — stage a message
def post_outbox_stage(handler, path, params, body):
    """# 20317703  Stage a message for a project. Gate 2 — the operator.

    Body: {"kind":"intake|reply|note", "body":"...", "subject":"...",
           "expects":"..."}

    With kind `intake` or `reply` and no body, the text is read from
    hub/INTAKE.md -- the file is the one source of that wording, and a copy of
    it in Python would be a second version that wins by being the one that
    runs. If that file cannot be read this REFUSES rather than staging an empty
    message, because an empty message on the board reads as a project owing a
    reply to nothing.

    The response says "staged", never "sent". Nothing has left this machine
    when this returns: the project collects, or its own registered callback is
    pushed by the worker if that worker was started.
    """
    project = _target(path, '/api/outbox/')
    if not project:
        handler.send_json({'ok': False, 'error': 'name the project'}, 400)
        return
    b = body or {}
    kind = (b.get('kind') or 'intake').strip().lower()
    text = (b.get('body') or '').strip()
    source = 'the body of this request'
    if not text:
        text, source = _out.payload_from_intake(kind)
        if not text:
            handler.send_json({'ok': False, 'error': source,
                               'fix': 'send {"body": "..."} explicitly'}, 400)
            return
    n, note = _out.stage(project, text, kind=kind,
                         subject=b.get('subject', ''),
                         expects=b.get('expects', ''),
                         staged_by=_pressed_by(handler))
    if n is None:
        handler.send_json({'ok': False, 'error': note}, 400)
        return
    addr = _out.address(project)
    log_activity(db_conn, 'outbox: staged %s for %s (%s)' % (n, project, kind),
                 'outbox', 'stage', project, 'info')
    handler.send_json({
        'ok': True, 'message': n, 'project': project, 'kind': kind,
        'state': 'staged', 'payload_from': source, 'note': note, 'who': _who(),
        # Said out loud on every stage, because "I pressed it" and "it arrived"
        # are the two things this whole file exists to keep apart.
        'delivered': False,
        'how_it_reaches_them': (
            'GET /api/outbox/%s — it collects. %s' % (
                project,
                ('A callback is registered (%s) so the worker will also push '
                 'it, and will record the failure if that fails.' % addr['url'])
                if addr else
                ('%s has registered no callback, so nothing is pushed. This '
                 'is the normal case.' % project))),
        'worker': _out.worker_state(),
    })


# 20317704  POST /api/outbox-ack/<n> — the project answers
def post_outbox_ack(handler, path, params, body):
    """# 20317704  Acknowledge one message. Gate 1 — the project's own act.

    Body: {"project":"<you>", "answer":"what you will do"}

    Collection is not agreement. A project that pulled a message and said
    nothing has been told nothing that can be evidenced, which is the same trap
    control.acknowledge was written against one layer in.

    An empty answer is refused. "none" is a valid answer; silence is not.
    """
    raw = _target(path, '/api/outbox-ack/')
    try:
        n = int(raw)
    except Exception:
        handler.send_json({'ok': False, 'error': 'message number required'}, 400)
        return
    b = body or {}
    project = (b.get('project') or '').strip().lower()
    answer = (b.get('answer') or b.get('note') or '').strip()
    got, note = _out.acknowledge(n, project, answer)
    if got is None:
        handler.send_json({'ok': False, 'error': note, 'message': n}, 400)
        return
    log_activity(db_conn, 'outbox: %s acknowledged message %s' % (project, n),
                 'outbox', 'ack', project, 'info')
    handler.send_json({'ok': True, 'message': n, 'project': project,
                       'note': note, 'who': _who(), 'trail': _out.trail(n)})


# 20317705  POST /api/outbox-address/<project> — register a callback
def post_outbox_address(handler, path, params, body):
    """# 20317705  A project hands over its own doorbell. Gate 1. OPTIONAL.

    Body: {"url":"https://..."} — or {"url":"none"} to remove it.

    THE ISOLATION RULE, as code: the hub never DERIVES this. It does not read
    it off `docker ps`, does not guess it from a published port, does not infer
    it from a claim. If a project has not registered a URL here, the hub has no
    way to reach it and that is the intended resting state.

    A loopback address is refused. A callback pointed at 127.0.0.1 would have
    the hub POSTing into a host port on this machine, which is reaching into a
    container by another name -- and would let one project aim the hub at the
    hub's own API.

    WHAT THIS CANNOT PROVE: there is no per-project credential on this server
    today, so the hub cannot verify the caller registering an address for
    `fksinv` is fksinv. The session that POSTed is recorded and the URL is on
    the board where the operator sees it. That is visibility, not proof, and
    calling it proof would be the lie.
    """
    project = _target(path, '/api/outbox-address/')
    if not project:
        handler.send_json({'ok': False, 'error': 'name the project'}, 400)
        return
    got, note = _out.register_address(project, (body or {}).get('url', ''),
                                      by=_pressed_by(handler))
    if got is None:
        handler.send_json({'ok': False, 'error': note, 'project': project}, 400)
        return
    log_activity(db_conn, 'outbox: callback for %s — %s' % (project, note),
                 'outbox', 'address', project, 'info')
    handler.send_json({'ok': True, 'project': project, 'note': note,
                       'who': _who(), 'registered': _out.address(project),
                       'worker': _out.worker_state()})
