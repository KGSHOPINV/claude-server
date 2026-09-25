#!/usr/bin/env python3
"""
# 20200018  kernel.changewatch — the server notices its own changes and says so

THE BUG THIS EXISTS FOR. kernel/control.publish() had exactly one caller: the
operator-gated route POST /api/bulletins. So a bulletin existed only because a
human sat down and wrote one. The registry recorded who arrived and then never
told them anything again -- and the proof is in this repo's own history: the
project port band moved off 7100-7899 with the acknowledgement list EMPTY.
Nothing in the running system noticed, because nothing was looking.

    "MOVING THROUGH INFORMING THEM ABOUT THE CIRCOMSTANCES OF THE SERVER IF
     PORTS CHANGE THIS IS WHAT WERE DOING IF THIS SERVER CHANGE HAPPENS"
    "NO NOT JUST THAT THE WHOLE FUCKIN EXCAHNGE FOR HOW TO ALSO KNOW WHERE THE
     FUCKING SERVER IS GOING TO BE HAVING CHANGES OF ALSO ORGINAATION TOOO"
                                            -- THE-PLAN.md section 2, step 12

Ports AND organisation. Both are in here.

A CHANGE, NOT A STATE. This compares today's derived facts against the last
ones it recorded and fires only on a difference. That distinction is the whole
module. Firing every scan is spam and gets muted; firing never is the bug we
started with. There is no third behaviour worth having.

WHAT EARNS A BULLETIN. plan/STATE.md draws the line and it is not negotiable:

    "Version bumps only on things a project could have to ACT on -- bands, data
     paths, isolation rules, a project arriving or leaving, direction. Not on
     live readings like current port usage or disk percent."

So: the project port band, the port lane map, the data root, the roster, the
code ref. Deliberately NOT: containers starting and stopping, RAM, disk
percent, uptime, load, which ports inside the band happen to be bound right
now. _do_port_snapshot() in collect.py already records ports appearing and
disappearing as port_events, and those stay port_events forever -- a container
restart is an event, not a bulletin. Get this wrong and the stream becomes
noise, people mute it, and a muted stream is the same as no stream at all.

THE LADDER. Everything here is rung 2 -- "here is where this server is going".
Never rung 1. Rung 1 is "you are already in this server", which is a readout of
what the hub sees of ONE project, written against that project's own claim; it
is the operator's message and a diff of server-wide facts cannot compose it.
Targeted rung 3 ("what that means for you") needs a project's position on the
change, which lives in control.record_diffs and is likewise a human's call.
Publishing rung 2 with rung 1 outstanding does not break the gate: bulletins_for
returns oldest first, so these land AFTER whatever rung 1 is already waiting.

NOTHING HERE BLOCKS. Same rule as everything else on this side of the house. If
publishing fails the scan carries on, the baseline for that fact is left where
it was, and the next sweep tries again. A watcher that could stall the port
scan would be a worse bug than the one it fixes.

ONE BULLETIN PER CHANGED FACT, not one per sweep. This is forced by the rule
that every bulletin ends with THE ONE THING THEY DO -- a bundled bulletin
covering a band move and a data root move has two one-things, which is none.
It is not an answer to the open question in STATE.md about whether the whole
restructuring is one bulletin or many; that question is about the narrative an
operator writes, and this writes no narrative.

THE ACID TEST -- does it pass?
    The band on this branch moved 7100-7899/20 -> 12000-18999/100 while no
    project had been told. Would this have caught it and published?

    YES, with one condition, stated honestly: this must already have been
    running, with a baseline recorded, BEFORE the move. Then the sequence is:
    old hub running, baseline on disk says 7100-7899/20; operator pulls and
    restarts; first sweep reads 12000-18999/100 out of collect; different;
    bulletin. The baseline is a file, not memory, precisely so a restart in the
    middle of that sequence does not erase the before-picture.

    It was NOT running before that move, so THAT bulletin -- the one that is
    already owed -- still has to be written by hand. This stops the next one.

    WHAT IT CAN SEE: PROJECT_BAND_FLOOR/CEIL/SIZE are constants in
    collect.py's source, not derived state, and this reads them as VALUES at
    runtime through the imported module. That is enough, because a source
    constant only reaches the running server through a restart, and a restart
    is exactly when a sweep re-reads them. There is no window where the hub is
    handing out ports from a band this module cannot see -- /api/admit reads
    the same imported constants.

    WHAT IT CANNOT SEE: an edit to the constant that has not been deployed and
    restarted. It reports what the server IS doing, never what a commit in a
    branch intends. That is the correct limit -- announcing an undeployed
    branch would tell projects to move onto a band the server is not serving.
    It also cannot see anything the machine does not answer: the storage
    template and the public/private isolation rule are proposals in STATE.md
    with nothing on disk behind them, so there is no fact here to diff and no
    bulletin to write until they exist.
"""
import json
import os
import subprocess
import threading

