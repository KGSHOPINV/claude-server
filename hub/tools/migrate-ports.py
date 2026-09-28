#!/usr/bin/env python3
"""
# 20404728  tools.migrate-ports — every project's route from where its ports
are to where they belong, and not one command run.

    python3 hub/tools/migrate-ports.py                  # both hosts, full report
    python3 hub/tools/migrate-ports.py --host ksgcohub  # one host
    python3 hub/tools/migrate-ports.py --json           # the same thing, parseable
    python3 hub/tools/migrate-ports.py --write          # + hub/intake/working/<p>.md
    python3 hub/tools/migrate-ports.py --per-host       # bands scoped per host
    python3 hub/tools/migrate-ports.py --local          # no ssh; says so and stops

THE PROBLEM THIS EXISTS FOR. The project band moved to 12000-18999 at 100 per
project, and a band constant changing is not a migration. Nothing existed that
could say, for one real project on one real machine, WHICH of its ports are
wrong, WHERE they would go, and WHAT a human would type. Without that the
constant is an assertion about a future nobody has a route to, and the projects
that were already scattered stay scattered while the documents say otherwise.

MIGRATION, NOT A CUTOVER. kernel/collect.py states it and this obeys it: a
project keeps its ports until it chooses to move. `accept` is a complete answer
and a project that answers it is FULLY RECONCILED. So this tool does not have a
"should move" column, because that would be an instruction. It has a PROPOSED
column, which is an offer, and a DISPOSITION column, which is the project's.

THE FOUR DISPOSITIONS ARE NOT OURS TO PICK (intake/MANIFEST.md):

    fix         the project will change to match      the project decides
    accept      the deviation is deliberate           the owner decides
    defer       real, not now, with a reason          the owner decides
    hub-wrong   the contract is wrong, not the project    ServerHub decides

`hub-wrong` is a live outcome here, not a courtesy. The contract handed out
ports inside the Supabase stack's reserved 10000-10999 lane for months, and
keynox is sitting in that lane right now BECAUSE IT WAS TOLD TO. A row where
the project did what it was told is a finding about the hub.

CONSTITUTION Law IV — REPORT, NEVER REPAIR. This writes nothing outside
hub/intake/working/, opens no ssh session that is not a read, and every `fix`
is TEXT FOR A HUMAN. It does not edit a compose file, rebind a port, restart a
container, or call a hub endpoint that is not a GET. The commands it prints are
the deliverable; running them is not this tool's job and never becomes it.

WHAT IT REFUSES TO GUESS, because guessing is how this got expensive:

  SERVICES ARE NOT PROJECTS AND NO DOCUMENT SAYS SO. Nobody moves portainer
  off 9443. The band governs PROJECTS. That distinction is load-bearing and it
  was nowhere -- so it is DERIVED here, by three independent tests, and every
  group prints WHICH test decided it. A group no test settles is printed as
  ambiguous and excluded from allocation rather than assumed either way. See
  _classify.

  A BLOCK IN THE BAND CAN ALREADY BE OCCUPIED. babyhelp publishes 12080, which
  is inside the new band, on a host the allocator has to know about. An
  allocator that offers 12000-12099 to someone else has recreated the exact
  defect the band was widened to end. See _squatters and _propose: an incumbent
  keeps the block it is already standing in, and no block is ever offered twice.

  A PORT THAT IS FREE RIGHT NOW MAY NOT BE FREE. `ss -tln` sees listeners, not
  intentions: a stopped container's port reads as available and the port comes
  back when it starts. So stopped containers are counted as occupying their
  ports, and a host where `ss` could not be read has every allocation on it
  marked PROVISIONAL rather than quietly computed from docker alone.

  ONE HOST OR THE WHOLE FLEET IS AN OPEN QUESTION. intake/MANIFEST.md says the
  rules are "scoped to one server by construction". Nothing anywhere says
  whether a BLOCK NUMBER means the same thing on both boxes. Both answers are
  computed; fleet-wide is the default because a number that means two things is
  the disease, and --per-host prints the other. The disagreement between them
  is reported, not resolved, because resolving it is an operator decision.
"""
import json
import os
import re
import subprocess
import sys

# Tools may import kernel. Kernel must never import tools -- so the band, the
# service roster and the lanes are read from the kernel rather than restated
# here. A second copy of PROJECT_BAND_FLOOR is the bug that put /api/admit and
# the Projects lane on different ranges for a fortnight.
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
HUB = os.path.join(ROOT, 'hub')
sys.path.insert(0, HUB)

BLIND = []          # every hole, named. Never allowed to be silently empty.

# THE FALLBACK REFUSES. It does not guess.
#
# This block first shipped with `BAND_FLOOR, BAND_CEIL, BAND_SIZE = 12000,
# 18999, 100` as an except-branch default, which is the same class of defect
# this repo just spent a day removing: handlers/registry.py::_pending was
# hardcoded and keyed on `band[0] == 7100`, so the moment the band moved it
# returned nothing -- telling every project "nothing is coming" at the exact
# instant everything changed. A constant standing in for a fact goes wrong
# silently and stays wrong.
#
# A migration tool planning against the wrong band is worse than one that
# stops, because its output looks identical either way and a human runs it. So
# there is no default: if the kernel cannot be read, BAND_FLOOR is None,
# _require_band() refuses, and nothing below executes.
KERNEL_ERR = ''
try:
    from kernel import collect as _srv          # noqa: E402
    from kernel import control as _ctl          # noqa: E402
    BAND_FLOOR = _srv.PROJECT_BAND_FLOOR
    BAND_CEIL = _srv.PROJECT_BAND_CEIL
    BAND_SIZE = _srv.PROJECT_BAND_SIZE
    SERVICES = _srv.SERVICES
    PORT_LANES = _srv.PORT_LANES
    PORT_NAMES = _srv._PORT_NAMES
    DOCKER_ROOT = _srv.DOCKER_ROOT
    # kernel/control.served_band() is the ONE formatter for this fact. The
    # bulletin changewatch publishes and the pending item /api/admit carries
    # are read by the same project, and this report is read next to both --
    # three formatters for one band eventually disagree by a slash, which
    # reads to a project as three different bands.
    SERVED = _ctl.served_band()
except Exception as _e:                          # pragma: no cover
    KERNEL_ERR = str(_e)[:100]
    BAND_FLOOR = BAND_CEIL = BAND_SIZE = None
    SERVICES, PORT_LANES, PORT_NAMES = [], [], {}
    DOCKER_ROOT = '/srv/docker'
    SERVED = ''


# 20404943  _require_band — stop rather than plan against a number nobody served
def _require_band():
    """The refusal. Called before anything else in main()."""
    if BAND_FLOOR is None or not SERVED:
        sys.stderr.write(
            '\n  REFUSING TO RUN.\n'
            '  The project band could not be read from kernel/collect.py'
            '%s\n' % (' (%s)' % KERNEL_ERR if KERNEL_ERR else
                      ' -- control.served_band() returned nothing') +
            '  There is no fallback band on purpose. Every port number this\n'
            '  tool would print is derived from that constant, so a guess\n'
            '  here produces a migration plan that looks exactly like a\n'
            '  correct one and is not. Run it from the repo root.\n\n')
        return False
    return True

# The band this moved FROM. Named so a port can be reported as "where the hub
# used to send you" rather than the useless "somewhere else".
OLD_BAND = (7100, 7899)
# The lane that made this necessary. /api/admit handed out 10020-10990 while
# the Supabase stack owned 10000-10999, and keynox bound sixteen ports there.
SUPABASE_LANE = (10000, 10999)

# Ports no project may hold on any node, from handlers/node.py RESERVED. Copied
# in shape, not in meaning: this list is used only to keep the allocator off
# them, never to tell a project what is forbidden -- /api/admit does that.
NEVER = {22: 'ssh', 80: 'http', 443: 'https', 8765: 'hub'}

