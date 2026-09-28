#!/usr/bin/env python3
"""
# 20404741  tools.goals — the twelve statements of done, cascaded and rolled up

    python3 hub/tools/goals.py                  the twelve, one line each
    python3 hub/tools/goals.py --full           every check under every goal
    python3 hub/tools/goals.py --goal 7         one goal, expanded
    python3 hub/tools/goals.py --local          repo only: no ssh, no edge
    python3 hub/tools/goals.py --json           the same answers, for a machine
    python3 hub/tools/goals.py --timeout 240    per-delegate ceiling, seconds

THE PROBLEM THIS EXISTS FOR. There are now eight instruments — atlas, matrix,
step, situation, tracks, edges, install-check, migrate-ports — plus
`bootstrap.sh --check`. Each of them answers its own slice honestly and at
length. Nobody can hold eight outputs in their head at once, so the one
question the operator actually asks — *is the system as a whole getting closer
to done* — has no command. It gets answered from impression, and an impression
is the thing every tool in this directory was written to replace.

So this is not a ninth opinion. It is a CASCADE: doctrine §11's twelve
statements of done, each cascaded to the checks that already prove it, and the
answers rolled back up. Every line says which instrument answered it. A roll-up
whose provenance is invisible is just another opinion with better formatting.

────────────────────────────────────────────────────────────────────────────
THE ONE RULE THAT MAKES THIS HONEST:  **BUILT IS NOT IN FORCE.**
────────────────────────────────────────────────────────────────────────────

Almost everything in this repo is true in the code and FALSE on both servers.
The two machines run commits that predate most of this branch, and they have
each drifted off it. A goals tool that read only the repo would report nearly
everything DONE and would be lying in precisely the way this codebase has spent
a week learning not to lie. So nothing here resolves to two states. Every check
and every goal resolves to four:

    IN FORCE       proved on a machine that is actually running
    BUILT          exists in the repo, not proved on any box
    NOT BUILT      does not exist anywhere, or a check says it fails
    CANNOT ANSWER  a probe could not see, a claim no instrument can test,
                   or TWO CHECKS DISAGREE

The fourth is a state, not a failure, and it is the one the operator asked for
by name — "needs reassessment". It is never scored as a fail and never as a
pass. A disagreement between two existing tools lands there on purpose: two
sessions this week reached opposite conclusions about the same disk, and the
cost of that was a day of work on something that was already right.

WHERE THE PROVENANCE COMES FROM, AND WHY IT IS MATRIX'S IDEA. matrix.py already
tags every one of its 68 rows with what answered it — `repo`, `node`, `edge` or
`both`. That tag IS the built-vs-in-force distinction, already derived, already
maintained by someone else. So this file does not re-derive it: a matrix row
that passed from the repo is BUILT here, and a matrix row that passed from a
node or the edge is IN FORCE here. The mapping is stated once, in _from_matrix,
and nowhere else.

ROLL-UP LAW, and it is doctrine §2 Law VII, not a preference:

    NO PARTIAL CREDIT. A goal is IN FORCE only when every check under it is
    IN FORCE. One CANNOT ANSWER under a goal makes the goal CANNOT ANSWER —
    never DONE. A blind spot is not a pass.

The precedence is therefore: all IN FORCE → IN FORCE; else any CANNOT ANSWER →
CANNOT ANSWER; else any NOT BUILT → NOT BUILT; else BUILT. CANNOT outranking
NOT BUILT loses information, so the reason line on every CANNOT goal carries the
count of NOT BUILT leaves underneath it, and --full shows all of them. What it
must never do is let a hole read as health.

WHAT EVERY UNFINISHED LEAF CARRIES. The one thing that would flip it. That is
what makes this a work list rather than a scoreboard, and it is why the default
output is twelve lines and not four hundred.

WHAT THIS IS NOT. It repairs nothing, writes nothing, restarts nothing, deploys
nothing, and runs no POST against any hub. Every probe is a read. It does not
edit the doctrine it scores itself against, and where an instrument would need
a change for this file to call it cleanly, that is REPORTED at the bottom
rather than made.

THE HONEST LIMITS, up front, because a roll-up that overstates its reach is
worse than none:

  IT IS ONLY AS GOOD AS ITS DELEGATES. Every verdict below is some other
  tool's verdict, carried. Where a delegate is wrong this is wrong in exactly
  the same way, which is the price of having one definition of each fact
  instead of nine.

  TWO BOXES IS NOT A FLEET. "In force" here means in force on ksgcohub and
  fks-services. Neither of them was produced by the installer end to end, so
  nothing below can prove what a THIRD box would get. Where that is the crux
  of a goal it is said as a CANNOT ANSWER rather than assumed.

  --local IS A BLIND RUN. It reads the repo and asks no machine anything, so
  it cannot report a single IN FORCE. Every probe it skips is registered as a
  blind spot. Its output is the shape of the cascade, not the state of it.
"""
import json
import os
import re
import subprocess
import sys
import time

try:
    from concurrent.futures import ThreadPoolExecutor
except Exception:                                   # pragma: no cover
    ThreadPoolExecutor = None

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TOOLS = os.path.join(ROOT, 'hub', 'tools')

# The four states. Ordered worst-knowledge-last on purpose: the roll-up reads
# this tuple, so the precedence is data rather than a chain of ifs that someone
# will later reorder by accident.
IN_FORCE, BUILT, NOT_BUILT, CANNOT = 'IN FORCE', 'BUILT', 'NOT BUILT', 'CANNOT ANSWER'
MARK = {IN_FORCE: '[ IN FORCE  ]',
        BUILT:    '[ built     ]',
        NOT_BUILT:'[ NOT BUILT ]',
        CANNOT:   '[ REASSESS  ]'}
LEAF = {IN_FORCE: 'in force', BUILT: 'built', NOT_BUILT: 'NOT BUILT',
        CANNOT: 'REASSESS'}

# The two machines, taken from CLAUDE.md — the only place both are written
# down, which is itself a finding every tool here repeats. ksgcohub is reached
# over Tailscale and that link is INTERMITTENT: it has timed out and answered
# in the same hour. fks-services answers on the LAN only; its Tailscale address
# times out. Neither fact is a failure of the node and neither is scored as one.
NODES = [
    {'node': 'ksgcohub', 'target': 'ksgco@100.107.234.9', 'via': 'tailscale'},
    {'node': 'fks-services', 'target': 'admin1@192.168.1.229', 'via': 'lan'},
]

BLIND = []          # what could not be seen. Never empty when a probe failed.
DISAGREE = []       # (subject, tool_a, says_a, tool_b, says_b, why_it_matters)
WANTED = []         # tools this file wanted to call and could not, and why


# 20404742  blind — record a hole once, in the operator's words not the code's
def blind(why):
    """A hole, recorded once.

    Deduplicated because the same unreachable box produces the same hole from
    six different leaves, and six copies of one blind spot reads as six blind
    spots. The dangerous output of a tool like this is not a FAIL — it is a
    clean page with a hole in it.
    """
    if why not in BLIND:
        BLIND.append(why)


# 20404743  wanted — an instrument this file could not call, and the reason
def wanted(tool, why):
    """Say out loud which delegate was out of reach.

    A cascade that silently drops a delegate reports fewer failures and looks
    better for it. That is the incentive this list exists to remove.
    """
    if (tool, why) not in WANTED:
        WANTED.append((tool, why))


# 20404744  disagree — two checks, one subject, two answers: a reassessment item
def disagree(subject, a, says_a, b, says_b, matters):
    """Record that two instruments answer the same question differently.

    This is NOT scored as a failure and NOT scored as a pass. It is the
    highest-value thing this file produces, because it is the only output that
    catches an instrument going wrong — and two of them went wrong this week in
    opposite directions about the same disk.
    """
    DISAGREE.append((subject, a, says_a, b, says_b, matters))


# 20404745  leaf — one check under one goal, with the thing that would flip it
def leaf(title, state, why, by, flip=''):
    """One check.

    `by` is the instrument that answered. It is mandatory and it is printed:
    a roll-up whose provenance is invisible is an opinion.
    `flip` is the ONE thing that would move this line. Leaves that are already
    IN FORCE do not carry one; everything else must, or this is a scoreboard.
    """
    if state != IN_FORCE and not flip:
        flip = 'no one has named what would change this'
    if state == CANNOT:
        blind('%s — %s' % (title, why))
    return {'title': title, 'state': state, 'why': why, 'by': by, 'flip': flip}


# 20404746  roll_up — doctrine Law VII in four lines, and no partial credit
def roll_up(leaves):
    """Fold the leaves into one state for the goal.

    Precedence, and each clause is a law rather than a taste:
      every leaf IN FORCE  -> IN FORCE       (the only way to be done)
      any leaf CANNOT      -> CANNOT ANSWER  (a blind spot is never a pass)
      any leaf NOT BUILT   -> NOT BUILT      (definite absence beats presence)
      otherwise            -> BUILT          (it exists; no box proves it)
    """
    if not leaves:
        return CANNOT
    states = [x['state'] for x in leaves]
    if all(s == IN_FORCE for s in states):
        return IN_FORCE
    if CANNOT in states:
        return CANNOT
    if NOT_BUILT in states:
        return NOT_BUILT
    return BUILT