from kernel import control as _ctl

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# WHERE THE BASELINE LIVES, and why it is not a table.
#
# Next to control.db, which is the record of what projects were TOLD. What they
# were told and what they were told it against belong on the same disk and in
# the same backup; splitting them gives you a bulletin history you cannot read
# in context.
#
# Not a table IN control.db: that file has one schema owner, control.ensure_
# tables(), and a second module quietly issuing CREATE TABLE against it is the
# start of two sources of truth. Not server.db either -- that is live state and
# is rebuilt without ceremony. This is one small dict and a file holds it
# honestly.
BASELINE_PATH = os.environ.get(
    'HUB_CHANGEWATCH',
    os.path.join(os.path.dirname(_ctl.CONTROL_DB), 'changewatch.json'))

_lock = threading.Lock()

# A fact that is absent from a sweep is UNDERIVABLE, not changed. findmnt can
# fail, git can be missing, SSH can be down. Treating a transient failure as
# "the data root disappeared" would publish a lie, and a lie in this stream
# costs more than a missed bulletin.
_MISSING = object()


# 20200602  _facts — the watched facts, derived fresh, live readings excluded
def _facts():
    """Only what a project could have to ACT on. Every key here is omitted
    rather than guessed when the machine will not answer."""
    out = {}

    try:
        from kernel import collect as _collect
        out['band'] = '%d-%d/%d' % (_collect.PROJECT_BAND_FLOOR,
                                    _collect.PROJECT_BAND_CEIL,
                                    _collect.PROJECT_BAND_SIZE)
        # The lane map is the "ORGINAATION TOOO" half of step 12: a project
        # needs to know the shape of the whole port space, not just its own
        # slice, or it cannot tell a free port from someone else's lane.
        #
        # The lane that IS the project band is skipped on purpose -- it is the
        # same fact wearing a second hat, and reporting it twice would publish
        # two bulletins for one move.
        lanes = {}
        band_ranges = [(_collect.PROJECT_BAND_FLOOR, _collect.PROJECT_BAND_CEIL)]
        for lane in _collect.PORT_LANES:
            if list(lane.get('ranges') or []) == band_ranges:
                continue
            lanes[lane['name']] = ', '.join(
                '%d-%d' % (lo, hi) if lo != hi else str(lo)
                for lo, hi in lane.get('ranges') or [])
        out['lanes'] = lanes
    except Exception:
        pass

    try:
        from kernel import storage as _storage
        # landscape() is cached, so this rides the cache the rest of the hub
        # already warms instead of spawning its own findmnt every five minutes.
        dr = (_storage.landscape() or {}).get('data_root') or {}
        path = dr.get('path')
        if path:
            out['data_root'] = '%s (%s)' % (
                path, 'dedicated disk' if dr.get('dedicated')
                else 'OS disk, no dedicated data mount')
    except Exception:
        pass

    try:
        # Arriving and leaving only. A project changing dev -> production is
        # its own business and nobody else has to act on it.
        reg = _ctl.registry() or {}
        out['roster'] = sorted(p.get('name', '') for p in (reg.get('projects') or []))
    except Exception:
        pass

    try:
        r = subprocess.run(['git', 'rev-parse', '--short', 'HEAD'],
                           cwd=os.path.dirname(BASE_DIR),
                           capture_output=True, text=True, timeout=5)
        ref = r.stdout.strip() if r.returncode == 0 else ''
        if ref:
            out['master'] = ref
    except Exception:
        pass

    return out