# Hosts, same source and same caveat as tools/fleet-status.py: a node cannot
# enumerate its own fleet, that is central's job, and central is not built.
HOSTS = [
    ('fks-services', 'admin1@192.168.1.229'),
    ('ksgcohub',     'ksgco@100.107.234.9'),
]
TIMEOUT = 30

# A container name is data read off a machine and it is about to be pasted into
# a shell command that a human will run. Docker's own charset is narrower than
# this; anything outside it is DROPPED rather than quoted, because a name that
# cannot legally occur is a name worth refusing. Same rule, same reason, as
# handlers/registry.py::_SAFE_NAME.
_SAFE = re.compile(r'^[A-Za-z0-9][A-Za-z0-9_.-]*$')

# Role buckets, from the OFFSET convention in kernel/collect.py. Suggested and
# never enforced -- the band is the boundary, the split inside it belongs to
# the project. Matched against the image first, then the container name, because
# an image says what a thing IS and a name says what someone called it.
ROLE_BANDS = [
    ('ui',     0,  19),
    ('api',    20, 39),
    ('data',   40, 59),
    ('worker', 60, 79),
    ('dev',    80, 99),
]
ROLE_HINTS = [
    ('data',   ('postgres', 'mysql', 'maria', 'redis', 'surreal', 'meili',
                'elastic', 'minio', 'mongo', 'clickhouse', 'pgbouncer',
                'valkey', 'qdrant')),
    ('api',    ('api', 'rest', 'kong', 'graphql', 'postgraphile', 'gotrue',
                'auth', 'gateway', 'imgproxy', 'gotenberg', 'mcp', 'pgmeta',
                'postgres-meta', 'node', 'vault', 'daemon')),
    ('ui',     ('ui', 'web', 'studio', 'frontend', 'dashboard', 'app', 'console')),
    ('worker', ('worker', 'job', 'queue', 'sync', 'cron', 'n8n', 'scheduler')),
]


def sh(target, cmd, timeout=TIMEOUT):
    """Run over ssh and return (reached, text). Never raises: a probe that dies
    is a blind spot to be named, not a traceback. -n so nothing on this end is
    ever read as input to the far end."""
    try:
        r = subprocess.run(['ssh', '-n', '-o', 'BatchMode=yes',
                            '-o', 'ConnectTimeout=10', target, cmd],
                           capture_output=True, text=True, timeout=timeout)
        out = (r.stdout or '').strip()
        if not out and r.returncode != 0:
            return False, (r.stderr or '').strip()[:120]
        return True, out
    except Exception as e:
        return False, str(e)[:120]


# 20404928  _probe — one host, one round trip, and every section separately fallible
def _probe(name, target):
    """Everything this tool needs about one machine, in ONE connection.

    Three sections, and each can fail on its own. That matters more than it
    looks: `ss` is what turns "docker publishes nothing there" into "nothing at
    all is listening there", and a host that answered docker but not ss is NOT
    a host this tool understands. It is marked provisional rather than folded
    into the confident rows -- because the dangerous output here is not a
    failure, it is a full allocation table computed from half a machine.

    Stopped containers are included deliberately (`docker ps -a`). A stopped
    container's port is free today and bound the moment anyone runs
    `docker compose up`, so an allocator that only sees `docker ps` hands out a
    port that works until the owner restarts something.
    """
    fmt = ('{{.Names}}|{{.Label "com.ksg.project"}}|'
           '{{.Label "com.docker.compose.project"}}|'
           '{{.Label "com.docker.compose.project.config_files"}}|'
           '{{.State}}|{{.Ports}}|{{.Image}}')
    script = (
        "echo '<<<HOST>>>'; hostname\n"
        # The ref assigns before echoing. `echo \"$(git ...)\"` succeeds whether
        # or not git printed anything, so a checkout that is not a repo comes
        # back BLANK -- and blank under a ref column reads as "same as the
        # other box", i.e. as no drift, when nothing was measured at all.
        "echo '<<<REF>>>'; cd ~/hub 2>/dev/null && R=$(git rev-parse --short "
        "HEAD 2>/dev/null); echo \"${R:-?}\"\n"
        "echo '<<<PS>>>'; docker ps -a --format '%s' 2>/dev/null\n"
        "echo '<<<SS>>>'; ss -tlnH 2>/dev/null | awk '{print $4}' "
        "| grep -oE '[0-9]+$' | sort -n -u\n"
        "echo '<<<END>>>'\n" % fmt)
    reached, out = sh(target, script)
    host = {'node': name, 'target': target, 'reached': reached, 'ref': '?',
            'hostname': '', 'containers': [], 'listening': set(),
            'ss_read': False, 'docker_read': False, 'error': ''}
    if not reached:
        host['error'] = out or 'ssh did not answer'
        BLIND.append('%s (%s): not reached -- %s. Every row for this host is '
                     'UNKNOWN, which is not the same as absent.'
                     % (name, target, host['error'] or 'no answer'))
        return host

    sec = None
    for line in out.splitlines():
        s = line.strip()
        if s.startswith('<<<') and s.endswith('>>>'):
            sec = s[3:-3]
            continue
        if not s:
            continue
        if sec == 'HOST':
            host['hostname'] = s
        elif sec == 'REF':
            host['ref'] = s
        elif sec == 'PS':
            p = s.split('|')
            if len(p) < 7:
                continue
            host['docker_read'] = True
            host['containers'].append({
                'name': p[0].strip(), 'ksg': p[1].strip(),
                'compose': p[2].strip(), 'config': p[3].strip(),
                'state': p[4].strip(), 'ports_raw': p[5].strip(),
                'image': p[6].strip(),
            })
        elif sec == 'SS' and s.isdigit():
            host['ss_read'] = True
            host['listening'].add(int(s))

    # The hub each box runs is not the hub this repo is. A packet generated
    # here states a band the node's own /api/admit may not serve yet, and a
    # project told two bands by two mouths believes neither.
    if host['ref'] in ('?', ''):
        BLIND.append('%s: its hub ref could not be read, so there is no way to '
                     'say whether the node serves the band this report is built '
                     'on. Blank is not "same as the other box".' % name)
    if not host['docker_read']:
        BLIND.append('%s: ssh answered but `docker ps -a` returned nothing. '
                     'Either the daemon is down or this user cannot read it. '
                     'No project row on this host is trustworthy.' % name)
    if not host['ss_read']:
        BLIND.append('%s: `ss -tln` could not be read. Non-docker listeners are '
                     'INVISIBLE, so every proposed block on this host is '
                     'PROVISIONAL -- a port that looks free may already be '
                     'held by something that is not a container.' % name)
    return host


# 20404929  _parse_ports — the host side of a docker Ports string, and only that
def _parse_ports(raw):
    """`0.0.0.0:10005->8000/tcp, [::]:10005->8000/tcp, 8001-8004/tcp`

    Two things here are load-bearing. The `->` is required, so `8001-8004/tcp`
    -- a container port EXPOSEd and not published -- is not counted. Counting it
    would have keynox holding 8001, which surrealdb actually owns, and the
    report would invent a collision that does not exist.

    And the v4 and v6 publications of one port are the same port, so the result
    is a set. A list would report keynox publishing 32 ports where it publishes
    16, and every count downstream would be double.
    """
    out = set()
    for m in re.finditer(r'(?:(?:\d{1,3}(?:\.\d{1,3}){3})|\[[^\]]*\]):(\d+)->', raw or ''):
        try:
            out.add(int(m.group(1)))
        except ValueError:
            pass
    # Published ranges: 0.0.0.0:80-81->80-81/tcp
    for m in re.finditer(r'(?:(?:\d{1,3}(?:\.\d{1,3}){3})|\[[^\]]*\]):(\d+)-(\d+)->', raw or ''):
        try:
            lo, hi = int(m.group(1)), int(m.group(2))
            if 0 < lo <= hi and hi - lo < 64:
                out.update(range(lo, hi + 1))
        except ValueError:
            pass
    return out