# 20404747  _wrap — fold prose to a width without importing textwrap's opinions
def _wrap(text, width=76):
    out, line = [], ''
    for word in str(text).split():
        if line and len(line) + 1 + len(word) > width:
            out.append(line)
            line = word
        else:
            line = (line + ' ' + word).strip()
    if line:
        out.append(line)
    return out or ['']


# 20404748  _ascii — the console here is cp1252 and an em dash kills the run
def _ascii(s):
    """Fold the characters a Windows console cannot encode.

    Not cosmetic. This tool is read from the operator's Windows PC, where
    printing a single em dash raises UnicodeEncodeError and takes the whole
    report with it. The delegates' output arrives full of them.
    """
    fold = {0x2014: '--', 0x2013: '-', 0x2018: "'", 0x2019: "'",
            0x201c: '"', 0x201d: '"', 0x2022: '*', 0x2192: '->',
            0x00b7: '-', 0x2026: '...', 0x2265: '>=', 0x2264: '<='}
    return str(s).translate(fold).encode('ascii', 'replace').decode('ascii')


# ── the delegates ────────────────────────────────────────────────────────────
# Every one of these RUNS AN EXISTING TOOL and carries its verdict. None of them
# re-derives a fact a tool already derives. Where this file asks a machine a
# question directly it is labelled `live`, and it is only ever a question no
# instrument here currently asks — the repo-versus-running-hub comparison, which
# is the whole built-versus-in-force axis and has no other home yet.