# 20200603  _load — the last facts we actually announced, or None on first run
def _load():
    try:
        with open(BASELINE_PATH, encoding='utf-8') as f:
            d = json.load(f)
        return d if isinstance(d, dict) else None
    except Exception:
        return None


# 20200604  _save — atomic, because a half-written baseline re-announces
def _save(facts):
    """os.replace, not a plain write. A baseline truncated by a power cut would
    read back as first-run and re-announce the entire server to everyone."""
    try:
        os.makedirs(os.path.dirname(BASELINE_PATH), exist_ok=True)
        tmp = BASELINE_PATH + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(facts, f, indent=2, sort_keys=True)
        os.replace(tmp, BASELINE_PATH)
        return True
    except Exception:
        return False


# 20200605  _wording — one changed fact becomes the bulletins it is worth
def _wording(key, old, new):
    """Returns a list of (title, body, action) -- a list because a roster
    change can be several arrivals and departures at once, and each one is its
    own thing with its own answer.

    ACTION IS NEVER EMPTY and "nothing right now" is the common case. It is
    handed to control.publish as the action field, which handlers/exchange.py
    renders as the last line of the readout -- so the body must NOT repeat it,
    or every bulletin ends by saying the same thing twice. The rule from
    STATE.md is that a bulletin ENDS with the one thing they do, and the
    renderer guarantees that; what the rule is protecting against is bulletins
    that all demand work, which is why most of these say nothing right now.
    """
    if key == 'band':
        return [(
            'Project port band is now %s' % new,
            'The band this server hands out project ports from has moved.\n\n'
            '    was   %s\n'
            '    now   %s\n\n'
            'Read it as floor-ceiling/size: every admitted project gets one\n'
            'contiguous block of that size, and the block is unique across the\n'
            'fleet, so a project can move machines without renumbering.\n\n'
            'This is a MIGRATION, not a cutover. Ports you are already bound to\n'
            'keep working and nothing is being taken off you. What changes is\n'
            'where the next port comes from.' % (old, new),
            'nothing right now -- existing ports keep working. Take your NEXT '
            'port from %s, and if that is a problem, file a ticket.' % new,
        )]

    if key == 'lanes':
        old = old if isinstance(old, dict) else {}
        new = new if isinstance(new, dict) else {}
        items = []
        for name in sorted(set(old) | set(new)):
            was, now = old.get(name), new.get(name)
            if was == now:
                continue
            if was is None:
                title = 'New port lane: %s (%s)' % (name, now)
                body = ('The port map gained a lane.\n\n'
                        '    %s    %s\n\n'
                        'Lanes are how this server keeps unrelated things from\n'
                        'landing on each other. A port inside a lane belongs to\n'
                        'that lane whether or not anything is bound to it yet.'
                        % (name, now))
                act = ('nothing right now -- unless you are bound inside %s, in '
                       'which case file a ticket before you move anything.' % now)
            elif now is None:
                title = 'Port lane retired: %s (was %s)' % (name, was)
                body = ('The %s lane is no longer on the port map.\n\n'
                        'Those ports are not automatically free -- they are\n'
                        'unclaimed, which is a different thing. Do not take one\n'
                        'without asking.' % name)
                act = ('nothing right now -- do not claim the vacated range '
                       'without filing a ticket first.')
            else:
                title = 'Port lane moved: %s is now %s' % (name, now)
                body = ('The %s lane has been re-ranged.\n\n'
                        '    was   %s\n'
                        '    now   %s\n\n'
                        'If you are bound anywhere inside either range, you are\n'
                        'the one who knows it -- the hub can see what is bound\n'
                        'but not what you intended.' % (name, was, now))
                act = ('nothing right now -- unless you hold a port in %s or %s, '
                       'then say so in your next acknowledgement.' % (was, now))
            items.append((title, body, act))
        return items

    if key == 'data_root':
        return [(
            'Project data root is now %s' % str(new).split(' (')[0],
            'Where project data is supposed to live on this machine has\n'
            'changed.\n\n'
            '    was   %s\n'
            '    now   %s\n\n'
            'This is derived from the disks this box actually has, not from a\n'
            'convention. Nothing has been moved for you and nothing will be:\n'
            'the hub reports, a human moves data.' % (old, new),
            'nothing right now if you already write under the new root. If you '
            'write anywhere else, say where in your next acknowledgement.',
        )]

    if key == 'roster':
        old = set(old or [])
        new = set(new or [])
        items = []
        for name in sorted(new - old):
            items.append((
                '%s is now on this server' % name,
                'A project has been admitted here.\n\n'
                'You share this machine with it: the same disks, the same port\n'
                'space, the same Docker daemon. Port bands are unique fleet-\n'
                'wide, so it has not been given anything of yours.\n\n'
                'You are being told because the neighbourhood changed, not\n'
                'because anything is wrong.',
                'nothing right now.',
            ))
        for name in sorted(old - new):
            items.append((
                '%s has left this server' % name,
                'A project that was admitted here is no longer in the\n'
                'registry.\n\n'
                'Its ports and its data are not yours by default. Something\n'
                'leaving the registry says nothing about what is still bound or\n'
                'still on disk -- assume both until a human says otherwise.',
                'nothing right now -- do not claim its band or its paths.',
            ))
        return items

    if key == 'master':
        return [(
            'This server is now running %s' % new,
            'The hub code this server runs has moved.\n\n'
            '    was   %s\n'
            '    now   %s\n\n'
            'Your last acknowledgement was recorded against the old ref, so\n'
            'the registry now lists you as stale. That is a marker for the\n'
            'operator, not a gate -- nothing of yours has stopped working and\n'
            'nothing is being withheld from you.\n\n'
            'If this ref changed anything you have to act on, that arrived as\n'
            'its own bulletin. This one is the record that it moved.'
            % (old, new),
            'nothing right now -- re-acknowledge the new ref next time you talk '
            'to the server.',
        )]

    return []