# 20404930  _group — containers by owner, four channels, and which one answered
def _group(host):
    """Same preference order as handlers/node.py::_projects, with the name
    channel that handlers/registry.py::_machine already uses added between --
    because on this fleet the first two channels are EMPTY for the containers
    that matter most.

        label    com.ksg.project              the contract. ZERO containers
                                              carry it on either box today.
        compose  com.docker.compose.project   what compose grouped
        name     <owner>-*                    matched against owners the first
                                              two channels already proved exist
        derived  leading segment of the name  the weakest channel, and the only
                                              one that can invent an owner

    The fourth channel is why this function is not three lines. `flarevault-node`
    and `flarevault-monitor` carry NO labels of any kind and no compose project:
    under the kernel's grouping they are two separate containers in the
    `unassigned` bucket, and a project publishing 7777 does not exist. Deriving
    an owner from the name makes them one project that can be reasoned about --
    but a derived owner is a GUESS, so it is recorded as one and every group
    prints the channel that named it.

    `keynox-10-meilisearch-1` is the case that proves the third channel: it is
    the one keynox container with no labels at all, it holds 7700, and without
    the name match keynox reads as a 15-port project in one lane instead of a
    16-port project across three.
    """
    groups = {}
    # Pass 1 and 2: the channels that cannot invent a name.
    for c in host['containers']:
        owner, via = '', ''
        if c['ksg']:
            owner, via = c['ksg'].lower(), 'label'
        elif c['compose']:
            owner, via = c['compose'].lower(), 'compose'
        if not owner:
            continue
        g = groups.setdefault(owner, {'name': owner, 'containers': [],
                                      'channels': set(), 'labelled': 0})
        g['channels'].add(via)
        g['containers'].append(dict(c, via=via))
        if c['ksg']:
            g['labelled'] += 1

    # Pass 3: name-prefix, but only onto owners that already exist. This cannot
    # create a project, only attach a stray to one -- which is the whole point.
    known = sorted(groups, key=len, reverse=True)
    leftover = []
    for c in host['containers']:
        if c['ksg'] or c['compose']:
            continue
        cn = c['name'].lower()
        hit = ''
        for k in known:
            if cn == k or any(cn.startswith(k + s) for s in ('-', '_', '.')):
                hit = k
                break
        if hit:
            groups[hit]['channels'].add('name')
            groups[hit]['containers'].append(dict(c, via='name'))
        else:
            leftover.append(c)

    # Pass 4: derive from the leading segment. Only fires when nothing else did.
    derived = {}
    for c in leftover:
        seg = re.split(r'[-_.]', c['name'].lower())[0]
        derived.setdefault(seg or c['name'].lower(), []).append(c)
    for seg, cs in derived.items():
        g = groups.setdefault(seg, {'name': seg, 'containers': [],
                                    'channels': set(), 'labelled': 0})
        g['channels'].add('derived')
        for c in cs:
            g['containers'].append(dict(c, via='derived'))

    for g in groups.values():
        g['ports'] = set()
        g['configs'] = sorted({c['config'] for c in g['containers'] if c['config']})
        for c in g['containers']:
            g['ports'] |= _parse_ports(c['ports_raw'])
        g['channels'] = sorted(g['channels'])
        g['stopped'] = [c['name'] for c in g['containers']
                        if not c['state'].lower().startswith('run')]
    return groups


# 20404931  _classify — service, project, or not governed at all
def _classify(g):
    """THE DISTINCTION NO DOCUMENT STATES. The band governs PROJECTS. Nobody
    moves portainer off 9443, and a migration tool that proposed it would be
    worse than no tool -- it would be a confident tool that is wrong about the
    infrastructure it runs on.

    THE FIRST VERSION OF THIS FUNCTION GOT IT WRONG, and the way it was wrong is
    worth keeping written down because it is the obvious design. It scored three
    tests -- roster, compose-directory shape, port-lane -- and called anything
    that passed two of them a service. On the real fleet that classified
    `fksinv` as INFRASTRUCTURE: its compose sits at /srv/docker/fksinv/ and its
    ports 10100/10101 fall inside the Supabase stack lane, so "shape" and "lane"
    both said service. Both signals were real and both meant the opposite of
    what they were read as. Living at /srv/docker/<name> is what /api/admit
    TELLS PROJECTS TO DO, and sitting in the Supabase lane is the deviation this
    entire migration exists to surface. A project had done everything asked of
    it and everything it was wrongly directed into, and the reward was being
    quietly removed from the migration table.

    So the rule is now one authoritative test and two honest outcomes:

      S1 ROSTER      the name is a service in kernel/collect.py SERVICES. This
                     is the hub's own list of what the server kit installs and
                     what /api/services already reports. It is the only signal
                     here that MEANS service rather than merely correlating
                     with one.
      NOT GOVERNED   the group publishes no host port at all. The band governs
                     published ports, so there is nothing to migrate and
                     nothing to classify. `watchtower` lands here -- and that
                     is a better answer than calling it a service, because this
                     tool has no evidence either way and does not need any.
      PROJECT        everything else. Publishing a host port while not being on
                     the roster is exactly what a project is.

    The ambiguity that IS worth raising is the reverse one: a group off the
    roster whose every published port already has a service name in
    _PORT_NAMES. That is infrastructure the roster forgot, and proposing to
    move it would be the expensive mistake. It is flagged and excluded rather
    than allocated. Nothing on this fleet matches today.

    The case that proves the roster test: keynox publishes 10012 from an n8n
    image, the same image as the SERVICE n8n at 7002. Classifying by image
    would have folded a sixteen-port project into a service and hidden every
    port in this report.
    """
    nm = g['name'].lower()
    roster = {re.sub(r'[^a-z0-9]', '', (s.get('name') or '').lower())
              for s in SERVICES}
    if re.sub(r'[^a-z0-9]', '', nm) in roster:
        return 'service', 'S1 roster', False
    if not g['ports']:
        return 'not-governed', 'publishes no host port', False
    if all(p in PORT_NAMES or p < 1024 for p in g['ports']):
        return 'project', 'AMBIGUOUS — off the roster, but every port it ' \
                          'publishes is a named service port', True
    return 'project', 'off the roster and publishing host ports', False


def _lane(port):
    for lane in PORT_LANES:
        for lo, hi in lane.get('ranges', ()):
            if lo <= port <= hi:
                return lane['name']
    return 'Other'


# 20404932  _verdict — where one port actually stands
def _verdict(port):
    """Five answers, and "elsewhere" is one of them rather than a shrug.

    OLD BAND is kept separate from ELSEWHERE on purpose: a port at 7777 is not
    an arbitrary choice, it is a project that did what /api/admit told it when
    /api/admit said 7100-7899. That is a different conversation from a port
    someone picked off the top of their head, and collapsing the two loses the
    only mitigating fact in the row.

    RESERVED LANE is the same argument one degree worse: /api/admit handed out
    10020-10990 while the Supabase stack owned 10000-10999. A project in there
    is a project that was MISDIRECTED, which is a finding about the hub.
    """
    if BAND_FLOOR <= port <= BAND_CEIL:
        return 'in-band', 'inside %d-%d' % (BAND_FLOOR, BAND_CEIL)
    if OLD_BAND[0] <= port <= OLD_BAND[1]:
        return 'old-band', 'the band this replaced (%d-%d)' % OLD_BAND
    if SUPABASE_LANE[0] <= port <= SUPABASE_LANE[1]:
        return 'reserved-lane', ('inside the Supabase stack lane %d-%d, which '
                                 '/api/admit used to hand out' % SUPABASE_LANE)
    lane = _lane(port)
    if lane not in ('Projects', 'Other'):
        return 'service-lane', 'inside the %s lane' % lane
    return 'elsewhere', 'in no lane anything claims'