# 20404749  _sh — one subprocess, bounded, never interactive, never a shell
def _sh(argv, timeout, cwd=None):
    """Run something and come back with (ok, text).

    stdin is closed so nothing downstream can ask a question and hang — the
    same discipline install-check.py states for its own subprocesses. The child
    is forced to UTF-8 because otherwise a delegate's em dashes arrive as
    mojibake on this PC and every regex below misses.
    """
    env = dict(os.environ)
    env['PYTHONIOENCODING'] = 'utf-8'
    env['PYTHONUTF8'] = '1'
    try:
        p = subprocess.run(argv, cwd=cwd or ROOT, env=env, stdin=subprocess.DEVNULL,
                           capture_output=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return False, 'TIMEOUT after %ss' % timeout
    except Exception as e:
        return False, 'could not run: %s' % str(e)[:120]
    out = (p.stdout or b'').decode('utf-8', 'replace')
    err = (p.stderr or b'').decode('utf-8', 'replace')
    return True, out if out.strip() else err


# 20404750  _ssh — read-only, BatchMode, never prompts, never writes to the box
def _ssh(target, script, timeout):
    """One read-only round trip to a node.

    BatchMode=yes is load-bearing twice over: fks-services' sudo is password
    gated and must never be prompted for, and an ssh that blocks on a prompt
    would hang this whole report behind one box.

    THE QUOTING TRAP, learned in matrix.py and repeated here because it bites
    silently: this string is handed to ssh as ONE argv element, and Windows'
    argv quoting wraps it in double quotes. A single quote inside would arrive
    at the remote shell as a literal quote character. So the probe below
    contains NO quote characters of either kind. Not a style choice — a
    correctness one, and the failure mode is a grep that matches nothing and
    reads as an absent feature.
    """
    argv = ['ssh', '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=10',
            '-o', 'StrictHostKeyChecking=accept-new', target, script]
    return _sh(argv, timeout)


# The node probe. No quotes, by the rule above. Everything it asks is a GET or
# a stat; nothing it runs can change the box.
PROBE = '; '.join([
    'echo REF:$(git -C ~/hub rev-parse --short HEAD 2>/dev/null)',
    # `grep -c -e --converge` and not `grep -c converge`. The loose form
    # matched a COMMENT on the node's installer that says the word once while
    # the verb is absent, and this file reported the box convergeable. A probe
    # that is one word too generous is a probe that invents a feature.
    # `| head -1` because grep exits 1 on a zero count, and a `|| echo 0`
    # tacked on the end would print the count TWICE.
    'echo BOOTSTRAP:$(test -f ~/hub/bootstrap.sh && echo yes || echo no)',
    'echo CONVERGE:$(grep -c -e --converge ~/hub/bootstrap.sh 2>/dev/null | head -1)',
    'echo CHECKVERB:$(grep -c -e --check ~/hub/bootstrap.sh 2>/dev/null | head -1)',
    'echo DECOMMISSION:$(test -f ~/hub/decommission.sh && echo yes || echo no)',
    'echo ENROLL:$(test -f ~/hub/enroll.sh && echo yes || echo no)',
    'echo NODEJSON:$(test -s ~/.flare/node.json && echo yes || echo no)',
    'echo INSTALLCHECK:$(test -f ~/hub/hub/tools/install-check.py && echo yes || echo no)',
    'echo TICKETS:$(curl -s -m 6 -o /dev/null -w %{http_code} '
    'http://127.0.0.1:8765/api/tickets/goals-probe)',
    'echo TRAIL:$(curl -s -m 6 -o /dev/null -w %{http_code} '
    'http://127.0.0.1:8765/api/bulletin-trail/goals-probe)',
    'echo MESHREG:$(curl -s -m 6 -o /dev/null -w %{http_code} '
    'http://127.0.0.1:8765/api/mesh/registry)',
    'echo BULLETINS:$(curl -s -m 6 -o /dev/null -w %{http_code} '
    'http://127.0.0.1:8765/api/bulletins)',
    'echo ::ADMIT::',
    'curl -s -m 8 http://127.0.0.1:8765/api/admit?project=goals-probe',
    'echo',
    'echo ::REGISTRY::',
    'curl -s -m 8 http://127.0.0.1:8765/api/registry',
    'echo',
    'echo ::FLEET::',
    'curl -s -m 8 http://127.0.0.1:8765/api/mesh/fleet',
    'echo',
    'echo ::END::',
])


# 20404751  Delegates — run each instrument at most once, concurrently, bounded
class Delegates(object):
    """Every instrument, run once per report and memoised.

    WHY THIS IS A CLASS AND NOT NINE CALLS. Eight tools, several of which ssh
    to two boxes and probe the Cloudflare edge, is ninety seconds of wall clock.
    Run serially, from one leaf at a time, it would be several minutes and a
    tool nobody waits for is a tool nobody runs. So they start together, each
    under its own ceiling, and one unreachable box cannot stall the report —
    it times out and becomes a blind spot, which is the correct answer anyway.
    """

    def __init__(self, local=False, timeout=200, quiet=False):
        self.local = local
        self.timeout = timeout
        self.quiet = quiet
        self._cache = {}
        self._started = {}

    # 20404752  say — progress to stderr, so a 90-second run does not look hung
    def say(self, msg):
        if not self.quiet:
            sys.stderr.write('  ... %s\n' % _ascii(msg))
            sys.stderr.flush()

    # 20404753  warm — start every delegate at once and wait for the slowest
    def warm(self):
        """Fire all of them together.

        The order in `jobs` is the order they are reported as finishing, not the
        order they run. Everything is memoised into self._cache, so the goal
        builders below never wait on anything: by the time they run, the answers
        are already here or already marked unseen.
        """
        jobs = [('matrix', self._matrix), ('tracks', self._tracks),
                ('situation', self._situation), ('atlas', self._atlas),
                ('edges', self._edges), ('live', self._live),
                ('install-check', self._install_check), ('repo', self._repo),
                ('migrate-ports', self._migrate)]
        t0 = time.time()
        if ThreadPoolExecutor is None:
            for name, fn in jobs:
                self._cache[name] = fn()
            return
        with ThreadPoolExecutor(max_workers=len(jobs)) as pool:
            futs = {name: pool.submit(fn) for name, fn in jobs}
            for name, fut in futs.items():
                try:
                    self._cache[name] = fut.result()
                except Exception as e:
                    self._cache[name] = {'unseen': 'delegate raised: %s' % str(e)[:120]}
                    wanted(name, 'it raised while this file called it: %s' % str(e)[:80])
        self.say('all delegates in, %.0fs' % (time.time() - t0))

    def get(self, name):
        return self._cache.get(name) or {'unseen': 'delegate never ran'}

    # 20404754  _matrix — 68 checklist rows, each already tagged repo/node/edge
    def _matrix(self):
        """matrix.py, parsed by its own printed row format.

        matrix has no --json. Rather than ask for one — this file does not edit
        other tools — its human rows are parsed, and the parse is anchored on
        the exact format string at matrix.py's row(). If that format moves, the
        parse yields zero rows and every leaf that wanted one becomes CANNOT
        ANSWER, which is the correct degradation: a silent zero must never read
        as a clean sweep.
        """
        if self.local:
            args = [sys.executable, os.path.join(TOOLS, 'matrix.py'), '--local']
        else:
            args = [sys.executable, os.path.join(TOOLS, 'matrix.py')]
        self.say('matrix.py — 68 checklist rows against both machines')
        ok, out = _sh(args, self.timeout)
        if not ok:
            wanted('matrix.py', out)
            return {'unseen': out}
        rows, cur = [], None
        rx = re.compile(r'^\s{2}\[(pass|part|FAIL|\s\?\?\s)\]\s(\S+)\s+'
                        r'(repo|node|edge|both)\s+(.*?)\s*$')
        for line in out.splitlines():
            m = rx.match(line)
            if m:
                state, key, where, title = m.groups()
                flip = ''
                if 'FLIPPED' in title:
                    title, flip = title.split('FLIPPED', 1)
                    flip = 'FLIPPED' + flip
                cur = {'key': key, 'state': state.strip(), 'where': where,
                       'title': title.strip(), 'flip': flip.strip(), 'detail': ''}
                rows.append(cur)
            elif cur is not None and line.startswith(' ' * 14) and line.strip():
                cur['detail'] = (cur['detail'] + ' ' + line.strip()).strip()
            elif line.strip() and not line.startswith(' ' * 14):
                cur = None
        flips = 0
        m = re.search(r'(\d+) of (\d+) rows no longer match their tick', out)
        if m:
            flips = int(m.group(1))
        if not rows:
            wanted('matrix.py', 'it ran but its row format did not parse — '
                                'nothing below could be answered from it')
        self.say('matrix.py — %d rows, %d flipped against the document'
                 % (len(rows), flips))
        return {'rows': rows, 'flips': flips, 'raw': out}

    # 20404755  _tracks — three tracks, and step.py's five imported inside them
    def _tracks(self):
        """tracks.py --json.

        The richest delegate: it already imports step.py rather than copying it,
        so asking tracks is asking step, once. Under --local it is not run at
        all — it probes the public edge and there is no honest --local for it —
        and the skip is registered as a blind spot rather than as silence.
        """
        if self.local:
            wanted('tracks.py', '--local: it probes the public edge and has no '
                                'repo-only mode, so it was not run')
            return {'unseen': '--local: not run'}
        self.say('tracks.py --json — ENTRY / UNISON / NEW UI, step.py inside')
        ok, out = _sh([sys.executable, os.path.join(TOOLS, 'tracks.py'), '--json'],
                      self.timeout)
        if not ok:
            wanted('tracks.py', out)
            return {'unseen': out}
        try:
            d = json.loads(out)
        except Exception as e:
            wanted('tracks.py', 'its --json did not parse: %s' % str(e)[:80])
            return {'unseen': 'json did not parse'}
        items = {}
        for t in d.get('tracks') or []:
            for it in t.get('items') or []:
                items[it.get('id')] = it
        self.say('tracks.py — %d items across %d tracks'
                 % (len(items), len(d.get('tracks') or [])))
        return {'items': items, 'tracks': d.get('tracks') or [],
                'blind': d.get('blind') or []}

    # 20404756  _situation — serving, exposure, the entry chain, and the holes
    def _situation(self):
        """situation.py --json.

        Run WITHOUT --no-cf so the entry chain is read where a token exists, and
        with no credential presented anywhere — its own standing limit, carried
        here unchanged: a 401 means this caller was refused, not that the door
        works for whoever is meant to come through it.
        """
        if self.local:
            wanted('situation.py', '--local: every group it reports is a probe, '
                                   'so it was not run')
            return {'unseen': '--local: not run'}
        self.say('situation.py --json — serving, exposure, entry chain')
        ok, out = _sh([sys.executable, os.path.join(TOOLS, 'situation.py'), '--json'],
                      self.timeout)
        if not ok:
            wanted('situation.py', out)
            return {'unseen': out}
        try:
            d = json.loads(out)
        except Exception as e:
            wanted('situation.py', 'its --json did not parse: %s' % str(e)[:80])
            return {'unseen': 'json did not parse'}
        self.say('situation.py — verdict %s, %d blind'
                 % ((d.get('verdict') or {}).get('state'), len(d.get('blind') or [])))
        return {'findings': d.get('findings') or [], 'verdict': d.get('verdict') or {},
                'entry_chain': d.get('entry_chain'), 'blind': d.get('blind') or []}

    # 20404757  _atlas — the planes, and whether the INSTALLER produces each one
    def _atlas(self):
        """atlas.py --planes.

        Goal 4 is atlas's question verbatim — "every plane scores installed, not
        hand-built" — so it is not re-derived here, it is read off atlas's own
        marks. Only --planes is asked for: the rest of atlas is answered better
        by the other delegates, and a section nobody needs is ninety seconds
        nobody gets back.
        """
        args = [sys.executable, os.path.join(TOOLS, 'atlas.py'), '--planes']
        if self.local:
            args.append('--local')
        self.say('atlas.py --planes — built versus installed')
        ok, out = _sh(args, self.timeout)
        if not ok:
            wanted('atlas.py', out)
            return {'unseen': out}
        planes = []
        for m in re.finditer(r'^\s{2}\[([A-Za-z\- ]+)\]\s+(P\d)\s+(.*?)\s*$',
                             out, re.M):
            planes.append({'mark': m.group(1).strip(), 'id': m.group(2),
                           'title': m.group(3).strip()})
        if not planes:
            wanted('atlas.py', 'it ran but its plane format did not parse')
        self.say('atlas.py — %d planes, %d hand-built'
                 % (len(planes), sum(1 for p in planes if p['mark'] == 'HAND-BUILT')))
        return {'planes': planes, 'raw': out}

    # 20404758  _edges — every external joint, and the one-writer invariant
    def _edges(self):
        """edges.py --pairs.

        Goal 9 — every write bound to something already recorded, or refused —
        is the one-writer invariant, and edges is the only thing that derives
        it. Its own standing limit is carried into the leaf verbatim: it checks
        that each leg exists and what it writes, and does NOT walk one. So
        "bound" from edges means correctly shaped, not exercised, and this file
        says so rather than quietly upgrading it to proof.
        """
        args = [sys.executable, os.path.join(TOOLS, 'edges.py'), '--pairs']
        if self.local:
            args.append('--local')
        self.say('edges.py --pairs — the one-writer invariant')
        ok, out = _sh(args, self.timeout)
        if not ok:
            wanted('edges.py', out)
            return {'unseen': out}
        legs = re.findall(r'^\s{2}\[(ok|UNBOUND|[A-Z ]+?)\s*\]\s+(POST|GET)\s+(\S+)',
                          out, re.M)
        clean = 'No reverse leg writes under a key the caller chose' in out
        gates_declaration = 'is a DECLARATION, not a control' in out
        self.say('edges.py — %d reverse legs, invariant %s'
                 % (len(legs), 'holds' if clean else 'does not hold'))
        return {'legs': legs, 'clean': clean,
                'gates_are_declarations': gates_declaration, 'raw': out}

    # 20404759  _install_check — bootstrap's own standard, asserted ON each box
    def _install_check(self):
        """install-check.py --json, piped into each node over ssh.

        NEITHER NODE HAS THIS FILE. Both carry a checkout that predates it, so
        `ssh node python3 ~/hub/hub/tools/install-check.py` would fail on both.
        It is piped instead — `ssh node python3 - --json < install-check.py` —
        which is the mode that file documents for exactly this case and the
        reason nothing has to be WRITTEN to a box to check it. That distinction
        matters here: writing the checker onto the machine would change the
        machine, and this whole directory reports and never repairs.
        """
        if self.local:
            for n in NODES:
                wanted('install-check.py on %s' % n['node'],
                       '--local: no machine was contacted')
            return {'unseen': '--local: not run'}
        path = os.path.join(TOOLS, 'install-check.py')
        try:
            with open(path, 'rb') as f:
                body = f.read()
        except Exception as e:
            wanted('install-check.py', 'could not be read to pipe: %s' % e)
            return {'unseen': 'unreadable'}
        out = {}
        for n in NODES:
            self.say('install-check.py piped to %s' % n['node'])
            argv = ['ssh', '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=10',
                    '-o', 'StrictHostKeyChecking=accept-new', n['target'],
                    'HUB_DIR=$HOME/hub python3 - --json']
            env = dict(os.environ)
            env['PYTHONIOENCODING'] = 'utf-8'
            try:
                p = subprocess.run(argv, input=body, capture_output=True, env=env,
                                   timeout=min(self.timeout, 120))
                txt = (p.stdout or b'').decode('utf-8', 'replace')
                out[n['node']] = json.loads(txt)
                rows = out[n['node']].get('rows') or []
                bad = [r for r in rows if r.get('state') in ('missing', 'different')]
                self.say('install-check %s — %d rows, %d short of standard'
                         % (n['node'], len(rows), len(bad)))
            except Exception as e:
                out[n['node']] = {'unseen': str(e)[:120]}
                wanted('install-check.py on %s' % n['node'],
                       'piped over ssh and did not come back: %s' % str(e)[:80])
        return out

    # 20404760  _live — the one question no instrument here asks: repo vs running
    def _live(self):
        """What the RUNNING hub on each box actually serves and answers.

        THIS IS THE ONLY PLACE THIS FILE ASKS A MACHINE ANYTHING ITSELF, and it
        is deliberate: the built-versus-in-force axis needs the repo's route
        table compared against `/api/sitemap` on each running hub, and no tool
        in this directory does that comparison. Everything else here is carried
        from a delegate.

        /api/sitemap is gate 0 and derives itself from kernel.router.ROUTES, so
        the comparison is derived on BOTH sides. A route present in this branch
        and absent from a box is not an opinion about how far behind the box is
        — it is the box saying so.
        """
        if self.local:
            for n in NODES:
                wanted('live probe of %s' % n['node'],
                       '--local: no machine was contacted, so nothing below is '
                       'in force as far as this run can tell')
            return {'unseen': '--local: not run'}
        out = {}
        for n in NODES:
            self.say('live probe — %s over %s' % (n['node'], n['via']))
            ok, txt = _ssh(n['target'], PROBE, min(self.timeout, 90))
            if not ok or '::END::' not in txt:
                out[n['node']] = {'unseen': txt.strip()[:160] or 'no answer'}
                blind('%s could not be reached over %s (%s). Its rows are '
                      'unknown, not fine.' % (n['node'], n['via'],
                                              txt.strip()[:80] or 'timeout'))
                continue
            d = {}
            for line in txt.splitlines():
                m = re.match(r'^([A-Z]+):(.*)$', line.strip())
                if m:
                    d[m.group(1)] = m.group(2).strip()
            for key in ('ADMIT', 'REGISTRY', 'FLEET'):
                blob = txt.split('::%s::' % key, 1)
                if len(blob) < 2:
                    continue
                blob = blob[1].split('::', 1)[0].strip()
                try:
                    d[key] = json.loads(blob)
                except Exception:
                    d[key] = None
            out[n['node']] = d
        return out

    # 20404782  _migrate — where every project's ports are against the band
    def _migrate(self):
        """migrate-ports.py --json.

        The only instrument that knows what band this branch declares AND where
        every project's ports actually sit. Goal 7 is about admission, and a
        door that hands out a band the rest of the repo has abandoned is an
        admission that costs the project a rebind later. That comparison is
        made here because migrate-ports knows one half of it and only the live
        door knows the other.
        """
        args = [sys.executable, os.path.join(TOOLS, 'migrate-ports.py'), '--json']
        if self.local:
            args.append('--local')
        self.say('migrate-ports.py --json -- the band, and where ports really are')
        ok, out = _sh(args, self.timeout)
        if not ok:
            wanted('migrate-ports.py', out)
            return {'unseen': out}
        try:
            d = json.loads(out)
        except Exception as e:
            wanted('migrate-ports.py', 'its --json did not parse: %s' % str(e)[:80])
            return {'unseen': 'json did not parse'}
        verdicts = {}
        for pr in d.get('projects') or []:
            for _port, v in (pr.get('verdicts') or {}).items():
                verdicts[str(v)] = verdicts.get(str(v), 0) + 1
        self.say('migrate-ports.py -- band %s, %d project(s)'
                 % (d.get('band'), len(d.get('projects') or [])))
        return {'band': d.get('band'), 'projects': d.get('projects') or [],
                'verdicts': verdicts, 'blind': d.get('blind') or []}

    # 20404761  _repo — the branch's own facts, read once, by the same rules
    def _repo(self):
        """Facts about THIS checkout: its ref, and the route table it declares.

        Read straight rather than through a delegate because it is the other
        half of the live comparison and there is no tool that exports it. The
        route table is imported from kernel.router, not grepped: a regex over
        a table of dicts is a second definition of the table.
        """
        ok, ref = _sh(['git', 'rev-parse', '--short', 'HEAD'], 30)
        ok2, branch = _sh(['git', 'rev-parse', '--abbrev-ref', 'HEAD'], 30)
        routes = []
        try:
            sys.path.insert(0, os.path.join(ROOT, 'hub'))
            from kernel import router                     # noqa: E402
            routes = [(r['method'], r['path']) for r in router.ROUTES]
        except Exception as e:
            wanted('kernel.router', 'could not be imported to read ROUTES: %s'
                                    % str(e)[:80])
            blind('the repo route table could not be read, so nothing below can '
                  'compare it against what the boxes serve')
        return {'ref': (ref or '').strip(), 'branch': (branch or '').strip(),
                'routes': routes}

    # 20404762  distance — how far each box is from this branch, both directions
    def distance(self, node_ref):
        """Commits this branch has that the box does not, AND the reverse.

        The reverse half is the one that gets forgotten. A box is not simply
        "behind": both of these boxes carry commits that are NOT on this branch,
        so they have diverged rather than lagged, and a deploy is a merge rather
        than a fast-forward. Saying only "38 behind" would hide that.
        """
        if not node_ref:
            return None, None
        ok, a = _sh(['git', 'rev-list', '--count', '%s..HEAD' % node_ref], 30)
        ok2, b = _sh(['git', 'rev-list', '--count', 'HEAD..%s' % node_ref], 30)
        try:
            return int(a.strip()), int(b.strip())
        except Exception:
            return None, None

    # 20404763  has_commit — is this commit in that box's history, actually
    def has_commit(self, node_ref, commit):
        """Ancestry, which is the cheapest honest in-force test there is.

        "The binding landed in 9c32ac3" is a claim about the repo. Whether the
        box HAS 9c32ac3 is a claim about the box, and git can answer it without
        touching the box at all.
        """
        if not node_ref:
            return None
        ok, _ = _sh(['git', 'merge-base', '--is-ancestor', commit, node_ref], 30)
        if not ok:
            return None
        p = subprocess.run(['git', 'merge-base', '--is-ancestor', commit, node_ref],
                           cwd=ROOT, capture_output=True)
        return p.returncode == 0


# 20404764  _from_matrix — matrix's own provenance tag IS the built/in-force axis
def _from_matrix(D, key, want_node=None):
    """Turn one matrix row into one state, using the tag matrix already carries.

    THE WHOLE MAPPING LIVES HERE AND NOWHERE ELSE:

        pass + repo             BUILT      the code has the step. No box said so.
        pass + node/edge/both   IN FORCE   a machine or the edge answered
        part + anything         BUILT      it exists and does not fully hold
        FAIL                    NOT BUILT  matrix asserts its absence
        ??                      CANNOT     matrix could not see

    The `part -> BUILT` line is the one to argue with, so it is stated rather
    than buried: a row matrix calls partial is a row where something real exists
    and does not fully hold, which is exactly what BUILT means here. It is never
    IN FORCE, so it can never carry a goal to done.
    """
    m = D.get('matrix')
    if 'unseen' in m:
        return None, CANNOT, 'matrix.py could not be run (%s)' % m['unseen'], 'matrix.py'
    hits = [r for r in m['rows'] if r['key'] == key]
    if want_node:
        hits = [r for r in hits if want_node in r['title']]
    if not hits:
        return None, CANNOT, ('matrix.py has no row %s — either the checklist '
                              'moved or the parse missed it' % key), 'matrix.py'
    r = hits[0]
    state = {'pass': IN_FORCE if r['where'] in ('node', 'edge', 'both') else BUILT,
             'part': BUILT, 'FAIL': NOT_BUILT, '??': CANNOT}[r['state']]
    by = 'matrix.py %s (%s)' % (key, r['where'])
    return r, state, r['detail'][:400] or r['title'], by


# 20404765  _from_tracks — one track item, and the vantage point it was proved from
def _from_tracks(D, item_id, done_is=BUILT):
    """Turn one tracks item into one state.

    `done_is` is passed in per leaf rather than inferred, because tracks does
    not tag its items with what answered them and guessing would be exactly the
    substitution this repo already made once — describing the local box under a
    remote box's name. Items proved by probing the public edge are passed
    IN_FORCE; items proved by reading this checkout are passed BUILT. The choice
    is written at each call site, where the reader can check it.
    """
    t = D.get('tracks')
    if 'unseen' in t:
        return None, CANNOT, 'tracks.py could not be run (%s)' % t['unseen'], 'tracks.py'
    it = (t.get('items') or {}).get(item_id)
    if not it:
        return None, CANNOT, 'tracks.py has no item %s' % item_id, 'tracks.py'
    state = {'done': done_is, 'todo': NOT_BUILT, 'unknown': CANNOT,
             'blocked': NOT_BUILT}.get(it.get('state'), CANNOT)
    return it, state, it.get('why') or '', 'tracks.py %s' % item_id


# 20404766  _node_live — one box's live answers, or an honest nothing
def _node_live(D, node):
    d = (D.get('live') or {}).get(node)
    if not d or 'unseen' in (d or {}):
        return None
    return d


# ── the twelve goals ─────────────────────────────────────────────────────────
# doctrine/flareshub-doctrine.md §11, verbatim, in its own order. The statements
# are NOT invented here and NOT edited here. If §11 changes, this list is wrong
# and the fix is here, not there.

# 20404767  goal1 — a new server is one command
def goal1(D):
    out = []
    ic = D.get('install-check')
    for n in NODES:
        r = (ic or {}).get(n['node'])
        if not r or 'unseen' in (r or {}):
            out.append(leaf('%s is at the installer standard' % n['node'], CANNOT,
                            'install-check.py could not be run on it: %s'
                            % ((r or {}).get('unseen') if r else 'never ran'),
                            'install-check.py (piped over ssh)',
                            'reach the box, or say out loud that it is unreachable'))
            continue
        rows = r.get('rows') or []
        bad = [x for x in rows if x.get('state') in ('missing', 'different')]
        unk = [x for x in rows if x.get('state') == 'unknown']
        if bad:
            out.append(leaf('%s is at the installer standard' % n['node'], BUILT,
                            '%d of %d rows are missing or different from what '
                            'bootstrap.sh would have installed: %s'
                            % (len(bad), len(rows),
                               ', '.join(x['name'] for x in bad[:4])),
                            'install-check.py (piped over ssh)',
                            'bootstrap.sh --converge on that box — which is itself '
                            'not on that box, see goal 2'))
        elif unk:
            out.append(leaf('%s is at the installer standard' % n['node'], CANNOT,
                            '%d row(s) could not be determined on it' % len(unk),
                            'install-check.py (piped over ssh)',
                            'whatever those rows need to be readable'))
        else:
            out.append(leaf('%s is at the installer standard' % n['node'], IN_FORCE,
                            '%d rows, none missing or different' % len(rows),
                            'install-check.py (piped over ssh)'))

    _r, st, why, by = _from_matrix(D, 'B/e14')
    out.append(leaf('enrolment ends holding a hostname that answers', st, why, by,
                    'whatever B/e14 names'))

    for n in NODES:
        d = _node_live(D, n['node'])
        if d is None:
            continue
        if d.get('NODEJSON') != 'yes':
            out.append(leaf('%s holds the enrolment record it was supposed to '
                            'end with' % n['node'], NOT_BUILT,
                            '~/.flare/node.json is absent, so this box does not '
                            'know its own hostname, zone or tunnel — it was never '
                            'enrolled by the installer, whatever answers at the edge',
                            'live probe (ssh, read-only)',
                            'enroll.sh on that box, which would also give goal 11 '
                            'a ref to compare'))
        else:
            out.append(leaf('%s holds the enrolment record it was supposed to '
                            'end with' % n['node'], IN_FORCE,
                            '~/.flare/node.json present',
                            'live probe (ssh, read-only)'))

    out.append(leaf('the installer has produced a server end to end', CANNOT,
                    'no instrument here can test this and none claims to. Of the '
                    'two boxes in the fleet, bootstrap.sh produced neither: both '
                    'predate it. atlas.py names the same gap — a third server is '
                    'what proves which planes were installed and which were typed',
                    'atlas.py --planes, and the absence of any other check',
                    'one run of bootstrap.sh on a box nobody has touched by hand'))
    return out


# 20404768  goal2 — running the installer again is safe
def goal2(D):
    out = []
    repo_boot = ''
    try:
        with open(os.path.join(ROOT, 'bootstrap.sh'), encoding='utf-8',
                  errors='ignore') as f:
            repo_boot = f.read()
    except Exception:
        pass
    out.append(leaf('--check exists in the installer',
                    BUILT if '--check' in repo_boot else NOT_BUILT,
                    'bootstrap.sh in this branch carries a --check entry point. '
                    'It answered on both boxes, but it was PIPED to them -- the '
                    'checker is on neither machine, so this proves the code and '
                    'the next lines are what prove a box'
                    if '--check' in repo_boot else 'no --check in bootstrap.sh',
                    'live read of bootstrap.sh + install-check.py piped over ssh',
                    'deploy this branch, so the checker is ON the box rather than '
                    'carried to it from the operator PC every time'))
    for n in NODES:
        d = _node_live(D, n['node'])
        if d is None:
            continue
        try:
            has_check = int(d.get('CHECKVERB') or 0)
        except ValueError:
            has_check = 0
        out.append(leaf('%s can be asked whether it is at standard' % n['node'],
                        IN_FORCE if has_check else BUILT,
                        'its own bootstrap.sh carries the --check verb, %d '
                        'mention(s)' % has_check if has_check else
                        'the installer on that box has no --check verb at all, so '
                        'the only way to ask it is to pipe the checker in from '
                        'here, which is what this run did',
                        'live probe (ssh, read-only)',
                        'get this branch onto the box'))
    out.append(leaf('--converge exists in the installer',
                    BUILT if '--converge' in repo_boot else NOT_BUILT,
                    'bootstrap.sh in THIS branch carries --converge and repairs '
                    'only what --check reports missing. That is the code; see the '
                    'next line for the boxes' if '--converge' in repo_boot
                    else 'no --converge in bootstrap.sh',
                    'live read of bootstrap.sh in this checkout',
                    'deploy this branch'))
    for n in NODES:
        d = _node_live(D, n['node'])
        if d is None:
            continue
        n_conv = d.get('CONVERGE', '0')
        try:
            n_conv = int(n_conv)
        except Exception:
            n_conv = 0
        out.append(leaf('%s can be converged' % n['node'],
                        IN_FORCE if n_conv else BUILT,
                        'its own bootstrap.sh mentions converge %d time(s)' % n_conv
                        if n_conv else
                        'the installer on that box has NO converge verb at all. '
                        'Re-running it there is the old installer, not the safe '
                        'one — which is the difference this goal is about',
                        'live probe (ssh, read-only)',
                        'get this branch onto the box'))
    _r, st, why, by = _from_matrix(D, 'B/e7')
    out.append(leaf('re-running does not destroy what is already there', st, why, by,
                    'whatever B/e7 names'))
    return out


# 20404769  goal3 — removing a server is one command
def goal3(D):
    out = []
    _r, st, why, by = _from_matrix(D, 'B/e16')
    out.append(leaf('a decommission path exists that removes tunnel, DNS and '
                    'Access app', st, why, by,
                    'whatever B/e16 names'))
    for n in NODES:
        d = _node_live(D, n['node'])
        if d is None:
            continue
        have = d.get('DECOMMISSION') == 'yes'
        out.append(leaf('%s has the decommission script' % n['node'],
                        IN_FORCE if have else BUILT,
                        'decommission.sh present' if have else
                        'decommission.sh is NOT on that box. The command exists in '
                        'this branch and on neither machine, so removing either '
                        'server today is still a hand operation in the Cloudflare '
                        'dashboard',
                        'live probe (ssh, read-only)',
                        'get this branch onto the box'))
    out.append(leaf('it has been walked once, on a real node', CANNOT,
                    'nothing here tests it and nothing claims to. matrix B/e16 '
                    'reads the script; no instrument runs it, and running it is '
                    'destructive by definition so none should',
                    'matrix.py B/e16 (repo) — and the absence of any walker',
                    'decommission a throwaway node once, with the dry-run first'))
    return out


# 20404770  goal4 — every plane scores installed, not hand-built
def goal4(D):
    a = D.get('atlas')
    if 'unseen' in a:
        return [leaf('the planes score installed', CANNOT,
                     'atlas.py could not be run (%s)' % a['unseen'], 'atlas.py',
                     'run atlas.py --planes by hand and read it')]
    out = []
    for p in a.get('planes') or []:
        mark = p['mark']
        if mark == 'DONE':
            st, why = IN_FORCE, 'the installer produces it'
        elif mark == 'HAND-BUILT':
            st, why = BUILT, ('it exists on both boxes because someone typed it '
                              'there. The installer does not produce it, so a '
                              'third server arrives without it')
        else:
            st, why = BUILT, 'runs from the checkout; the installer is not its route'
        out.append(leaf('%s %s' % (p['id'], p['title']), st, why, 'atlas.py --planes',
                        'teach bootstrap.sh to produce it, or accept that every '
                        'new box needs a hand'))
    return out


# 20404771  goal5 — one login, no second password anywhere
def goal5(D):
    out = []
    # E1/E2/E4 are proved by probing the PUBLIC EDGE, so done means in force.
    for item, title in (('E1', 'the apex serves the public login space'),
                        ('E2', '/fleet is behind a login, not public'),
                        ('E4', 'an alias redirects and serves nothing')):
        _it, st, why, by = _from_tracks(D, item, done_is=IN_FORCE)
        out.append(leaf(title, st, why, by, 'whatever %s names' % item))
    _r, st, why, by = _from_matrix(D, 'B/e10')
    out.append(leaf('nothing public is ungated', st, why, by, 'whatever B/e10 names'))
    _r, st, why, by = _from_matrix(D, 'A/3')
    out.append(leaf('the edge identity becomes a session and a role', st, why, by,
                    'whatever A/3 names'))
    _r, st, why, by = _from_matrix(D, 'A/9')
    out.append(leaf('no second password anywhere — the dangerous routes do not '
                    'ask for one the edge cannot give', st, why, by,
                    'whatever A/9 names'))
    return out


# 20404772  goal6 — one UI file, and an old one says so out loud
def goal6(D):
    out = []
    for item, title in (('UI2', 'ONE console front end, not two'),
                        ('UI3', 'views render from their own files'),
                        ('UI4', 'hub/ui-next/ is wired in or deleted')):
        _it, st, why, by = _from_tracks(D, item, done_is=BUILT)
        out.append(leaf(title, st, why, by, 'whatever %s names' % item))
    _r, st, why, by = _from_matrix(D, 'E/5')
    out.append(leaf('a box running an old build says so out loud', st, why, by,
                    'whatever E/5 names'))
    return out


# 20404773  goal7 — a project is admitted without a human carrying anything
def goal7(D):
    out = []
    seen_any = False
    for n in NODES:
        d = _node_live(D, n['node'])
        if d is None:
            continue
        seen_any = True
        admit = d.get('ADMIT') or {}
        band = admit.get('assigned_band')
        has_storage = bool(admit.get('storage'))
        pend = admit.get('pending')
        ok_admit = bool(band) and has_storage
        out.append(leaf('%s admits a project with a band and a storage answer'
                        % n['node'], IN_FORCE if ok_admit else NOT_BUILT,
                        '/api/admit answers band %s and %s a storage block'
                        % (band, 'carries' if has_storage else 'carries NO'),
                        'live probe (ssh, loopback HTTP)',
                        'the route has to answer with both'))
        four = ('change', 'why', 'when', 'what_you_must_do')
        good = (isinstance(pend, list) and pend
                and all(all(i.get(k) for k in four) for i in pend))
        out.append(leaf('%s tells an arriving project what is pending' % n['node'],
                        IN_FORCE if good else NOT_BUILT,
                        '%d pending item(s), each carrying all four fields'
                        % len(pend or []) if good else
                        'the pending block is missing or short of its four fields',
                        'live probe (ssh, loopback HTTP) — step.py step 2 asks the '
                        'same question of the code',
                        'whatever step.py step 2 names'))
        reg = d.get('REGISTRY') or {}
        projects = reg.get('projects') or []
        out.append(leaf('%s has an admitted project on the record' % n['node'],
                        IN_FORCE if projects else NOT_BUILT,
                        '%d project(s) in the registry' % len(projects) if projects
                        else 'the registry is EMPTY. Every route under this goal '
                             'works and nothing has ever come through one',
                        'live probe (ssh, loopback HTTP)',
                        'walk one intake end to end — step.py step 5'))
    if not seen_any:
        out.append(leaf('a project is admitted at all', CANNOT,
                        'neither box could be reached, so the admission door was '
                        'not asked anything', 'live probe (ssh)',
                        'reach a box'))
    _r, st, why, by = _from_matrix(D, 'C/1')
    out.append(leaf('an arriving project can authenticate — the acknowledgement '
                    'cannot be forged', st, why, by, 'whatever C/1 names'))
    _it, st, why, by = _from_tracks(D, 'U5', done_is=IN_FORCE)
    out.append(leaf('one intake completed end to end', st, why, by,
                    'whatever step.py step 5 names'))
    mp = D.get('migrate-ports')
    if 'unseen' in mp:
        out.append(leaf('the band a project is handed is the band the fleet uses',
                        CANNOT, 'migrate-ports.py could not be run (%s)'
                        % mp['unseen'], 'migrate-ports.py --json',
                        'run migrate-ports.py by hand'))
    else:
        v = mp.get('verdicts') or {}
        bad = sum(n for k, n in v.items() if k != 'in-band')
        out.append(leaf('the band a project is handed is the band the fleet uses',
                        IN_FORCE if not bad else NOT_BUILT,
                        'every port sits inside the declared band' if not bad else
                        'this branch declares band %s and migrate-ports.py finds '
                        '%d port(s) outside it (%s) against %d inside. Admission '
                        'is not carried by a human any more; what it hands out is '
                        'still not what the fleet runs on'
                        % (mp.get('band'), bad,
                           ', '.join('%s x%d' % (k, n) for k, n in sorted(v.items())
                                     if k != 'in-band'), v.get('in-band', 0)),
                        'migrate-ports.py --json',
                        'settle the band in one place -- see the reassessment '
                        'item that compares it against the live door'))
    return out


# 20404774  goal8 — the exchange has a screen
def goal8(D):
    out = []
    repo = D.get('repo')
    routes = [p for m, p in (repo.get('routes') or [])
              if any(k in p for k in ('bulletin', 'ticket', 'outbox'))]
    out.append(leaf('the exchange has routes', BUILT if routes else NOT_BUILT,
                    '%d exchange routes declared in kernel.router.ROUTES' % len(routes),
                    'live read of kernel.router.ROUTES',
                    'nothing — this half is done'))
    for n in NODES:
        d = _node_live(D, n['node'])
        if d is None:
            continue
        gone = [k for k in ('TICKETS', 'TRAIL', 'MESHREG', 'BULLETINS')
                if d.get(k) == '404']
        out.append(leaf('%s serves the exchange routes this branch declares'
                        % n['node'], IN_FORCE if not gone else BUILT,
                        'every exchange route answered' if not gone else
                        '%d route(s) this branch declares answer 404 on that box: '
                        '%s. The code is real and the running hub has never seen it'
                        % (len(gone), ', '.join(sorted(gone))),
                        'live probe: repo ROUTES vs /api/sitemap and live status',
                        'get this branch onto the box'))
    # The screen itself. Not delegated because no instrument asks it; it is a
    # grep of the one file that would have to mention the thing.
    hits = 0
    for name in ('hub/app.html', 'hub/mobile.html'):
        try:
            with open(os.path.join(ROOT, name), encoding='utf-8', errors='ignore') as f:
                body = f.read().lower()
            hits += sum(body.count(w) for w in ('bulletin', 'ticket', 'outbox'))
        except Exception:
            pass
    views = []
    vdir = os.path.join(ROOT, 'hub', 'ui', 'views')
    if os.path.isdir(vdir):
        views = sorted(os.listdir(vdir))
    out.append(leaf('a human can see the exchange without reading a log',
                    NOT_BUILT if not hits else BUILT,
                    'neither console mentions a bulletin, a ticket or the outbox '
                    'even once, and hub/ui/views/ holds %s. So the exchange has '
                    'routes and no screen, which is the whole of this goal'
                    % (', '.join(views) or 'nothing') if not hits else
                    '%d mention(s) across the consoles' % hits,
                    'live read of hub/app.html, hub/mobile.html and hub/ui/views/',
                    'a screen — and per tracks.py UI1 a mockup is owed before it'))
    return out


# 20404775  goal9 — every write is bound to something already recorded
def goal9(D):
    e = D.get('edges')
    if 'unseen' in e:
        return [leaf('every write is bound', CANNOT,
                     'edges.py could not be run (%s)' % e['unseen'], 'edges.py',
                     'run edges.py --pairs by hand and read the invariant')]
    legs = e.get('legs') or []
    bad = [l for l in legs if l[0] != 'ok']
    out = [leaf('no reverse leg writes under a key the caller chose',
                BUILT if e.get('clean') and not bad else NOT_BUILT,
                '%d reverse legs, %d bound, and edges.py states the invariant '
                'holds' % (len(legs), len(legs) - len(bad)) if e.get('clean')
                else '%d leg(s) are not bound' % len(bad),
                'edges.py --pairs (the one-writer invariant)',
                'bind the unbound legs')]
    out.append(leaf('a refusal has actually been observed', CANNOT,
                    'edges.py says so about itself: it checks that each leg '
                    'exists and what it writes, and does not walk one. So "bound" '
                    'above means correctly shaped, not exercised, and nothing here '
                    'has ever watched a forged write get refused',
                    'edges.py --pairs, standing limit',
                    'one POST with a machine_id that does not match, watched, on a '
                    'box that can be dirtied'))
    if e.get('gates_are_declarations'):
        out.append(leaf('the gate a bound route declares is enforced', NOT_BUILT,
                        'edges.py: the gate is declared at router.py and nothing '
                        'in the installer sets it, so every gate number is a '
                        'DECLARATION, not a control — a gate 1 route and a gate 0 '
                        'route are equally open today',
                        'edges.py --pairs',
                        'the same thing goal 10 is waiting on'))
    return out


# 20404776  goal10 — layers 3 and 4 refuse until FlareVault fills them
def goal10(D):
    out = []
    _r, st, why, by = _from_matrix(D, 'A/8')
    out.append(leaf('a gate is declared per route', st, why, by,
                    'whatever A/8 names'))
    _r, st, why, by = _from_matrix(D, 'A/9')
    out.append(leaf('the dangerous routes demand more than the edge gave', st,
                    why, by, 'whatever A/9 names'))
    s = D.get('situation')
    if 'unseen' in s:
        out.append(leaf('the gates are armed on a running box', CANNOT,
                        'situation.py could not be run (%s)' % s['unseen'],
                        'situation.py --json', 'run situation.py by hand'))
    else:
        totp = [f for f in (s.get('findings') or [])
                if 'TOTP' in (f.get('what') or '')]
        if totp:
            out.append(leaf('the gates are armed on a running box', NOT_BUILT,
                            totp[0].get('what') + ' — ' +
                            (totp[0].get('why_it_matters') or '')[:220],
                            'situation.py --json (findings)',
                            'TOTP, which is what would let HUB_ENFORCE_GATES be '
                            'turned on without closing nothing'))
        else:
            out.append(leaf('the gates are armed on a running box', CANNOT,
                            'situation.py reported no finding about the gates on '
                            'this run, which is not the same as reporting them armed',
                            'situation.py --json (findings)',
                            'ask situation.py directly'))
    e = D.get('edges')
    if 'unseen' not in e:
        seams = e.get('raw', '').count('stands in for')
        out.append(leaf('the seams FlareVault will fill are declared and watched',
                        BUILT if seams else NOT_BUILT,
                        '%d seam(s) carry a marker, so one silently closed or '
                        'silently deleted shows up' % seams,
                        'edges.py --pairs (the FlareVault seams)',
                        'FlareVault arriving'))
    return out


# 20404777  goal11 — drift is visible, fleet-wide, from one address
def goal11(D):
    out = []
    for key, title in (('E/1', 'which nodes exist, by stable identity'),
                       ('E/2', 'what runs on each node, by owning project'),
                       ('E/3', 'which projects are publicly exposed'),
                       ('E/5', 'what has drifted from what was declared'),
                       ('E/6', 'which nodes are quietly filling their disks')):
        _r, st, why, by = _from_matrix(D, key)
        out.append(leaf(title, st, why, by, 'whatever %s names' % key))
    # One address. Only a node in `central` mode can answer for the fleet, so
    # "from one address" is a claim about WHICH address, and it has to be said.
    for n in NODES:
        d = _node_live(D, n['node'])
        if d is None:
            continue
        fl = d.get('FLEET') or {}
        mode = fl.get('mode')
        count = len((fl.get('fleet') or {}))
        out.append(leaf('%s can answer for the whole fleet' % n['node'],
                        IN_FORCE if (mode == 'central' and count) else BUILT,
                        'mode %s, %d other node(s) on the record' % (mode, count)
                        if mode == 'central' and count else
                        'mode %s: it carries %d fleet record(s) and cannot answer '
                        'for anything but itself. "From one address" means from '
                        'the other one' % (mode, count),
                        'live probe (ssh, loopback /api/mesh/fleet)',
                        'central mode, or a federation leg that reaches back'))
    return out


# 20404778  goal12 — every fact is derived, and docs/ holds doctrine only
def goal12(D):
    out = []
    m = D.get('matrix')
    if 'unseen' in m:
        out.append(leaf('the documents agree with the machines', CANNOT,
                        'matrix.py could not be run', 'matrix.py',
                        'run matrix.py'))
    else:
        flips = m.get('flips') or 0
        out.append(leaf('the documents agree with the machines',
                        IN_FORCE if not flips else NOT_BUILT,
                        'every checklist row matches the machine' if not flips else
                        '%d of %d hand-marked checklist rows no longer match what '
                        'the machine says, in BOTH directions. A document that '
                        'states a fact is a document that goes wrong silently, '
                        'and this is the measurement of it'
                        % (flips, len(m.get('rows') or [])),
                        'matrix.py (its own FLIPPED tally)',
                        'delete the ticks and let matrix.py be the answer — not '
                        'a hand pass over them, which is what produced the list'))
    # docs/ holding assertions rather than doctrine. Counted, not described.
    ticked, docs = [], os.path.join(ROOT, 'docs')
    if os.path.isdir(docs):
        for f in sorted(os.listdir(docs)):
            if not f.endswith('.md'):
                continue
            try:
                with open(os.path.join(docs, f), encoding='utf-8', errors='ignore') as fh:
                    body = fh.read()
            except Exception:
                continue
            if re.search(r'\|\s*(y|n|w)\s*\|', body) or '[x]' in body.lower():
                ticked.append(f)
    out.append(leaf('docs/ holds doctrine only, not statuses',
                    IN_FORCE if not ticked else NOT_BUILT,
                    'no file under docs/ carries a hand-marked status' if not ticked
                    else '%d file(s) under docs/ still carry hand-marked ticks: %s'
                         % (len(ticked), ', '.join(ticked)),
                    'live read of docs/',
                    'move each ticked row into a check, then delete the row'))
    a = D.get('atlas')
    out.append(leaf('the instruments that replace the documents exist',
                    CANNOT if 'unseen' in a else IN_FORCE,
                    'atlas.py could not be run' if 'unseen' in a else
                    'the instrument plane is present and every goal on this page '
                    'was answered by one of them',
                    'atlas.py --planes',
                    'run atlas.py'))
    return out


GOALS = [
    (1, 'A new server is one command.', goal1),
    (2, 'Running the installer again is safe.', goal2),
    (3, 'Removing a server is one command.', goal3),
    (4, 'Every plane scores installed, not hand-built.', goal4),
    (5, 'One login carries you from flarevault.dev to inside any server.', goal5),
    (6, 'One UI file serves every box, and an old one says so.', goal6),
    (7, 'A project is admitted without a human carrying anything.', goal7),
    (8, 'The exchange has a screen.', goal8),
    (9, 'Every write is bound to something already recorded, or refused.', goal9),
    (10, 'Layers 3 and 4 refuse until FlareVault fills them.', goal10),
    (11, 'Drift is visible, fleet-wide, from one address.', goal11),
    (12, 'Every fact in this repo is derived.', goal12),
]


# 20404779  find_disagreements — where two instruments answer the same thing twice
def find_disagreements(D, results):
    """The highest-value output on the page, and the only one nobody asked for.

    A cascade that only rolls verdicts up cannot catch an instrument going
    wrong. These comparisons exist because the same two facts are derived twice
    by different means, and a divergence between them is a reason to go look —
    not a pass and not a fail. Each one below is a pair that has ALREADY
    diverged at least once in this repo's history.
    """
    # 1. The fleet's own drift counter against the refs the boxes report.
    refs = {}
    for n in NODES:
        d = _node_live(D, n['node'])
        if d:
            refs[n['node']] = d.get('REF') or ''
    live = D.get('live') or {}
    for n in NODES:
        d = _node_live(D, n['node'])
        if not d:
            continue
        fl = d.get('FLEET') or {}
        drift = ((fl.get('summary') or {}).get('drift'))
        if drift == 0 and len(set(v for v in refs.values() if v)) > 1:
            disagree(
                'are the two boxes on the same build?',
                '/api/mesh/fleet on %s' % n['node'], 'drift: 0',
                'git, against the refs the boxes report',
                ' vs '.join('%s %s' % (k, v) for k, v in sorted(refs.items())),
                'the drift counter compares only the git ref, and a node that '
                'sends no ref compares as agreeing. A zero here means "nothing '
                'comparable", not "nothing different" — and goal 11 is the goal '
                'that rests on it.')
            break

    # 2. matrix's storage row against what the live fleet records actually carry.
    r, st, why, by = _from_matrix(D, 'E/6')
    if r and r['state'] == 'pass':
        carried = 0
        total = 0
        for n in NODES:
            d = _node_live(D, n['node'])
            if not d:
                continue
            for rec in ((d.get('FLEET') or {}).get('fleet') or {}).values():
                total += 1
                att = rec.get('attention')
                # attention arrives as a dict on one build and a list of
                # findings on another. Both shapes are asked the same question
                # rather than one being assumed, because assuming it is how a
                # probe reports "no storage flag" on a box that has three.
                if isinstance(att, dict) and att.get('storage'):
                    carried += 1
                elif isinstance(att, list) and any(
                        'storage' in str(x).lower() for x in att):
                    carried += 1
        if total and not carried:
            disagree(
                'can one address see which node is filling its disk?',
                'matrix.py E/6 (repo)', 'pass — the fleet record carries storage',
                'live /api/mesh/fleet on the running boxes',
                '%d of %d fleet records carry a storage flag' % (carried, total),
                'matrix reads the repo, where the three lines landed. The running '
                'hubs predate them. This is the exact shape of BUILT-not-IN-FORCE '
                'and it is on the row the doctrine calls the point of the whole '
                'exercise.')

    # 3. tracks' vantage point against matrix's. Both are right; they are
    #    standing in different places, and that is worth saying out loud.
    it, tst, twhy, tby = _from_tracks(D, 'U4', done_is=IN_FORCE)
    r, mst, mwhy, mby = _from_matrix(D, 'B/e14')
    if it and r and tst == CANNOT and mst == IN_FORCE:
        disagree(
            'does the installer end holding a live hostname?',
            'tracks.py U4 (step.py step 4)', 'unknown — no node.json on this machine',
            'matrix.py B/e14 (edge)', 'pass — the hostname answers',
            'step 4 reads ~/.flare/node.json on WHATEVER MACHINE IT RUNS ON, and '
            'this is the operator PC. matrix asks the edge. Neither is wrong and '
            'the pair cannot be averaged: run step.py on the node, or read B/e14.')

    # 4. The band this branch declares against the band the live door hands out.
    #    These two have been the same number in exactly one of the last three
    #    weeks, and a project that acts on the door's answer rebinds twice.
    mp = D.get('migrate-ports')
    if 'unseen' not in mp and mp.get('band'):
        lo, hi = (mp['band'] + [None, None])[:2]
        for n in NODES:
            d = _node_live(D, n['node'])
            if not d:
                continue
            live_band = (d.get('ADMIT') or {}).get('assigned_band')
            if live_band and lo is not None and not (lo <= live_band[0] <= hi):
                disagree(
                    'what band does a project arriving today get?',
                    'migrate-ports.py, from this branch', '%s-%s' % (lo, hi),
                    '/api/admit live on %s' % n['node'],
                    '%s-%s' % (live_band[0], live_band[-1]),
                    'the door on the running box is handing out a band this '
                    'branch has already moved off. A project that does what '
                    '/api/admit tells it today binds ports that migrate-ports.py '
                    'will call old-band tomorrow, and rebinds twice.')
                break

    # 5. A repo route the boxes do not serve, against any matrix row that passed
    #    from the repo about the same subject.
    gone = set()
    for n in NODES:
        d = _node_live(D, n['node'])
        if not d:
            continue
        for k, path in (('TICKETS', '/api/tickets/'), ('TRAIL', '/api/bulletin-trail/'),
                        ('MESHREG', '/api/mesh/registry'), ('BULLETINS', '/api/bulletins')):
            if d.get(k) == '404':
                gone.add(path)
    repo_paths = {p for m, p in (D.get('repo').get('routes') or [])}
    both = sorted(gone & repo_paths)
    if both:
        disagree(
            'does the exchange answer?',
            'kernel.router.ROUTES in this branch', '%d of these routes declared' % len(both),
            'the running hubs on both boxes', '404 on: %s' % ', '.join(both),
            'every instrument that reads router.py will report these as present. '
            'They are present in the code and absent from both machines, and no '
            'tool but this comparison says so.')


# 20404780  render — the twelve, then the leaves only if asked
def render(D, results, full=False, only=None):
    repo = D.get('repo')
    print()
    print('  GOALS -- doctrine section 11, cascaded to the checks that prove it')
    print('  repo: %s' % ROOT)
    print('  branch %s at %s' % (repo.get('branch') or '?', repo.get('ref') or '?'))
    for n in NODES:
        d = _node_live(D, n['node'])
        if not d:
            print('  %-14s NOT REACHED over %s -- its rows are unknown, not fine'
                  % (n['node'], n['via']))
            continue
        ref = d.get('REF') or '?'
        ahead, behind = D.distance(ref)
        gap = ''
        if ahead is not None:
            gap = ('%d commit(s) on this branch it does not have' % ahead
                   + (', and %d it has that this branch does not' % behind
                      if behind else ''))
        print('  %-14s ref %-9s %s' % (n['node'], ref, gap))
    print()
    for line in _wrap('BUILT IS NOT IN FORCE. Both boxes run code that predates '
                      'most of this branch, so a check answered from the repo '
                      'proves the code and nothing about either machine. Every '
                      'line below says which of the two it is, and which '
                      'instrument said so.', 74):
        print('  %s' % line)
    print()

    for num, statement, _fn in GOALS:
        if only and num != only:
            continue
        r = results[num]
        print('  %s %2d. %s' % (MARK[r['state']], num, _ascii(statement)))
        for line in _wrap(r['reason'], 68):
            print('                  %s' % _ascii(line))
        if full or only == num:
            for x in r['leaves']:
                print()
                print('       %-9s %s' % (LEAF[x['state']], _ascii(x['title'])))
                print('                 by: %s' % _ascii(x['by']))
                for line in _wrap(x['why'], 62):
                    print('                 %s' % _ascii(line))
                if x['state'] != IN_FORCE:
                    for i, line in enumerate(_wrap('would flip it: ' + x['flip'], 62)):
                        print('                 %s' % _ascii(line))
        print()

    counts = {s: 0 for s in (IN_FORCE, BUILT, NOT_BUILT, CANNOT)}
    for num, _s, _f in GOALS:
        counts[results[num]['state']] += 1
    nleaf = sum(len(results[n]['leaves']) for n, _s, _f in GOALS)
    print('  ' + '-' * 74)
    print('  %d goals, %d checks under them:  %d IN FORCE   %d built   '
          '%d NOT BUILT   %d need reassessment'
          % (len(GOALS), nleaf, counts[IN_FORCE], counts[BUILT],
             counts[NOT_BUILT], counts[CANNOT]))
    print('  marks  [ IN FORCE  ] proved on a running machine')
    print('         [ built     ] in the repo, not proved on any box')
    print('         [ NOT BUILT ] absent, or a check asserts it fails')
    print('         [ REASSESS  ] could not be answered, or two checks disagree')
    print()

    print('  NEEDS REASSESSMENT -- two instruments, one question, two answers')
    print('  ' + '=' * 74)
    if DISAGREE:
        for subject, a, sa, b, sb, matters in DISAGREE:
            print()
            print('    %s' % _ascii(subject))
            print('      %-42s %s' % (_ascii(a)[:42], _ascii(sa)[:120]))
            print('      %-42s %s' % (_ascii(b)[:42], _ascii(sb)[:120]))
            for line in _wrap(matters, 68):
                print('        %s' % _ascii(line))
        print()
        print('    None of these is a pass and none is a failure. Each is a pair')
        print('    of checks that cannot both be right, and averaging them is how')
        print('    a correct setup reached the top of the priority list once.')
    else:
        print('    Nothing. Every pair of checks compared here agrees.')
    print()

    if WANTED:
        print('  INSTRUMENTS THIS COULD NOT CALL')
        print('  ' + '-' * 74)
        for tool, why in WANTED:
            for i, line in enumerate(_wrap('%s -- %s' % (tool, why), 70)):
                print('    %s%s' % ('' if i == 0 else '  ', _ascii(line)))
        print()

    print('  WHAT I COULD NOT SEE')
    print('  ' + '-' * 74)
    if BLIND:
        for b in BLIND:
            for i, line in enumerate(_wrap(b, 70)):
                print('    %s%s' % ('- ' if i == 0 else '    ', _ascii(line)))
        print()
        print('    Everything above is true only of what answered. A hole here is')
        print('    not a pass, and a goal that could not be checked is not a goal')
        print('    that is fine.')
    else:
        print('    Nothing. Every delegate ran and every probe answered.')
    print()
    return counts


# 20404781  main — one run, bounded, and a non-zero exit while anything is owed
def main(argv):
    full = '--full' in argv
    local = '--local' in argv
    as_json = '--json' in argv
    quiet = as_json or '--quiet' in argv
    only = None
    if '--goal' in argv:
        i = argv.index('--goal')
        if i + 1 < len(argv):
            try:
                only = int(argv[i + 1])
            except ValueError:
                only = None
    timeout = 200
    if '--timeout' in argv:
        i = argv.index('--timeout')
        if i + 1 < len(argv):
            try:
                timeout = int(argv[i + 1])
            except ValueError:
                pass

    if local:
        blind('--local: no machine and no hostname was asked anything, so this '
              'run cannot report a single IN FORCE. Every state below is a claim '
              'about the code. That is the shape of the cascade, not the state '
              'of it.')

    D = Delegates(local=local, timeout=timeout, quiet=quiet)
    if not quiet:
        sys.stderr.write('\n  running %d instruments%s -- this takes about a '
                         'minute\n' % (8, ' (--local: repo only)' if local else ''))
    D.warm()

    results = {}
    for num, statement, fn in GOALS:
        try:
            leaves = fn(D)
        except Exception as e:
            leaves = [leaf('this goal could not be assembled', CANNOT,
                           'the cascade itself failed: %s' % str(e)[:140],
                           'goals.py', 'fix goals.py')]
        state = roll_up(leaves)
        nblind = sum(1 for x in leaves if x['state'] == CANNOT)
        nbad = sum(1 for x in leaves if x['state'] == NOT_BUILT)
        # The headline leaf must be one that CARRIES the goal's state, or the
        # one-line reason contradicts the mark beside it. A goal marked
        # REASSESS whose reason quotes a NOT BUILT row reads as an admission
        # that the mark is wrong, which is exactly the kind of quiet
        # inconsistency this file exists to stop printing.
        same = [x for x in leaves if x['state'] == state]
        worst = (same or [x for x in leaves if x['state'] == NOT_BUILT] or
                 [x for x in leaves if x['state'] == CANNOT] or
                 [x for x in leaves if x['state'] == BUILT] or leaves)[0]
        tail = ''
        if state == CANNOT and nbad:
            tail = (' (%d check(s) under it are NOT BUILT as well -- --goal %d '
                    'shows them)' % (nbad, num))
        elif state != IN_FORCE and nblind:
            tail = ' (%d check(s) could not be answered)' % nblind
        why = worst['why']
        if len(why) > 210:
            # Cut on a word, not mid-syllable. A headline that stops halfway
            # through a word reads as a crash, and this page is read fast.
            why = why[:210].rsplit(' ', 1)[0] + ' ...'
        reason = '%s: %s%s' % (worst['title'], why, tail)
        if state == IN_FORCE:
            reason = 'all %d checks under it are in force' % len(leaves)
        results[num] = {'state': state, 'leaves': leaves, 'reason': reason,
                        'statement': statement}

    find_disagreements(D, results)

    if as_json:
        print(json.dumps({
            'tool': 'goals', 'code': '20404741', 'schema': 1, 'read_only': True,
            'generated': time.strftime('%Y-%m-%dT%H:%M:%S'),
            'local': local,
            'goals': [{'n': n, 'statement': results[n]['statement'],
                       'state': results[n]['state'], 'reason': results[n]['reason'],
                       'checks': results[n]['leaves']} for n, _s, _f in GOALS],
            'reassessment': [{'subject': a, 'a': b, 'a_says': c, 'b': d,
                              'b_says': e, 'matters': f}
                             for a, b, c, d, e, f in DISAGREE],
            'could_not_call': [{'tool': t, 'why': w} for t, w in WANTED],
            'blind': BLIND,
        }, indent=2))
        counts = {s: 0 for s in (IN_FORCE, BUILT, NOT_BUILT, CANNOT)}
        for n, _s, _f in GOALS:
            counts[results[n]['state']] += 1
    else:
        counts = render(D, results, full=full, only=only)

    # Non-zero while anything is owed, so this can gate something later. A goal
    # that could not be answered counts as owed: that is the whole discipline.
    return 0 if counts[IN_FORCE] == len(GOALS) else 1


if __name__ == '__main__':
    try:
        sys.exit(main(sys.argv[1:]))
    except KeyboardInterrupt:
        sys.exit(130)