# 20200601  publish — the whole point: a real change becomes a real bulletin
def publish():
    """Called once per port scan from collect._port_scan_loop.

    Named `publish` because that is what it does when, and only when, something
    moved. It is the one caller control.publish() was missing.

    THE CONTRACT, in order:

      first run   record the facts, say NOTHING. There is no previous state, so
                  there is no change, and a fresh hub announcing its own
                  existence to every project is the spam that gets the whole
                  stream muted. Seed, do not shout.

      a new key   record it, say nothing. A fact that could not be derived last
                  time and can be derived now is not a change -- we never knew
                  the old value, so we cannot honestly claim it differs.

      a change    publish, then advance the baseline for THAT fact only.

      a failure   leave that fact's baseline alone and return. The next sweep
                  retries. Nothing raises out of here; the port scan that calls
                  this has work of its own to finish.

    Idempotent across restarts because the baseline is a file, not memory. The
    fifth restart of the day publishes exactly what the first one did: nothing.
    """
    with _lock:
        try:
            facts = _facts()
        except Exception:
            return 0
        if not facts:
            return 0

        base = _load()
        if base is None:
            _save(facts)
            return 0

        published = 0
        carried = dict(base)
        for key in sorted(facts):
            new = facts[key]
            old = base.get(key, _MISSING)
            if old is _MISSING or old == new:
                carried[key] = new
                continue
            try:
                items = _wording(key, old, new)
                for title, body, action in items:
                    _ctl.publish(title, body, action=action, scope='all', rung=2)
                    published += 1
                # Only now is it safe to forget the old value: a project has
                # somewhere to read about the move.
                carried[key] = new
            except Exception:
                # Baseline for this fact stays put on purpose. An unannounced
                # change that is retried beats a silently swallowed one.
                continue

        _save(carried)
        return published