# 20404933  _squatters — every port spoken for on a host, and by whom
def _squatters(host, groups):
    """The bug this exists to end. babyhelp publishes 12080 -- inside the new
    band, on a live machine -- and an allocator that offers 12000-12099 to
    someone else has recreated exactly the defect the band was widened to fix.
    handlers/node.py::_free_band checks `ss`, so it would skip that block TODAY;
    it would stop skipping it the moment babyhelp's container is stopped for an
    upgrade, and the next project to ask would be sent straight into it.

    So occupancy here is the union of three things, not one:
      * every port any container PUBLISHES, running or stopped
      * every port `ss -tln` reports listening, container or not
      * the ports nothing may ever hold (ssh, http, https, the hub)

    Returns (occupied_ports, owner_of_port). The owner map is what lets a block
    be offered back to its own incumbent instead of being declared unavailable.
    """
    occupied = set(NEVER)
    owner = {p: 'reserved' for p in NEVER}
    for p in host['listening']:
        occupied.add(p)
        owner.setdefault(p, 'a listener `ss` saw, unattributed')
    for g in groups.values():
        for p in g['ports']:
            occupied.add(p)
            owner[p] = g['name']
    return occupied, owner


# 20404934  _propose — a block per project, incumbents first, nothing offered twice
def _propose(projects, occupied, owner, reserved_blocks, seat_only=False):
    """The allocator, and every rule in it is here because its absence costs
    something specific.

    INCUMBENTS FIRST, AND FLEET-WIDE BEFORE ANYONE IS PLACED. A project already
    publishing inside the band keeps the block it is standing in. babyhelp at
    12080 is offered 12000-12099 -- the block it already occupies -- so its
    proposal is "stay", its disposition is `accept`, and its migration is over.

    THIS FUNCTION SHIPPED WITH THE EXACT BUG IT WAS WRITTEN TO PREVENT, and the
    first run caught it. Incumbency was resolved per host, in host order. So
    fks-services was placed first, flarevault -- which is NOT an incumbent
    anywhere -- was handed 12000-12099 as the first free block, and by the time
    ksgcohub was read, babyhelp's own block was gone. The tool printed
    "CONFLICT" against the one project that had done nothing wrong. Hence
    `seat_only`: the caller runs this over EVERY host with seat_only=True
    first, seating everyone who is already standing somewhere, and only then
    runs it again to place the newcomers. Two passes over the fleet, not one
    pass per host. An allocator that cannot see the whole fleet before it
    starts handing out ground is the bug this exercise exists to end, and it is
    apparently easy enough to write twice.

    A BLOCK IS NEVER OFFERED TWICE, including to a project on the other host,
    unless --per-host says otherwise. intake/MANIFEST.md scopes rules to one
    server; it does not say whether a BLOCK NUMBER means one thing fleet-wide.
    Both answers are computed. Fleet-wide is the default because the cheaper
    mistake is a project placed further up an empty 7000-port band than it
    needed to be, and the expensive one is two projects that believe they own
    12000-12099 discovering it during a move.

    STABLE ORDER. Non-incumbents are allocated alphabetically, so re-running
    this on an unchanged fleet produces the identical table. An allocator whose
    output moves between runs cannot be diffed, and a migration plan that cannot
    be diffed is read once and never checked again.

    A block is unavailable if it contains ANY occupied port not belonging to
    the project being placed. Not "any listening port" -- any port anything
    holds, including a stopped container's, because the difference between
    those two is a bug that only appears during someone's upgrade.
    """
    taken = dict(reserved_blocks)       # block floor -> project that holds it
    out = {}

    def block_free(base, who):
        if base in taken and taken[base] != who:
            return False
        for p in range(base, base + BAND_SIZE):
            if p in occupied and owner.get(p) != who:
                return False
        return True

    # Pass 1 -- incumbents keep their ground.
    for name in sorted(projects):
        g = projects[name]
        inb = sorted(p for p in g['ports'] if BAND_FLOOR <= p <= BAND_CEIL)
        if not inb:
            continue
        bases = sorted({BAND_FLOOR + ((p - BAND_FLOOR) // BAND_SIZE) * BAND_SIZE
                        for p in inb})
        base = bases[0]
        note = 'incumbent -- already publishing inside this block'
        if len(bases) > 1:
            note = ('incumbent, but its in-band ports STRADDLE %d blocks (%s). '
                    'The lowest is proposed and the straddle is a difference in '
                    'its own right, not a rounding decision for this tool.'
                    % (len(bases), ', '.join(str(b) for b in bases)))
        if base in taken and taken[base] != name:
            note = ('CONFLICT -- %s already holds this block. Two projects '
                    'cannot both be incumbent here and this tool will not '
                    'choose between them.' % taken[base])
            out[name] = {'block': None, 'note': note, 'incumbent': True}
            continue
        taken[base] = name
        out[name] = {'block': [base, base + BAND_SIZE - 1], 'note': note,
                     'incumbent': True}

    # Pass 2 -- everyone else, alphabetically, first block that is wholly free.
    for name in sorted(projects):
        if name in out or seat_only:
            continue
        base = BAND_FLOOR
        placed = None
        while base + BAND_SIZE - 1 <= BAND_CEIL:
            if block_free(base, name):
                placed = base
                break
            base += BAND_SIZE
        if placed is None:
            out[name] = {'block': None,
                         'note': 'NO FREE BLOCK in %d-%d. The band is full, '
                                 'which is a finding about the contract, not '
                                 'about this project.' % (BAND_FLOOR, BAND_CEIL),
                         'incumbent': False}
            continue
        taken[placed] = name
        out[name] = {'block': [placed, placed + BAND_SIZE - 1],
                     'note': 'first wholly-free block', 'incumbent': False}
    return out, taken


def _role(c):
    """Which offset bucket a container belongs in. Image first, name second."""
    hay = (c.get('image', '') + ' ' + c.get('name', '')).lower()
    for role, words in ROLE_HINTS:
        if any(w in hay for w in words):
            return role
    return 'dev'


# 20404935  _map_ports — old port -> new port, using the offset convention
def _map_ports(g, block, occupied, owner):
    """A block is not a plan. A human running a `fix` needs a NUMBER per port,
    and the number has to come from somewhere defensible.

    kernel/collect.py suggests the last two digits carry the role, so the port
    itself says what kind of thing it is. That is followed here and marked
    SUGGESTED every time it is printed, because collect.py is explicit that the
    split inside a block belongs to the project.

    Ports are mapped in ascending order within each role bucket so the mapping
    is stable across runs. A port already inside the proposed block KEEPS ITS
    NUMBER -- moving babyhelp from 12080 to 12080 is not a migration step, and
    printing it as one would put a line in a plan that does nothing and still
    has to be read.
    """
    if not block:
        return {}, []
    base = block[0]
    by_role = {}
    port_role = {}
    for c in g['containers']:
        r = _role(c)
        for p in _parse_ports(c['ports_raw']):
            port_role[p] = r
    for p in sorted(g['ports']):
        by_role.setdefault(port_role.get(p, 'dev'), []).append(p)

    mapping, notes = {}, []
    used = set()
    for p in sorted(g['ports']):
        if base <= p <= base + BAND_SIZE - 1:
            mapping[p] = p                       # already home
            used.add(p)
    for role, lo, hi in ROLE_BANDS:
        cur = base + lo
        for p in by_role.get(role, []):
            if p in mapping:
                continue
            while cur <= base + hi and (cur in used or
                                        (cur in occupied and owner.get(cur) != g['name'])):
                cur += 1
            if cur > base + hi:
                notes.append('role bucket `%s` (%d-%d) is full; %d spilled '
                             'outside its suggested offsets'
                             % (role, base + lo, base + hi, p))
                cur = base
                while cur <= base + BAND_SIZE - 1 and (
                        cur in used or (cur in occupied and owner.get(cur) != g['name'])):
                    cur += 1
                if cur > base + BAND_SIZE - 1:
                    notes.append('block %d-%d cannot hold %d ports; %d is '
                                 'unplaced' % (base, base + BAND_SIZE - 1,
                                               len(g['ports']), p))
                    continue
            mapping[p] = cur
            used.add(cur)
            cur += 1
    return mapping, notes


# 20404936  _diffs — rows in exactly the shape record_diffs() already stores
def _diffs(g, kind, proposal, mapping, host):
    """{claimed, machine, why, fix} -- the same four keys
    handlers/registry.py::_compare produces and kernel/control.record_diffs
    writes, so these flow into the existing diffs table and inherit the
    disposition-carrying behaviour instead of becoming a second register.

    `claimed` and `machine` are the IDENTITY record_diffs uses to carry a
    disposition across re-verification, so both are written to be STABLE while
    the situation is: sorted port lists and counts, never a timestamp, an uptime
    or a proposed number. That last one matters here specifically -- putting the
    proposed port into `machine` would re-open every decided difference the
    moment the allocator's input changed, and the allocator's input is the whole
    fleet.
    """
    d = []
    ports = sorted(g['ports'])
    if not ports:
        return d
    buckets = {}
    for p in ports:
        buckets.setdefault(_verdict(p)[0], []).append(p)

    outside = sorted(p for p in ports if not BAND_FLOOR <= p <= BAND_CEIL)
    if outside:
        d.append({
            'claimed': "binds inside this server's project band",
            'machine': 'publishes %s, outside %d-%d'
                       % (', '.join(str(p) for p in outside), BAND_FLOOR, BAND_CEIL),
            'why': 'the band is the one lane this server promises not to hand to '
                   'anything else. Outside it the port belongs to whoever got '
                   'there first, and nothing announces the day that changes. '
                   'This is a difference, not a fault: the band moved on '
                   '2026-09-24 and existing projects keep their ports until '
                   'they choose to move.',
            'fix': 'nothing, if the answer is `accept`. To move: rebind to %s '
                   'in %s, `docker compose up -d`, then re-file the claim.'
                   % (proposal['block'] and '%d-%d' % tuple(proposal['block']) or 'a block this tool could not allocate',
                      g['configs'][0] if g['configs'] else 'the compose file'),
        })

    if buckets.get('reserved-lane'):
        pl = buckets['reserved-lane']
        d.append({
            'claimed': 'binds in a lane no other stack owns',
            'machine': 'publishes %d port(s) inside %d-%d: %s'
                       % (len(pl), SUPABASE_LANE[0], SUPABASE_LANE[1],
                          ', '.join(str(p) for p in pl)),
            'why': 'THIS ONE IS PROBABLY OURS. /api/admit declared the project '
                   'band as 10020-10990 while kernel/collect.py already gave '
                   '10000-10999 to the Supabase stack, so a project that bound '
                   'here did what it was told. `hub-wrong` is the likely '
                   'disposition and it is a finding about ServerHub, not about '
                   'this project.',
            'fix': 'record the disposition. If `hub-wrong`, the contract is '
                   'what changes, not the project.',
        })

    if buckets.get('old-band'):
        pl = buckets['old-band']
        d.append({
            'claimed': 'binds inside the current project band',
            'machine': 'publishes %s, inside the PREVIOUS band %d-%d'
                       % (', '.join(str(p) for p in pl), OLD_BAND[0], OLD_BAND[1]),
            'why': 'this is the band /api/admit advertised until 2026-09-24. A '
                   'port here is a project that complied with the contract of '
                   'the day, so the deviation is the contract moving, not the '
                   'project drifting.',
            'fix': 'nothing is required. To move, see the commands in this '
                   "project's packet under hub/intake/working/.",
        })

    if len(ports) > BAND_SIZE:
        d.append({
            'claimed': 'fits inside one %d-port block' % BAND_SIZE,
            'machine': 'publishes %d ports' % len(ports),
            'why': 'a project wider than a block cannot be described by one '
                   'band, which is a sizing question for the contract rather '
                   'than a fault in the project. Outgrowing 100 is a ticket, '
                   'not a violation.',
            'fix': 'raise it as a contract question -- PROJECT_BAND_SIZE lives '
                   'in kernel/collect.py and is not a per-project setting.',
        })

    spread = sorted({_verdict(p)[0] for p in ports})
    if len(spread) > 1:
        d.append({
            'claimed': 'publishes from one contiguous range',
            'machine': '%d ports across %d different ranges: %s'
                       % (len(ports), len(spread), ', '.join(spread)),
            'why': 'scattered ports have no start and no end, so nothing can '
                   'say where this project begins or what it would collide '
                   'with. This is the condition PROJECT_BAND_SIZE=100 exists '
                   'to end.',
            'fix': 'see the per-port mapping in the packet; it is one rebind '
                   'per port and one `docker compose up -d`.',
        })

    if g['labelled'] == 0 and g['containers']:
        d.append({
            'claimed': 'com.ksg.project=%s on every container' % g['name'],
            'machine': '%d container(s) match by %s, 0 carry the label'
                       % (len(g['containers']), ' / '.join(g['channels'])),
            'why': 'Constitution VI: `docker ps --filter '
                   'label=com.ksg.project=%s` returns 0 of %d. Nothing on the '
                   'host can attribute these containers, so this tool had to '
                   'derive the grouping -- and a port table built on a derived '
                   'grouping is only as good as the guess underneath it.'
                   % (g['name'], len(g['containers'])),
            'fix': 'add `labels: ["com.ksg.project=%s"]` to each service in %s. '
                   'Labels are immutable on a running container, so it takes '
                   'effect on the next recreate -- with no extra downtime ever, '
                   'if it waits for one that was going to happen anyway.'
                   % (g['name'], g['configs'][0] if g['configs'] else 'the compose file'),
        })

    if 'derived' in g['channels']:
        d.append({
            'claimed': 'a named project on %s' % host['node'],
            'machine': 'no label and no compose project; the name "%s" was '
                       'derived from the container names' % g['name'],
            'why': 'this project exists in this report because a tool split a '
                   'container name on a hyphen. That is a guess, and it is the '
                   'only thing holding these containers together as one thing. '
                   'If the guess is wrong every row above is wrong with it.',
            'fix': 'confirm or correct the name, then declare it with '
                   'com.ksg.project so nothing has to guess again.',
        })
    return d


# 20404937  _commands — the exact text, for a human, run by nobody here
def _commands(g, proposal, mapping, host):
    """A `fix` disposition is the project's to give and the project's to
    execute. What this owes is that the work is not research: which file, which
    line, what it becomes, in the order it has to happen.

    So every line below is TEXT. Nothing in this module runs any of it, and the
    first command is deliberately a read -- `docker compose config` prints the
    resolved file without touching anything, which is how a person checks that
    the path in this packet is the path they are about to edit.
    """
    if not proposal.get('block'):
        return ['(no block could be allocated -- see the note on this project)']

    if not g['configs']:
        # NO PLAN IS THE HONEST OUTPUT. Printing the compose recipe with a
        # placeholder where the filename goes produces something that LOOKS
        # like a set of steps, and a reader skims to the `docker compose up`.
        # There is no file. The first real question is how these containers
        # were started at all, because a container nothing on disk can
        # reproduce does not survive the host, never mind a rebind.
        return [
            '# on %s  (ssh %s)' % (host['node'], host['target']),
            '#',
            '# THERE IS NO PLAN HERE YET, AND THAT IS THE FINDING.',
            '# %s carries no compose project and no config_files label, so'
            % g['name'],
            '# there is no file to edit and this tool will not invent a path.',
            '# %d container(s) are running with nothing on disk that is known'
            % len(g['containers']),
            '# to reproduce them. Rebinding is the second question; the first',
            '# is whether this survives the host being rebuilt.',
            '#',
            '# Establish that first -- all three are reads:',
            "docker inspect %s --format '{{json .Config.Labels}}'"
            % ' '.join(c['name'] for c in g['containers']
                       if _SAFE.match(c['name'])),
            "docker inspect %s --format '{{.Name}} {{.HostConfig.RestartPolicy.Name}} "
            "{{json .HostConfig.PortBindings}}'"
            % ' '.join(c['name'] for c in g['containers']
                       if _SAFE.match(c['name'])),
            'grep -rl "%s" /srv/docker ~/ --include="*.yml" --include="*.yaml" 2>/dev/null'
            % g['name'],
            '#',
            '# Once a file is found, re-run:',
            '#   python3 hub/tools/migrate-ports.py --write',
            '# and this section becomes the port table it should have been.',
            '#',
            '# Proposed block, for when there is somewhere to write it: %d-%d'
            % (proposal['block'][0], proposal['block'][1]),
        ] + ['#   %d -> %d' % (o, n) for o, n in sorted(mapping.items())]

    cfg = g['configs'][0]
    moves = [(o, n) for o, n in sorted(mapping.items()) if o != n]
    lines = [
        '# on %s  (ssh %s)' % (host['node'], host['target']),
        '# nothing below has been run. Read it, then run it yourself.',
        '',
        '# 1. confirm this is the file that is actually live',
        'docker compose -f %s config | head -40' % cfg,
        '',
        '# 2. the port lines to change, in %s' % cfg,
    ]
    if not moves:
        lines.append('#    none -- every published port is already inside %d-%d'
                     % (proposal['block'][0], proposal['block'][1]))
    for o, n in moves:
        cs = [c['name'] for c in g['containers'] if o in _parse_ports(c['ports_raw'])]
        cport = ''
        for c in g['containers']:
            m = re.search(r':%d->(\d+)' % o, c['ports_raw'] or '')
            if m:
                cport = m.group(1)
                break
        lines.append('#    %-28s  "%s:%s"  ->  "%d:%s"   (%s)'
                     % (', '.join(cs) or '?', o, cport or '?', n, cport or '?',
                        _role({'image': '', 'name': ', '.join(cs)})))
    # The compose PROJECT is not always the compose DIRECTORY. keynox's file
    # lives at /srv/docker/metaforge/, so a bare `docker compose up -d` in that
    # directory defaults the project name to `metaforge` and can orphan or
    # duplicate every container instead of recreating it. -p is not belt and
    # braces here; it is the difference between a rebind and an outage.
    cproj = next((c['compose'] for c in g['containers'] if c['compose']), g['name'])
    # Step 4 has to use a channel that actually answers. `docker ps --filter
    # label=com.ksg.project=<p>` is the acceptance test in the contract, and on
    # this project it returns ZERO rows -- carrying no label is one of the
    # differences listed above. A verification command that prints nothing
    # whether or not the work succeeded is worse than no verification, because
    # it looks like it ran.
    verify = ("docker ps --filter label=com.ksg.project=%s --format "
              "'{{.Names}} {{.Ports}}'" % g['name'])
    if g['labelled'] == 0:
        verify = ("# the contract's acceptance test would return 0 rows here --\n"
                  "# this project carries no com.ksg.project label. Using the\n"
                  "# channel that does answer, and this substitution is itself\n"
                  "# one of the differences above:\n"
                  "docker compose -f %s ps --format '{{.Name}} {{.Ports}}'" % cfg)
    lines += [
        '',
        '# 3. apply -- recreates only what changed.',
        '#    -p is required: the directory is `%s`, the compose project is'
        % (os.path.basename(os.path.dirname(cfg.replace('\\', '/'))) or '?'),
        '#    `%s`, and a bare `up -d` would use the directory name.' % cproj,
        'docker compose -f %s -p %s up -d' % (cfg, cproj),
        '',
        '# 4. prove it, from the host',
        verify,
        ('ss -tln | grep -E ":(%s)\\b"' % '|'.join(str(n) for _, n in moves))
        if moves else 'ss -tln | grep -c LISTEN',
        '',
        '# 5. tell the hub, so /api/admit stops believing the old numbers',
        "curl -s -X POST http://127.0.0.1:8765/api/registry/%s "
        "-d '{\"ports\": [%s]}'"
        % (g['name'], ', '.join(str(n) for n in sorted(mapping.values()))),
        '',
        '# ROLLBACK: git checkout the compose file and `docker compose up -d`.',
        '#   The old ports are released the moment the new ones bind, so a',
        '#   rollback that is not immediate can find them taken. Do it in one',
        '#   sitting or not at all.',
    ]
    return lines


# 20404938  _packet — the per-project markdown, shaped like projects/babyhelp.md
def _packet(g, kind, host, proposal, mapping, diffs, cmds, notes):
    """Matches hub/intake/projects/babyhelp.md, which is the only worked example
    and carries one rule this file obeys literally:

        "No observed values are written in this file, and none should be."

    That rule belongs to projects/ -- the STANDING record, which sits beside
    control.db and must not become a second copy of it. This writes to
    working/, which MANIFEST.md defines as "claim being verified against its
    host": a stage, not a record, disposable by construction and regenerated
    every run. So observed values DO belong here, and the header says so rather
    than letting a reader assume the babyhelp rule was ignored.

    What this file is for, and why each difference is a difference, is the part
    a command cannot supply. That is the part written longhand.
    """
    b = proposal.get('block')
    out = [
        '# %s — port migration packet (%s)' % (g['name'], host['node']), '',
        '**This project is not ours to change.** Read to describe; never touch.',
        "Nothing in this file is an instruction to anyone but the project's own",
        'owner, and nothing in it has been run against anything.',
        '',
    ]
    out += [
        '> **This is a `working/` file, not a standing record.** MANIFEST.md',
        '> defines `working/` as the claim being verified against its host, so',
        '> unlike `projects/<name>.md` this one DOES carry observed values —',
        '> it is regenerated on every run and is disposable by construction.',
        '> The standing record stays in `control.db`:',
        '>',
        '> ```bash',
        '> curl -s <hub>/api/registry/%s           the standing record' % g['name'],
        '> curl -s <hub>/api/registry/%s/diffs     differences + dispositions' % g['name'],
        '> curl -s "<hub>/api/admit?project=%s"    the rules, derived live' % g['name'],
        '> ```',
        '',
        '---',
        '',
        '## What the machine says',
        '',
        '| | |',
        '|---|---|',
        '| host | `%s` (%s) |' % (host['node'], host['target']),
        '| classified | **%s** |' % kind,
        '| grouped by | %s |' % ', '.join(g['channels']),
        '| containers | %d (%d carry `com.ksg.project`) |'
        % (len(g['containers']), g['labelled']),
        '| compose | %s |' % (', '.join('`%s`' % c for c in g['configs']) or '*none on the host*'),
        '| published ports | %s |' % (', '.join(str(p) for p in sorted(g['ports'])) or 'none'),
        '| stopped containers | %s |' % (', '.join(g['stopped']) or 'none'),
        '',
    ]

    out += ['## Where each port stands', '',
            '| port | verdict | what that means |', '|---|---|---|']
    for p in sorted(g['ports']):
        v, why = _verdict(p)
        out.append('| %d | `%s` | %s |' % (p, v, why))
    if not g['ports']:
        out.append('| — | — | publishes nothing; the band does not govern it |')
    out.append('')

    out += ['## The offer', '']
    if b:
        out += ['**Proposed block: `%d–%d`** — %s' % (b[0], b[1], proposal['note']),
                '',
                'Per-port mapping. The last two digits follow the role',
                'convention in `kernel/collect.py`, which that file marks',
                '**suggested, never enforced** — the block is the boundary, the',
                'split inside it belongs to the project.', '',
                '| now | proposed | note |', '|---|---|---|']
        for o in sorted(mapping):
            n = mapping[o]
            out.append('| %d | %d | %s |' % (o, n, 'unchanged — already in block'
                                             if o == n else 'rebind'))
        out.append('')
    else:
        out += ['**No block proposed.** %s' % proposal['note'], '']
    for n in notes:
        out.append('- %s' % n)
    if notes:
        out.append('')

    out += ['## The differences, and why each is one', '']
    if not diffs:
        out.append('None. Every published port is inside the band and every')
        out.append('container carries its label — which is worth stating,')
        out.append('because agreement is evidence too.')
    for i, d in enumerate(diffs, 1):
        out += ['### %d. %s' % (i, d['claimed']), '',
                '- **machine:** %s' % d['machine'],
                '- **why it matters:** %s' % d['why'],
                '- **if `fix`:** %s' % d['fix'], '']

    out += ['## If the disposition is `fix` — the exact commands', '',
            'Nothing below has been run and nothing in this repo will run it.',
            'It is here so the work is not research.', '',
            '```bash'] + cmds + ['```', '']

    out += ['## The dispositions, and who gives them', '',
            '| | |', '|---|---|',
            '| `fix` | the project will move. **The project decides, never the hub.** |',
            '| `accept` | deliberate, and it stays. Needs no justification beyond being deliberate. |',
            '| `defer` | real, not now, with a reason. |',
            '| `hub-wrong` | the contract is wrong, not the project. ServerHub changes. |',
            '',
            '**Reconciled means every difference has a disposition — not that',
            'every difference is fixed.** A project that answers `accept` to',
            'all of the above is fully reconciled and its migration is over.',
            'An undeclared deviation is the only failure state.', '',
            '---', '',
            '*Regenerated by `python3 hub/tools/migrate-ports.py --write`.',
            'Dispositions are not stored here and cannot be re-derived; they',
            'live in `control.db` and are what gets backed up.*', '']
    return '\n'.join(out)


# 20404939  _write_packets — inside hub/intake/working/ and provably nowhere else
def _write_packets(packets):
    """The brief allows exactly one directory. So the path is not merely built
    under it, it is CHECKED against it after normalisation -- a project name is
    data read off a machine, and a machine that reports a container called
    `../../etc` should produce a refusal, not a file.
    """
    base = os.path.realpath(os.path.join(HUB, 'intake', 'working'))
    written, refused = [], []
    for name, text in sorted(packets.items()):
        safe = re.sub(r'[^a-z0-9._-]', '', name.lower())
        path = os.path.realpath(os.path.join(base, safe + '.md'))
        if not safe or os.path.dirname(path) != base:
            refused.append(name)
            continue
        try:
            with open(path, 'w', encoding='utf-8', newline='\n') as f:
                f.write(text)
            written.append(os.path.relpath(path, ROOT).replace('\\', '/'))
        except Exception as e:
            refused.append('%s (%s)' % (name, str(e)[:50]))
    return written, refused


# 20404940  survey — every host, every group, the whole derivation
def survey(argv):
    per_host = '--per-host' in argv
    want = ''
    if '--host' in argv:
        i = argv.index('--host')
        if i + 1 < len(argv):
            want = argv[i + 1]

    if '--local' in argv:
        BLIND.append('--local: no host was contacted. There is nothing to '
                     'migrate that can be derived from source alone -- the '
                     'ports are a fact about a running machine, not about this '
                     'repo. This mode exists to prove the tool imports.')
        return {'hosts': [], 'projects': [], 'per_host': per_host, 'local': True}

    hosts = []
    for name, target in HOSTS:
        if want and want not in (name, target):
            continue
        hosts.append(_probe(name, target))
    if want and not hosts:
        BLIND.append('--host %s matched no known host. Known: %s'
                     % (want, ', '.join(n for n, _ in HOSTS)))

    # Pass one: group and classify on every host that answered.
    per = []
    for h in hosts:
        groups = _group(h)
        occupied, owner = _squatters(h, groups)
        projects, services, ambiguous = {}, {}, []
        for n, g in groups.items():
            kind, by, amb = _classify(g)
            g['kind'], g['by'] = kind, by
            if amb:
                ambiguous.append(n)
                services[n] = g          # held out of allocation deliberately
            elif kind == 'project':
                projects[n] = g
            else:
                services[n] = g
        per.append({'host': h, 'groups': groups, 'projects': projects,
                    'services': services, 'ambiguous': ambiguous,
                    'occupied': occupied, 'owner': owner})
        for n in ambiguous:
            BLIND.append('%s/%s: %s. It is EXCLUDED from allocation -- neither '
                         'classified as a project nor confirmed as '
                         'infrastructure. An operator decides.'
                         % (h['node'], n, groups[n]['by']))

    # Pass two: allocate, in TWO sweeps over the whole fleet rather than one
    # sweep per host. Sweep A seats every incumbent everywhere; only then does
    # sweep B hand a free block to anyone. Doing it host by host gave
    # flarevault -- an incumbent nowhere -- babyhelp's occupied block before
    # babyhelp's host had even been read.
    reserved = {}
    live = [p for p in per if p['host']['reached']]
    if not per_host:
        for p in live:
            _, taken = _propose(p['projects'], p['occupied'], p['owner'],
                                dict(reserved), seat_only=True)
            reserved.update(taken)

    refs = {p['host']['ref'] for p in live if p['host']['ref'] not in ('?', '')}
    if len(refs) > 1:
        BLIND.append('the fleet has DIVERGED — the reached hosts run %s. A '
                     'packet written here states one band; whether a given node '
                     'SERVES it depends on the build that node is on, and these '
                     'are not the same build. Do not assume one ref across the '
                     'fleet.' % ', '.join(sorted(refs)))

    rows = []
    for p in live:
        h = p['host']
        # Listeners nothing on the host claims. The allocator already refuses
        # to place anything on top of them, so this is not a correctness hole
        # -- it is an honesty one: the report is about to name every port by
        # its owner, and these have no owner to name. A port held by something
        # unidentified is exactly the thing that makes a "free" block wrong.
        stray = sorted(x for x in h['listening']
                       if p['owner'].get(x, '').startswith('a listener'))
        if stray:
            BLIND.append('%s: %d listening port(s) belong to no container and '
                         'no service this tool can name -- %s. They are treated '
                         'as occupied, so no block is offered on top of them, '
                         'but what holds them is unknown.'
                         % (h['node'], len(stray),
                            ', '.join(str(x) for x in stray)))
        seed = {} if per_host else dict(reserved)
        proposals, taken = _propose(p['projects'], p['occupied'], p['owner'],
                                    seed, seat_only=False)
        if not per_host:
            reserved.update(taken)
        for n in sorted(p['projects']):
            g = p['projects'][n]
            pr = proposals[n]
            mapping, notes = _map_ports(g, pr['block'], p['occupied'], p['owner'])
            if not h['ss_read']:
                notes.append('PROVISIONAL: `ss` could not be read on this host, '
                             'so non-docker listeners were invisible to the '
                             'allocator.')
            if not g['configs']:
                # No compose label means no file to point a human at. The
                # commands degrade to a placeholder, and a placeholder inside a
                # block labelled "the exact commands" is the worst shape this
                # report can take -- so it is registered as a hole rather than
                # printed as a step.
                BLIND.append('%s/%s: no `com.docker.compose.project.config_files` '
                             'label, so THERE IS NO COMPOSE FILE TO NAME. Its '
                             '`fix` commands cannot say which file to edit, and '
                             'a container started outside compose may not be '
                             'reproducible from anything on disk. This is a '
                             'finding in its own right.' % (h['node'], n))
                notes.append('no compose file on the host — the `fix` commands '
                             'are incomplete by construction, not by oversight')
            diffs = _diffs(g, g['kind'], pr, mapping, h)
            rows.append({
                'project': n, 'host': h['node'], 'target': h['target'],
                'kind': g['kind'], 'by': g['by'], 'channels': g['channels'],
                'containers': len(g['containers']), 'labelled': g['labelled'],
                'configs': g['configs'], 'stopped': g['stopped'],
                'ports': sorted(g['ports']),
                'verdicts': {str(x): _verdict(x)[0] for x in sorted(g['ports'])},
                'proposal': pr, 'mapping': {str(k): v for k, v in sorted(mapping.items())},
                'notes': notes, 'diffs': diffs,
                'commands': _commands(g, pr, mapping, h),
                'provisional': not h['ss_read'],
            })
    return {'hosts': per, 'projects': rows, 'per_host': per_host, 'local': False}


# 20404941  render — the report, and the hole in it named last
def render(s, argv):
    w = sys.stdout.write
    w('\n  PORT MIGRATION — every project, where it is, where it could go\n')
    w('  band %s  (kernel/control.served_band, one formatter)\n' % SERVED)
    w('  scope: %s\n' % ('per-host blocks (--per-host)' if s['per_host']
                         else 'fleet-wide blocks — a block number means one thing on both boxes'))
    w('  %s\n' % ('-' * 74))

    w('\n  0. A PROMISE THE LIVE ALLOCATOR CANNOT KEEP\n')
    w('  %s\n' % ('-' * 74))
    w('     hub/plan/STATE.md:125 states, of this band:\n')
    w('       "ALLOCATION fleet-wide — a band is unique across BOTH servers,\n')
    w('        so a project can move machines without renumbering."\n\n')
    w('     handlers/node.py::_free_band reads ONE host\'s bound ports. Checked\n')
    w('     directly, not inferred:\n')
    w('       _free_band([])        -> [12000, 12099]\n')
    w('       _free_band([12080])   -> [12100, 12199]\n')
    w('     It is correct locally and blind fleet-wide. babyhelp holds 12080 on\n')
    w('     ksgcohub, so fks-services — which has nothing in that range — would\n')
    w('     hand 12000-12099 to the next project that asked, and the stated\n')
    w('     reason for the whole scheme fails silently.\n\n')
    w('     THIS TOOL ALLOCATES FLEET-WIDE and that is why babyhelp keeps\n')
    w('     12000-12099 in the table below. It can, because it runs on the\n')
    w('     operator\'s machine and reads both boxes. /api/admit CANNOT: it runs\n')
    w('     ON a node, and the two nodes are on different tailnets and cannot\n')
    w('     reach each other. So this is not a bug to patch in _free_band — it\n')
    w('     is a capability the node does not have. Either the fleet fact\n')
    w('     crosses via the zone or the heartbeat, or the promise is withdrawn.\n')
    w('     It must not be left standing with nothing behind it.\n')
    w('     (Reported, not repaired. Changing STATE.md is not this tool\'s job\n')
    w('      and editing it was outside this task\'s scope.)\n')

    w('\n  A. HOW SERVICES WERE SEPARATED FROM PROJECTS\n')
    w('  %s\n' % ('-' * 74))
    w('     No document states this distinction, so it is derived — from ONE\n')
    w('     authoritative test and two honest outcomes:\n\n')
    w('       S1 roster      the name is in kernel/collect.py SERVICES, the\n')
    w('                      hub\'s own list of what the server kit installs.\n')
    w('                      -> SERVICE.\n')
    w('       no host port   the band governs published ports; there is\n')
    w('                      nothing to migrate.  -> NOT GOVERNED.\n')
    w('       anything else  publishing a host port while off the roster is\n')
    w('                      what a project IS.  -> PROJECT.\n\n')
    w('     Deliberately NOT tests: living at %s/<name>/ (that is\n' % DOCKER_ROOT)
    w('     what /api/admit tells PROJECTS to do) and sitting in a named\n')
    w('     PORT_LANE (being in the Supabase lane is the deviation, not a\n')
    w('     credential). Scoring those two as service evidence classified\n')
    w('     fksinv as infrastructure and removed it from this table.\n')
    w('     Flagged AMBIGUOUS and excluded: a group off the roster whose every\n')
    w('     port already has a service name — infrastructure the roster\n')
    w('     forgot. Proposing to move one of those is the expensive mistake.\n\n')
    for p in s['hosts']:
        h = p['host']
        if not h['reached']:
            w('     %-14s NOT REACHED — %s\n' % (h['node'], h['error']))
            continue
        w('     %s (%s)  hub ref %s\n'
          % (h['node'], h['hostname'] or '?', h['ref']))
        for n in sorted(p['groups']):
            g = p['groups'][n]
            mark = 'PROJECT' if n in p['projects'] else (
                'AMBIGUOUS' if n in p['ambiguous'] else 'service')
            w('       %-9s %-16s %-24s ports: %s\n'
              % (mark, n, g['by'], ', '.join(str(x) for x in sorted(g['ports'])) or '—'))
        w('\n')

    w('\n  B. THE MIGRATION TABLE\n')
    w('  %s\n' % ('-' * 74))
    if not s['projects']:
        w('     nothing to place — no host produced a project.\n')
    w('     %-12s %-12s %-5s %-13s %s\n'
      % ('project', 'host', 'n', 'proposed', 'current ports'))
    for r in s['projects']:
        b = r['proposal'].get('block')
        w('     %-12s %-12s %-5d %-13s %s\n'
          % (r['project'], r['host'], len(r['ports']),
             '%d-%d' % tuple(b) if b else 'NONE',
             ', '.join(str(x) for x in r['ports']) or 'none'))
        vs = {}
        for port, v in r['verdicts'].items():
            vs.setdefault(v, []).append(port)
        for v in sorted(vs):
            w('       %-14s %s\n' % (v, ', '.join(vs[v])))
        w('       %s\n' % r['proposal']['note'])
        moves = [(o, n) for o, n in sorted((int(k), v)
                                           for k, v in r['mapping'].items())
                 if o != n]
        if moves:
            w('       rebinds     %s\n'
              % ', '.join('%d->%d' % m for m in moves[:6]))
            for i in range(6, len(moves), 6):
                w('                   %s\n'
                  % ', '.join('%d->%d' % m for m in moves[i:i + 6]))
        elif r['mapping']:
            w('       rebinds     none — already inside the proposed block\n')
        if r['provisional']:
            w('       PROVISIONAL — ss unread on this host\n')
        for n in r['notes']:
            w('       ! %s\n' % n)
        w('\n')

    w('\n  C. DIFFERENCES — record_diffs() shape, dispositions NOT ours\n')
    w('  %s\n' % ('-' * 74))
    for r in s['projects']:
        w('     %s @ %s — %d difference(s)\n'
          % (r['project'], r['host'], len(r['diffs'])))
        for d in r['diffs']:
            w('       claimed: %s\n' % d['claimed'])
            w('       machine: %s\n' % d['machine'])
            w('       why:     %s\n' % _wrap(d['why'], 62))
            w('\n')

    w('\n  D. WHAT I COULD NOT SEE\n')
    w('  %s\n' % ('-' * 74))
    if not BLIND:
        w('     Nothing was skipped and every host answered every section.\n')
        w('     That is a statement about this run only.\n')
    for b in BLIND:
        w('     - %s\n' % _wrap(b, 66))
    w('\n     Everything above is true only of what answered. A clean table\n')
    w('     with a hole in it is more dangerous than a failure.\n\n')
    return 0


def _wrap(text, width, indent=' ' * 16):
    words, line, out = text.split(), '', []
    for word in words:
        if len(line) + len(word) + 1 > width:
            out.append(line)
            line = word
        else:
            line = (line + ' ' + word).strip()
    out.append(line)
    return ('\n' + indent).join(out)


# 20404942  main
def main(argv):
    if not _require_band():
        return 2
    s = survey(argv)
    if '--write' in argv and not s['local']:
        packets = {}
        for p in s['hosts']:
            h = p['host']
            for n in sorted(p['projects']):
                r = next((x for x in s['projects']
                          if x['project'] == n and x['host'] == h['node']), None)
                if not r:
                    continue
                g = p['projects'][n]
                packets[n] = _packet(
                    g, r['kind'], h, r['proposal'],
                    {int(k): v for k, v in r['mapping'].items()},
                    r['diffs'], r['commands'], r['notes'])
        written, refused = _write_packets(packets)
        for f in written:
            print('  wrote %s' % f)
        for f in refused:
            print('  REFUSED %s' % f)
            BLIND.append('packet for %s was not written' % f)
    if '--json' in argv:
        print(json.dumps({'band': [BAND_FLOOR, BAND_CEIL, BAND_SIZE],
                          'per_host': s['per_host'],
                          'projects': s['projects'],
                          'blind': BLIND}, indent=2, default=str))
        return 0
    return render(s, argv)


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
