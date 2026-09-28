#!/usr/bin/env python3
"""
# 20404719  tools.edges — every external joint, what it needs, and what breaks

    python3 hub/tools/edges.py                 # everything
    python3 hub/tools/edges.py --inventory     # just the joints
    python3 hub/tools/edges.py --pairs         # just the paired flows + invariant
    python3 hub/tools/edges.py --seams         # just the FlareVault placeholders
    python3 hub/tools/edges.py --local         # no ssh (source only)

THE PROBLEM THIS EXISTS FOR. There were three partial maps of this system and
no cut sheet. Telescope codes address every internal function uniquely.
/api/sitemap derives the route surface. docs/flareshub-frontend-dag.md draws
seven mermaid DAGs. Between them they answer "what is inside" three times over
and "what is this attached to" not once — so "this piece connects to that
piece" was answerable only by reading all the code, and consequently it was
answered from memory. The failures that came out of that were all the same
shape:

  - A DNS record, an Access app and a running tunnel existed for
    fks-services while the box itself had no ~/.flare/node.json. The hostname
    answered, so the node was called enrolled; the node had no idea. Nothing
    looked at the joint from both ends.
  - Two boxes run cloudflared two different ways (a root system unit vs a user
    unit with a hand-placed binary). One installer was credited with both.
  - ntfy answers on 8085 on one box and 7001 on the other, and the code's
    default is 8085 — so one of them works because the default happened to
    match and nobody wrote that down either way.

WHAT AN EDGE IS, here. Anything OUTSIDE this codebase that the system reaches
for or that reaches in: an API, a daemon, a unix socket, a CLI binary, a file
on disk that another program writes, a systemd unit, a hostname. Not internal
modules — kernel/router.py addresses those already, and doing it twice is how
the route count came to be wrong in three documents at once.

HOW IT AVOIDS BECOMING ANOTHER STALE LIST. Two passes that check each other:

    DERIVED     every outbound URL, unix socket, invoked binary, credential-
                shaped environment name and credential file path found in the
                source, right now, by pattern. This half needs no maintenance
                and finds joints nobody described.
    DESCRIBED   the judgements a pattern cannot make: which credential, which
                direction, what concretely breaks. Each described edge carries
                the patterns that tie it back to the derived pass.

Then BOTH mismatches are reported, because either one alone is a lie:
    a derived hit no description claims  ->  UNDESCRIBED EDGE
    a description with no derived hit    ->  DESCRIBED BUT NOT IN THE CODE

LAW V — NO SECRET REACHES THIS OUTPUT. Every credential is reported as a
SOURCE: an environment variable NAME, or a file PATH and its mode. No file
holding a credential is opened by this tool, anywhere, including over ssh. The
server probe uses `test`, `stat -c %a` and `command -v` and nothing that can
print a value. There is no code path here that holds a secret, so there is no
leak to prevent later.

LAW IV — REPORT, NEVER REPAIR. This writes nothing on any machine. Its only
outbound calls are ssh with a fixed read-only command string. It makes no
Cloudflare call at all — not even GET — because naming the joints must not
need the credential that uses them; situation.py already reads the Access
apps, and asking twice buys nothing.

WHAT THIS IS NOT. It is not an exposure report: it says a joint EXISTS and what
depends on it, never whether it is safely configured. tools/situation.py owns
that question and answers it properly, from both sides. Do not read a clean
page here as "the edges are fine" — read it as "these are the edges".

  IT CANNOT SEE INSIDE CLOUDFLARE. Whether an Access app has the policy it
  should, whether a tunnel's ingress points where the DNS record says — that
  needs the API and it is situation.py's and tools/tracks.py's job.

  A PRESENT BINARY IS NOT A WORKING EDGE. `command -v tailscale` says the tool
  is installed. It does not say the daemon has a route, which is a fault this
  project has already mistaken for a dead server once.

  IT ONLY PROBES THE TWO NODES NAMED IN CLAUDE.MD. Fleet membership being a
  document is itself a finding and atlas.py already reports it; this tool
  inherits the same limit rather than inventing a third node list.
"""
import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
LOCAL = '--local' in sys.argv
BLIND = []

# Everything scanned. Deliberately includes the installers and the unit files:
# an edge that only exists because bootstrap.sh installs it is still an edge,
# and the unit files are where two of them are actually declared.
SCAN_EXT = ('.py', '.sh', '.service', '.timer', '.conf')
SCAN_SKIP = ('__pycache__', '.git', 'node_modules', 'docs-site', 'ui-next',
             'server-kit', '.netlify')

# THIS FILE IS EXCLUDED FROM ITS OWN DERIVATION. It names every edge by
# construction -- every `detect` pattern appears in it literally -- so counting
# itself would add a site to all 15 edges and make the busiest joint look like
# whichever one this docstring talks about most. A tool describing a joint is
# not the system touching it.
SELF = 'hub/tools/edges.py'


# 20404301  _read — one file, or '' and a blind spot rather than a crash
def _read(abs_path):
    try:
        with open(abs_path, encoding='utf-8', errors='ignore') as f:
            return f.read()
    except Exception:
        BLIND.append('could not read %s' % os.path.relpath(abs_path, ROOT))
        return ''


# 20404302  _sources — every file this tool considers part of the system
def _sources():
    """Relative paths, sorted, so two runs on the same checkout agree."""
    out = []
    for base, dirs, files in os.walk(ROOT):
        dirs[:] = [d for d in dirs if d not in SCAN_SKIP]
        for f in files:
            if f.endswith(SCAN_EXT):
                rel = os.path.relpath(os.path.join(base, f), ROOT).replace('\\', '/')
                if rel != SELF:
                    out.append(rel)
    return sorted(out)


_CACHE = {}


# 20404303  _lines — a file as (lineno, text) pairs, read once per run
def _lines(rel):
    if rel not in _CACHE:
        _CACHE[rel] = _read(os.path.join(ROOT, rel)).splitlines()
    return list(enumerate(_CACHE[rel], 1))


# 20404304  _code_at — the telescope code of the function a line sits inside
def _code_at(rel, lineno):
    """Walks BACKWARDS for the nearest `# NNNNNNNN` marker, which is how this
    repo addresses functions. Returns '' when there is none above the line —
    shell files and module-level constants have no owning function, and
    inventing one would be worse than saying nothing.
    """
    best = ''
    for n, text in _lines(rel):
        if n > lineno:
            break
        m = re.match(r'\s*#\s+(\d{8})\b', text)
        if m:
            best = m.group(1)
    return best


# 20404305  _hits — every line in the system matching a pattern, with its code
def _hits(pattern, files=None):
    """Returns [(rel, lineno, telescope_code, stripped_line)].

    The single derivation everything else here is built on. One compiled
    pattern over the whole tree; no per-edge file lists to keep in step with a
    repo that moves files, because a hardcoded file list is the thing that
    rots.
    """
    rx = re.compile(pattern)
    out = []
    for rel in (files if files is not None else _sources()):
        for n, text in _lines(rel):
            if rx.search(text):
                out.append((rel, n, _code_at(rel, n), text.strip()[:96]))
    return out


# 20404306  _sh — run, never raise. A probe that dies is a blind spot.
def _sh(cmd, timeout=45):
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return p.returncode == 0, (p.stdout or '').strip()
    except Exception as e:
        return False, str(e)[:90]


# ─────────────────────────────────────────────────────────────────────────────
# THE DESCRIBED EDGES
#
# `detect` is the ONLY thing tying an entry to reality, and it is deliberately
# the narrowest pattern that still finds every site: too broad and the
# UNDESCRIBED pass goes quiet and stops earning its place.
#
# `cred` names SOURCES. An environment variable NAME or a file PATH. There is
# no field in this structure that could hold a value.
#
# `breaks` names an endpoint or a view, never an adjective. "degraded" is the
# word that let /api/mesh/registry answer 404 on both servers for a week.
#
# `probe` is the key the server probe reports for this edge, or None when
# presence is not a thing a box can be asked (an API is not installed).
# ─────────────────────────────────────────────────────────────────────────────
EDGES = [
    {
        'id': 'cf-api', 'name': 'Cloudflare API',
        'what': 'zone + DNS records, cfd_tunnel, Access apps and policies. '
                'The zone IS the fleet register: kernel.fleet.discover '
                'enumerates every node from its flareshub-* records, so this '
                'is not a convenience, it is where membership lives.',
        'reach': 'https://api.cloudflare.com/client/v4  (HTTPS out, 443)',
        'cred': ['$CF_API_TOKEN',
                 '~/.cf-token  (file, expected mode 600)',
                 '/etc/flare/token  (file)'],
        'direction': 'OUT only. Nothing at Cloudflare calls this API back.',
        'pair': None,
        'breaks': [
            'GET /api/mesh/fleet — the fleet collapses to this box plus '
            'whatever has beaten in; the register cannot be read',
            'the topography console / lobby server list shows no unbeaten node',
            'enroll.sh cannot run at all (it verifies the token first, line 155)',
            'tools/cf-check.py, tools/fix-entry.py and situation.py group C '
            'all report unknown, not empty',
        ],
        'detect': [r'api\.cloudflare\.com', r'CF_API_TOKEN', r'\bcf_api\b'],
        'probe': 'CFTOKEN',
    },
    {
        'id': 'cloudflared', 'name': 'cloudflared (the tunnel daemon)',
        'what': 'the only inbound path from the internet. A HOST service on '
                'purpose, never a container: a container that dies takes the '
                'way in to fix it with it.',
        'reach': 'a systemd unit running `cloudflared tunnel run '
                 '--token-file <path>`; the .deb comes from GitHub releases',
        'cred': ['/etc/cloudflared/token  (root-owned, system unit)',
                 '~/.cloudflared/token  (user unit)',
                 'minted by enroll.sh from GET /accounts/<id>/cfd_tunnel/<id>/token'],
        'direction': 'OUT to build the tunnel, then INBOUND rides it. The '
                     'origin never accepts a connection from the internet.',
        'pair': 'the CNAME <tunnel-id>.cfargotunnel.com written by enroll.sh',
        'breaks': [
            'every https://flareshub-<id>.<zone> request — the edge answers '
            '1033 / 502 instead of reaching the hub',
            'the lobby drill-in /s/<id>/ for that node',
            'a node heartbeat over the `cloudflare` path (falls back to '
            'tailscale, silently, which kernel.heartbeat reports)',
        ],
        'detect': [r'cloudflared', r'cfargotunnel'],
        'probe': 'CFD',
    },
    {
        'id': 'cf-access', 'name': 'Cloudflare Access (human door)',
        'what': 'Google as the identity provider, in front of the apex. '
                'cloudflared forwards the verified email to the origin.',
        'reach': 'header Cf-Access-Authenticated-User-Email, believed ONLY '
                 'from $HUB_CF_TRUST_IP — the path is the proof, not the header',
        'cred': ['$HUB_CF_TRUST_IP  (which source address may assert it)',
                 '$HUB_CF_EMAILS  (allow-list, empty = any Access accepted)',
                 '$HUB_CF_ROLE'],
        'direction': 'IN. Cloudflare asserts an identity to this hub.',
        'pair': 'GET /api/door, which turns that session into a role JWT',
        'breaks': [
            'GET /api/door returns 401 no_session for an internet visitor, so '
            'GET /api/lobby refuses and the fleet page is empty',
            'anyone arriving through the tunnel is anonymous and app.html '
            'shows its own login box — the second login the chain exists to end',
        ],
        'detect': [r'Cf-Access-Authenticated-User-Email', r'HUB_CF_TRUST_IP',
                   r'HUB_CF_EMAILS'],
        'probe': 'TRUSTIP',
    },
    {
        'id': 'cf-svctoken', 'name': 'Cloudflare Access service token',
        'what': 'how the lobby reaches a node. Node hostnames publish an '
                'Access policy of any_valid_service_token with no identity '
                'provider in it, so they refuse humans outright.',
        'reach': 'headers CF-Access-Client-Id / CF-Access-Client-Secret on one '
                 'outbound https call to flareshub-<label>.<zone>',
        'cred': ['~/.flare/svctoken.json  (mode 600, REFUSED if widened)',
                 '~/.flare/.svctoken-salt  (mode 600)',
                 '$HUB_SVCTOKEN_FILE  (override for the path)',
                 'the inbound half: $HUB_CF_CLIENTS names which client ids '
                 'may act as the lobby'],
        'direction': 'BOTH, and it is the same token seen from two ends. '
                     'OUT: kernel.svctoken.headers_for -> a node. '
                     'IN: kernel.auth.service_identity reads common_name out '
                     'of Cf-Access-Jwt-Assertion and grants a cf-service '
                     'session.',
        'pair': 'kernel.svctoken.headers_for  <->  kernel.auth.service_identity',
        'breaks': [
            'GET /api/lobby/server/<id> — every remote row reports it cannot '
            'call that node (headers_for returns {} and {} means DO NOT CALL)',
            'the drill-in /s/<id>/ proxy for every node but this one',
            'a node beat over the cloudflare path — Access refuses it',
        ],
        'detect': [r'CF-Access-Client-Id', r'Cf-Access-Jwt-Assertion',
                   r'common_name', r'svctoken', r'HUB_SVCTOKEN_FILE',
                   r'HUB_CF_CLIENTS'],
        'probe': 'SVCTOKEN',
    },
    {
        'id': 'zone-dns', 'name': 'the zone (flarevault.dev) as the register',
        'what': 'every flareshub-<label> record in the zone IS the fleet '
                'roster. Not a cache of one — the roster. No box has to be up '
                'for the fleet to be visible.',
        'reach': 'the zone name on THIS box: ~/.flare/node.json "zone", or '
                 '$FLARE_ZONE / $HUB_ZONE. Read via the Cloudflare API.',
        'cred': ['(none of its own — it borrows cf-api\'s token)'],
        'direction': 'OUT (read). Written only by enroll.sh, at enrolment.',
        'pair': 'enroll.sh writes the record; kernel.fleet.discover reads it',
        'breaks': [
            'kernel.fleet.discover returns no nodes and a `why` saying this '
            'box cannot name the register, so GET /api/mesh/fleet shows only '
            'rows that have beaten in',
            'kernel.svctoken.node_url returns \'\' for every id, which takes '
            'the whole lobby drill-in with it',
        ],
        'detect': [r'FLARE_ZONE', r'HUB_ZONE', r'flareshub-', r'def zone\('],
        'probe': 'ZONE',
    },
    {
        'id': 'tailscale', 'name': 'Tailscale',
        'what': 'the failsafe path. The one that is supposed to still work '
                'when Cloudflare does not, and the transport this operator '
                'administers both boxes over.',
        'reach': 'the `tailscale` binary (status, ip -4) and 100.x addresses',
        'cred': ['(node key held by tailscaled, outside this repo entirely)'],
        'direction': 'BOTH. Out for a heartbeat fallback and for ssh; in for '
                     'the hub port 8765 on the tailnet address.',
        'pair': 'kernel.heartbeat target `central_tailscale`  <->  the '
                'receiver POST /api/heartbeat',
        'breaks': [
            'the heartbeat fallback chain loses leg 2, leaving cloudflare and '
            'LAN only',
            'the Tailscale-only failsafe console — the way back in when a '
            'Cloudflare token has expired — has no transport',
            'tailscale_ip disappears from GET /api/node and GET /api/identity',
        ],
        'detect': [r'tailscale', r'\btailnet\b', r'100\.\d+\.\d+\.\d+'],
        'probe': 'TS',
    },
    {
        'id': 'github', 'name': 'GitHub (KGSHOPINV/claude-server)',
        'what': 'where the installer comes from and where the code comes '
                'from. A fresh box has nothing until it clones this.',
        'reach': 'https://raw.githubusercontent.com/... for the one-liner, '
                 'https://github.com/KGSHOPINV/claude-server for the clone, '
                 'and github.com/cloudflare/cloudflared/releases for the .deb',
        'cred': ['(none — public clone over https)'],
        'direction': 'OUT only.',
        'pair': None,
        'breaks': [
            'bootstrap.sh cannot clone, so a new node cannot be installed',
            'enroll.sh cannot fetch cloudflared, so a new node gets no tunnel '
            'and therefore no public hostname',
            'the build ref reported by every tool (git rev-parse) still works '
            'from the existing checkout — this is an install-time edge, not a '
            'runtime one',
        ],
        'detect': [r'github\.com', r'raw\.githubusercontent\.com'],
        'probe': 'GIT',
    },
    {
        'id': 'ntfy', 'name': 'ntfy',
        'what': 'the only push notification path off these boxes. It runs as '
                'a container here, which makes it an edge and not a feature: '
                'the hub talks to it over HTTP like any stranger.',
        'reach': '$HUB_NTFY_URL/$HUB_NTFY_TOPIC, default '
                 'http://localhost:8085/server-alerts — and ~/.server-alerts.conf '
                 'OVERRIDES the environment, which is the wrong way round and '
                 'is why one box works by coincidence. tools/enable-ntfy.sh:91 '
                 'also names a PUBLIC instance, https://ntfy.ksgco.app, which '
                 'is a second and quite different edge: the phone subscribes '
                 'to that one, not to the container.',
        'cred': ['~/.server-alerts.conf  (NTFY_TOKEN=, mode 600)',
                 '$HUB_NTFY_URL / $HUB_NTFY_TOPIC  (addresses, not secrets)'],
        'direction': 'OUT only. ntfy never calls the hub.',
        'pair': None,
        'breaks': [
            'container-died and container-started alerts stop leaving the box',
            'hub-alert.timer and hub-daily.timer run and deliver nothing',
            'GET /api/node reports attention.notifications.healthy=false — '
            'the one failure this project treats as worse than none, because '
            'silence reads as coverage',
        ],
        'detect': [r'ntfy', r'NTFY_', r'server-alerts\.conf'],
        'probe': 'NTFY',
    },
    {
        'id': 'host-cli', 'name': 'the host\'s own command-line tools',
        'what': 'the substrate under "derive, don\'t maintain". Nearly every '
                'fact this hub reports is a shell-out: ss for ports, df for '
                'disks, ip and hostname for addresses, nproc, uptime, git for '
                'the build ref, curl for reachability. They are invisible '
                'until one is missing on a minimal image, and then the hub '
                'reports an empty collection rather than an error.',
        'reach': 'subprocess / kernel.ssh.ssh_run. ss and df have no stdlib '
                 'substitute in use here; curl is shelled even though '
                 'urllib is already imported two files away.',
        'cred': ['(none — but `sudo` appears at tools/fix-entry.py:86, which '
                 'means one instrument needs a privilege the rest do not)'],
        'direction': 'OUT (local exec).',
        'pair': None,
        'breaks': [
            'no `ss`: _ports_in_use returns [], so GET /api/admit hands out '
            'the FIRST block in kernel.collect.PROJECT_BAND_FLOOR..CEIL '
            'regardless of what is bound — the project binds on top of '
            'whatever is already there. Live today: babyhelp holds 12080, '
            'inside the first block of the current band',
            'no `df`: GET /api/storage and the storage findings inside '
            'GET /api/node go blank, which reads as a healthy disk',
            'no `git`: every tool\'s build ref reads NONE, so the congruence '
            'check in GET /api/mesh/registry reports unknown for every node',
        ],
        'detect': [r"subprocess\.(?:run|Popen|check_output)\(\s*\[?\s*['\"](?:ss|df|ip|hostname|nproc|uptime|git|sudo|curl)\b",
                   r"ssh_run\(\s*['\"](?:ss|df|ip|hostname|nproc|uptime|curl)\b",
                   r"\bss -tln\b", r'\bnproc\b', r"df --output"],
        'probe': 'CLI',
    },
    {
        'id': 'docker-install', 'name': 'get.docker.com (install-time only)',
        'what': 'bootstrap.sh installs Docker by piping a remote script into '
                'a shell. That is a supply-chain joint and it is the only one '
                'in the repo: everything else fetched from the internet is '
                'either a git clone of this repo or a signed .deb.',
        'reach': 'https://get.docker.com  — bootstrap.sh:651',
        'cred': ['(none)'],
        'direction': 'OUT, once, at install.',
        'pair': None,
        'breaks': [
            'a fresh box gets no Docker, so bootstrap.sh finishes and every '
            'Docker-derived endpoint answers empty on a machine that looks '
            'installed',
        ],
        'detect': [r'get\.docker\.com'],
        'probe': 'DOCKER',
    },
    {
        'id': 'docker', 'name': 'Docker',
        'what': 'what the hub is mostly FOR. Reached as a CLI through '
                'kernel.ssh.ssh_run, and as an event stream for the watcher '
                'thread. The socket is named only to be EXCLUDED from backup '
                'and from what counts as project data.',
        'reach': 'the `docker` binary via bash -c (HUB_LOCAL=1) or ssh; '
                 '/var/run/docker.sock named in registry.py:250 and '
                 'backup.sh:239 as a thing to skip',
        'cred': ['(unix group membership — outside this repo)'],
        'direction': 'OUT only (the hub asks docker; docker never calls in). '
                     'The event stream is a long-lived OUT read.',
        'pair': None,
        'breaks': [
            'GET /api/containers, /api/services, /api/docker/* and '
            '/api/status all answer with empty collections',
            'GET /api/node reports projects: [] — indistinguishable from a '
            'box that genuinely runs nothing',
            'GET /api/admit still answers, but ports_in_use comes from `ss` '
            'and the name-collision check goes blind',
            'kernel.log._docker_event_loop stops, so nothing is logged or '
            'pushed when a container dies',
        ],
        # subprocess AND ssh_run both reach it. Only matching ssh_run left
        # four real sites in handlers/status.py showing as undescribed.
        'detect': [r'docker\.sock', r"ssh_run\('docker", r'docker ps',
                   r'docker events',
                   r"subprocess\.(?:run|Popen|check_output)\(\s*\[?\s*['\"]docker"],
        'probe': 'DOCKER',
    },
    {
        'id': 'systemd', 'name': 'systemd (user units, and one system unit)',
        'what': 'what keeps the hub, the backup, the reclaim and the alert '
                'timers running. The hub itself is a USER unit; cloudflared '
                'is a system unit on one box and a user unit on the other, '
                'which is a divergence, not a preference.',
        'reach': '`systemctl --user` for hub.service and the timers; '
                 '`systemctl` for cloudflared on the box that has it there',
        'cred': ['(none — but a user unit needs loginctl enable-linger to '
                 'survive logout, which is the failure that looks like a crash)'],
        'direction': 'OUT (the tools ask it). systemd starts the hub, which is '
                     'the one sense in which it calls in.',
        'pair': None,
        'breaks': [
            'the hub does not start on boot, so every endpoint on :8765 is '
            'refused and every tool reports the node unreachable',
            'hub-backup.timer stops and nothing says so until a disk dies',
        ],
        'detect': [r'systemctl', r'\.service\b', r'\.timer\b'],
        'probe': 'UNITS',
    },
    {
        'id': 'sqlite', 'name': 'SQLite files',
        'what': 'four separate files on purpose. server.db is re-derivable '
                'from the machine; control.db is NOT — it holds what no '
                'machine can be asked. bank.db is its own file so that '
                'anything copying a database does not copy the secrets.',
        'reach': 'db/server.db, db/control.db, db/bank.db, plus db/fleet.json '
                 'and db/changewatch.json as flat state. $HUB_DB, '
                 '$HUB_BANK_DB, $HUB_FLEET_STATE override the paths.',
        'cred': ['db/.bank-salt  (mode 600, the bank\'s key half)'],
        'direction': 'local file I/O. Neither in nor out.',
        'pair': 'kernel.control writes control.db; tools/backup.sh copies it',
        'breaks': [
            'control.db unreadable: GET /api/registry, /api/bulletins/<p>, '
            '/api/tickets and the whole exchange fail, and mesh._self_entry '
            'reports the error instead of a blank row',
            'server.db unreadable: sessions, activity log and hub_config go, '
            'so every gated route refuses',
            'bank.db absent is NORMAL — an empty bank is the desired state',
        ],
        'detect': [r'sqlite3', r'\.db[\'"]', r'HUB_DB\b', r'HUB_BANK_DB',
                   r'HUB_FLEET_STATE'],
        'probe': 'DBS',
    },
    {
        'id': 'machine-id', 'name': '/etc/machine-id',
        'what': 'the hardware anchor under the server id. Two identifiers on '
                'purpose: server_id can be reissued, machine_id cannot, so a '
                'reimage is DETECTABLE. It is also half the key for both '
                'obfuscation-at-rest schemes.',
        'reach': 'the file /etc/machine-id, read directly',
        'cred': ['(not a credential — but it is an input to kernel.bank._key '
                 'and kernel.svctoken\'s keystream, so a box whose machine-id '
                 'changes can no longer read either store)'],
        'direction': 'local read.',
        'pair': None,
        'breaks': [
            'kernel.identity._derive_server_id returns \'\', so server_id is '
            'empty and GET /api/node, /api/admit and every heartbeat carry no '
            'id — and fleet.heartbeat rejects a beat with neither',
            'the svctoken and bank stores become undecryptable on this box',
        ],
        'detect': [r'/etc/machine-id'],
        'probe': 'MACHINEID',
    },
    {
        'id': 'ssh', 'name': 'SSH (as the hub\'s own execution transport)',
        'what': 'kernel.ssh.ssh_run is the hub\'s ONLY way to run a host '
                'command. With HUB_LOCAL=1 it degenerates to bash -c on the '
                'same box, which is how both servers actually run — so this '
                'edge is configured out of existence in production and is '
                'still the code path everything goes through.',
        'reach': '$HUB_LOCAL, $HUB_SSH_HOST, $HUB_SSH_USER, $HUB_SERVER_IP',
        'cred': ['(the invoking user\'s ssh agent / keys — outside this repo)'],
        'direction': 'OUT.',
        'pair': None,
        'breaks': [
            'every collector that shells out: /api/containers, /api/ports, '
            '/api/storage, /api/status, and _ports_in_use inside /api/admit '
            '(which then hands out a band derived from an empty port list)',
        ],
        'detect': [r'HUB_SSH_HOST', r'HUB_LOCAL', r'def ssh_run',
                   r"subprocess\.(?:run|Popen|check_output)\(\s*\[?\s*['\"]ssh['\"]"],
        'probe': 'HUBLOCAL',
    },
    {
        'id': 'ai-api', 'name': 'third-party AI APIs',
        'what': 'api.anthropic.com, api.openai.com and '
                'generativelanguage.googleapis.com, selected by the '
                'hub_config row `ai_provider`. Optional and off by default.',
        'reach': 'https POST to whichever provider is configured',
        'cred': ['$HUB_AI_KEY',
                 '~/.server-alerts.conf  (HUB_AI_KEY= or ANTHROPIC_API_KEY=, '
                 'also read by hub/scripts/alert-ai-explain.sh)',
                 '(NOT the database. handlers/ai.py refuses to store a key and '
                 'refuses to serve while a legacy `ai_api_key` row exists)'],
        'direction': 'OUT only.',
        'pair': None,
        'breaks': [
            'POST /api/ai/chat returns "No AI API key available" and names the '
            'two pointers it reads',
            'hub/scripts/alert-ai-explain.sh sends the raw alert with no '
            'explanation — the alert still goes out',
            'nothing else. This is the only edge on this page whose absence '
            'costs one feature and no structure.',
        ],
        'detect': [r'api\.anthropic\.com', r'api\.openai\.com',
                   r'generativelanguage\.googleapis\.com', r'ai_api_key',
                   r'HUB_AI_KEY'],
        'probe': 'AIKEY',
    },
    {
        'id': 'flarevault', 'name': 'FlareVault (the authority that has not arrived)',
        'what': 'the intended issuer of identity, the owner of the Access '
                'policy on the single human door, and the broker for '
                'node-to-node calls. NOT REACHED BY ANY CODE PATH TODAY: '
                'there is no client, no base URL, no call. What exists is '
                'SEAMS — places standing in for it that say so.',
        'reach': 'nothing. login.flarevault.dev does not resolve; '
                 'handlers/door.py points at the apex instead and says why.',
        'cred': ['(it will MINT them: server.identity.json jwt_secret, '
                 'jwt_issuer=flarevault, and the join tokens mesh has no '
                 'authentication without)'],
        'direction': 'intended: DOWN (authority) paired with UP (attestation '
                     'via GET /api/node). Today only the UP leg exists.',
        'pair': 'GET /api/node is the attestation half, and it is built',
        'breaks': [
            'nothing breaks by its absence — everything it would own is '
            'stood in for. What breaks is the OPPOSITE: each stand-in has to '
            'be removed when it arrives, and see the seam list for what '
            'specifically changes.',
        ],
        'detect': [r'FlareVault', r'FlarVault', r'flarevault'],
        'probe': None,
    },
]

# The credential stores that announce themselves, and the one that does not.
# This is here rather than in a document because "a temporary exception that
# stops complaining has become architecture" (kernel/bank.py), and a document
# is exactly how it stops complaining.
LAW_V = [
    ('kernel/bank.py', 'ANNOUNCED',
     'read-once on project scope, 24h TTL, and exception_open() FAILS '
     'install-preflight --strict while anything is held. Deletable the day '
     'FlareVault can do the handoff.'),
    ('kernel/svctoken.py', 'ANNOUNCED',
     'long-lived by design, mode 0600 enforced on read, never logged, held '
     'only inside _Secret whose __repr__ redacts. Deletable the day '
     'FlareVault brokers node calls.'),
    ('handlers/ai.py', 'CLOSED, NOT ANNOUNCED',
     'it used to write the provider key into hub_config in server.db in '
     'plaintext, and tools/backup.sh copies server.db by name, so the key '
     'would have been duplicated into every backup set with no TTL and '
     'nothing failing while it was set; the Gemini branch also put it in a '
     'URL query string. Latent, never live: 0 rows on both boxes. This one '
     'is CLOSED rather than announced, because unlike a service token the AI '
     'key already had a pointer source. POST /api/ai/config refuses an '
     'api_key, _ai_key reads $HUB_AI_KEY then ~/.server-alerts.conf, Gemini '
     'takes x-goog-api-key as a header, and every AI route REFUSES while a '
     'legacy row is still in the database — the bank\'s discipline applied to '
     'the residue instead of to a standing exception.'),
]


# 20404307  show_inventory — the described edges, checked against the code
def show_inventory():
    print()
    print('  EDGE INVENTORY — %d described joints, each tied to live code'
          % len(EDGES))
    print('  ' + '=' * 74)
    claimed = set()
    dead = []
    for e in EDGES:
        hits = []
        for pat in e['detect']:
            for h in _hits(pat):
                hits.append(h)
                claimed.add((h[0], h[1]))
        # Deduplicated and ordered so the same checkout prints the same page.
        seen, uniq = set(), []
        for h in sorted(hits):
            if (h[0], h[1]) not in seen:
                seen.add((h[0], h[1]))
                uniq.append(h)
        files = sorted({h[0] for h in uniq})
        codes = sorted({h[2] for h in uniq if h[2]})
        print()
        print('  %-14s %s' % (e['id'], e['name']))
        print('     what      %s' % _wrap(e['what'], 13))
        print('     reached   %s' % _wrap(e['reach'], 13))
        print('     credential SOURCE (never a value):')
        for c in e['cred']:
            print('               %s' % _wrap(c, 14))
        print('     direction %s' % _wrap(e['direction'], 13))
        if e['pair']:
            print('     pair      %s' % _wrap(e['pair'], 13))
        print('     breaks without it:')
        for b in e['breaks']:
            print('               - %s' % _wrap(b, 16))
        if not uniq:
            print('     TOUCHES   NOTHING. Described here and not present in '
                  'the source.')
            dead.append(e['id'])
        else:
            print('     touches   %d line(s) in %d file(s)' % (len(uniq), len(files)))
            for rel in files[:8]:
                ns = [str(h[1]) for h in uniq if h[0] == rel][:6]
                print('               %s:%s' % (rel, ','.join(ns)))
            if len(files) > 8:
                print('               ... and %d more file(s)' % (len(files) - 8))
            if codes:
                print('     functions %s' % ' '.join(codes[:12])
                      + (' ...' if len(codes) > 12 else ''))
    print()
    if dead:
        print('  DESCRIBED BUT NOT IN THE CODE: %s' % ', '.join(dead))
        print('  Either the code moved or this description outlived it. Both '
              'are findings.')
    else:
        print('  Every described edge is present in the source.')
    return claimed


# 20404308  _wrap — keep a long sentence readable without truncating it
def _wrap(text, indent, width=74):
    words, lines, cur = str(text).split(), [], ''
    for w in words:
        if len(cur) + len(w) + 1 > width:
            lines.append(cur)
            cur = w
        else:
            cur = (cur + ' ' + w) if cur else w
    lines.append(cur)
    pad = '\n' + ' ' * (indent + 1)
    return pad.join(lines)


# ── THE DERIVED PASS ─────────────────────────────────────────────────────────
# Signatures of an external joint, chosen so that a NEW dependency lands here
# without anybody editing this file. That is the whole point: the described
# table above will go stale and this will not.
SIGNATURES = [
    ('outbound URL',      r"https?://(?!127\.0\.0\.1|localhost)[A-Za-z0-9%._-]{3,}"),
    ('unix socket',       r"/(?:var/)?run/[a-z0-9_.-]+\.sock"),
    ('invoked binary',    r"subprocess\.(?:run|Popen|check_output)\(\s*\[?\s*['\"]([a-z0-9_.-]+)"),
    ('shelled binary',    r"ssh_run\(\s*['\"]([a-z][a-z0-9_-]+)"),
    ('credential env',    r"environ\.get\('([A-Z_]*(?:TOKEN|SECRET|KEY|PASS|CRED)[A-Z_]*)'"),
    ('credential file',   r"(~/\.[a-z][a-z0-9_.-]*(?:token|salt|conf|json)|/etc/(?:flare|cloudflared)/[a-z]+)"),
    ('systemd unit',      r"\b(hub[a-z-]*\.(?:service|timer)|cloudflared\.service)\b"),
]


# 20404309  show_derived — every joint signature in the tree, described or not
def show_derived(claimed):
    """The half that needs no maintenance.

    A hit already claimed by a described edge is counted and dropped. What is
    left is the interesting output: a joint the source reaches for that nothing
    on this page explains.
    """
    print()
    print('  DERIVED PASS — joint signatures found in the source right now')
    print('  ' + '=' * 74)
    undescribed = {}
    for label, pat in SIGNATURES:
        hits = _hits(pat)
        rx = re.compile(pat)
        kinds = {}
        for rel, n, code, text in hits:
            m = rx.search(text)
            key = (m.group(1) if m.lastindex else m.group(0)).rstrip('\'".,);')
            kinds.setdefault(key, []).append((rel, n, code))
        print()
        print('  %-18s %d distinct, %d site(s)' % (label, len(kinds), len(hits)))
        for key in sorted(kinds):
            sites = kinds[key]
            mark = '  ' if any((r, n) in claimed for r, n, _c in sites) else '??'
            print('    %s %-52s %d site(s)  %s'
                  % (mark, key[:52], len(sites),
                     '%s:%s' % (sites[0][0], sites[0][1])))
            if mark == '??':
                undescribed.setdefault(label, []).append((key, sites))
    print()
    if undescribed:
        print('  UNDESCRIBED EDGES — found in the code, explained nowhere above')
        print('  ' + '-' * 74)
        for label in sorted(undescribed):
            for key, sites in undescribed[label]:
                print('    %-16s %s' % (label, key[:58]))
                for rel, n, code in sites[:4]:
                    print('                     %s:%s%s'
                          % (rel, n, ('  fn ' + code) if code else ''))
        print()
        print('    Each of these is either a joint nobody has described or a '
              'false positive')
        print('    in a SIGNATURES pattern. Both are worth one minute; '
              'neither is nothing.')
        print()
        print('    EXPECTED RESIDUE, so it is not mistaken for a fault here: a '
              'URL built')
        print('    from a format string (https://%s%s) has no host to name '
              'until runtime,')
        print('    so it lands here every run. What is NOT residue is a '
              'literal address --')
        print('    a hardcoded IP or hostname in an instrument only works on '
              'the one box')
        print('    it was typed on, which is the whole HAND-BUILT problem in '
              'miniature.')
    else:
        print('  Nothing undescribed. Every derived signature is claimed above.')
    return undescribed


# 20404310  show_lawv — the credential stores, and which one is silent
def show_lawv():
    print()
    print('  LAW V — "credentials are never here, pointers only", and its '
          'exceptions')
    print('  ' + '=' * 74)
    for where, state, why in LAW_V:
        print()
        print('  [%-13s] %s' % (state, where))
        print('                  %s' % _wrap(why, 17))
    print()
    print('  An announced exception is a decision. An unannounced one is a '
          'leak waiting')
    print('  for a backup to be restored somewhere else.')


# ─────────────────────────────────────────────────────────────────────────────
# THE PAIRED FLOWS
#
# Each pair is two legs pointing opposite ways. `check` is a predicate over the
# source: it returns (exists, evidence). Nothing here is asserted — a leg that
# cannot be found in the code prints ASSERTED, NOT BUILT.
# ─────────────────────────────────────────────────────────────────────────────

# 20404311  _routes — the route table, parsed from source, not imported
def _routes():
    """Parsed with a regex rather than imported.

    tools may import kernel, and this one deliberately does not: importing
    kernel.router in a FRESH interpreter on a server gives in-memory state
    belonging to no running process, which has already produced a tool that
    confidently reported zeros. Reading the file cannot make that mistake.
    """
    src = _read(os.path.join(ROOT, 'hub/kernel/router.py'))
    out = []
    for m in re.finditer(
            r'\{"code":\s*"(\d+)",\s*"method":\s*"(\w+)",\s*"path":\s*"([^"]+)"'
            r'.*?"gate":\s*(\d+).*?"handler":\s*"(\w+)".*?"module":\s*"(\w+)"',
            src):
        out.append({'code': m.group(1), 'method': m.group(2), 'path': m.group(3),
                    'gate': int(m.group(4)), 'handler': m.group(5),
                    'module': m.group(6)})
    if not out:
        BLIND.append('router.py ROUTES could not be parsed — every leg and '
                     'gate below is unknown, not absent')
    return out


# 20404320  _route — one route by method and path, or None
def _route(method, path, routes):
    """None means the route is not declared. Callers print NO ROUTE rather than
    skipping the leg, because a leg with no address is the failure that let
    get_mesh_registry answer 404 on both servers while being fully written."""
    for r in routes:
        if r['method'] == method and r['path'] == path:
            return r
    return None


PAIRS = [
    {
        'name': 'ADMISSION down  <->  EXCHANGE up',
        'down': ('a project asks the server for its boundaries and is handed a '
                 'band, the reserved ports, the server_id and what is pending',
                 [('route', 'GET', '/api/admit'),
                  ('grep', r'def get_admit', 'hub/handlers/node.py'),
                  ('grep', r'PROJECT_BAND_FLOOR', 'hub/kernel/collect.py')]),
        'up':   ('the project reports back: files a claim, collects messages, '
                 'acknowledges bulletins with proof, opens tickets',
                 [('route', 'POST', '/api/registry/'),
                  ('route', 'POST', '/api/ack/'),
                  ('route', 'POST', '/api/bulletin/'),
                  ('route', 'POST', '/api/outbox-ack/'),
                  ('route', 'POST', '/api/tickets')]),
    },
    {
        'name': 'INSTALL down  <->  REPORT up',
        'down': ('clone from GitHub, hub on :8765, identity, then Cloudflare: '
                 'tunnel, DNS record, Access app and policy',
                 [('grep', r'git clone', 'bootstrap.sh'),
                  ('grep', r'enroll\.sh', 'bootstrap.sh'),
                  ('grep', r'access/apps', 'enroll.sh'),
                  ('grep', r'dns_records', 'enroll.sh')]),
        'up':   ('the node beats its own /api/node payload up, central records '
                 'it, and the fleet page renders the roster',
                 [('route', 'POST', '/api/heartbeat'),
                  ('route', 'GET', '/api/mesh/fleet'),
                  ('grep', r'def discover\(', 'hub/kernel/fleet.py'),
                  ('grep', r'def loop\(', 'hub/kernel/heartbeat.py')]),
    },
    {
        'name': 'AUTHORITY down  <->  ATTESTATION up',
        'down': ('FlareVault mints server_id and jwt_secret, sets the Access '
                 'policy on the human door, and issues the role a client sees',
                 [('grep', r'jwt_issuer.*flarevault|flarevault.*jwt_issuer',
                   'hub/kernel/identity.py'),
                  ('grep', r'login\.flarevault\.dev', 'hub/handlers/lobby.py'),
                  ('grep', r'provision_node', 'enroll.sh')]),
        'up':   ('the node describes itself completely in one call, so an '
                 'authority polls N nodes instead of guessing N times',
                 [('route', 'GET', '/api/node'),
                  ('grep', r'def node_payload', 'hub/handlers/node.py')]),
    },
]


# 20404312  show_pairs — which legs exist in the code and which are asserted
def show_pairs(routes):
    print()
    print('  PAIRED FLOWS — each leg checked against the source')
    print('  ' + '=' * 74)
    for p in PAIRS:
        print()
        print('  %s' % p['name'])
        for direction, (what, checks) in (('down', p['down']), ('up', p['up'])):
            found, missing = [], []
            for c in checks:
                if c[0] == 'route':
                    r = _route(c[1], c[2], routes)
                    if r:
                        found.append('%s %s (gate %d, %s)'
                                     % (c[1], c[2], r['gate'], r['code']))
                    else:
                        missing.append('%s %s — NO ROUTE' % (c[1], c[2]))
                else:
                    hs = _hits(c[1], files=[c[2]])
                    if hs:
                        found.append('%s:%d' % (c[2], hs[0][1]))
                    else:
                        missing.append('%s not in %s' % (c[1], c[2]))
            state = ('BUILT' if not missing else
                     ('PARTIAL' if found else 'ASSERTED, NOT BUILT'))
            print('    %-4s [%-19s] %s' % (direction, state, _wrap(what, 30)))
            for f in found:
                print('         ok      %s' % f)
            for m in missing:
                print('         MISSING %s' % m)


# ─────────────────────────────────────────────────────────────────────────────
# THE INVARIANT. ONE WRITER PER FACT.
#
#   a node        is the only writer of its own state
#   FlareVault    is the only writer of identity
#   the registry  is the only writer of admission
#
# A reverse leg REPORTS. The moment one WRITES a fact it does not own, or
# writes a fact it does own under a key the CALLER chose, there are two
# writers and the system has a split brain that no amount of reading either
# side will explain.
#
# Each entry names the writer, what key it writes under, and WHERE THAT KEY
# COMES FROM. The last one is the whole check: a key taken from the request
# body means the caller decides whose fact it is writing.
# ─────────────────────────────────────────────────────────────────────────────
WRITERS = [
    {'route': ('POST', '/api/heartbeat'),
     'writes': 'kernel.fleet._fleet[sid] — name, machine_id, status, path, '
               'reachability, container and project counts, os, uptime',
     'owner': 'the node the record is about',
     'key': 'payload["server_id"] or payload["machine_id"]',
     'key_from': 'BODY',
     'bound': True,
     'note': 'BOUND as of 9c32ac3. The sid is still a claim, but fleet._bound '
             '(20200316) decides whether the beat may have the record it '
             'names: the record must already exist -- a beat never creates one '
             '-- and the payload machine_id must equal the record\'s. Over the '
             'edge, a recorded edge_identity must also match the service '
             'token\'s common_name; that leg is additive so the tailnet '
             'failsafe still binds on machine_id alone. Unknown sid answers '
             '403 unknown_server_id. heartbeat() now PERSISTS too. '
             '`authenticated: false` still means what it always meant (no '
             'FlareVault join token); the binding is reported separately as '
             'bound_by = machine_id | edge+machine_id.'},
    {'route': ('POST', '/api/mesh/register'),
     'writes': 'kernel.fleet._fleet[server_id] — name, machine_id, '
               'reachability, and it PERSISTS to db/fleet.json',
     'owner': 'the node the record is about',
     'key': 'body["server_id"]',
     'key_from': 'BODY',
     'bound': True,
     'note': 'BOUND as of 9c32ac3, and now the ONLY thing that creates a fleet '
             'record. machine_id is required, because a record without one can '
             'never accept a beat. A known server_id arriving with a different '
             'machine_id is refused rather than absorbed. A known machine_id '
             'under a new sid is a note, not a refusal -- it keys a new row and '
             'cannot overwrite anyone. heartbeat() persists as well now, so the '
             'durable half is no longer the caller-keyed half. Still gate 0: '
             'anyone reaching :8765 can register a NEW server_id, which is '
             'registration\'s job and is explicit and logged.'},
    {'route': ('POST', '/api/registry/'),
     'writes': 'control.db projects — owner, status, purpose, claim, state',
     'owner': 'the project (its claim) + the registry (state, home)',
     'key': 'the project name in the URL path',
     'key_from': 'PATH',
     'bound': False,
     'note': 'CLEAN on the part that matters: `home` comes from '
             '_id.server_id() server-side, not the body, and the claim is '
             'stored verbatim and never corrected. A project cannot write its '
             'own band or its own admission — those are not columns.'},
    {'route': ('POST', '/api/ack/'),
     'writes': 'control.db acks — an APPEND of (project, ref, answer, at)',
     'owner': 'the project',
     'key': 'the project name in the URL path',
     'key_from': 'PATH',
     'bound': False,
     'note': 'CLEAN: append-only. It cannot alter the master ref it '
             'acknowledges, which is the fact the registry owns.'},
    {'route': ('POST', '/api/bulletin/'),
     'writes': 'control.db bulletin reads — an APPEND, PIN-checked',
     'owner': 'the project',
     'key': 'body["project"]',
     'key_from': 'BODY',
     'bound': True,
     'note': 'BOUND as of 9c32ac3. It used to INSERT whatever project string '
             'it was handed, unchecked, without even verifying the project '
             'existed -- and because ONE PIN was shared across every recipient, '
             'every recipient held the proof every other recipient needed. So '
             'a project could acknowledge a bulletin AS another project and the '
             'forged row landed in who_read, which control.py itself calls '
             '"the matrix, the most useful thing the server knows": not a '
             'missing auth check but a FALSE ENTRY in the record the operator '
             'reads as evidence. The PIN is now the credential -- per '
             '(bulletin, project), an HMAC of a per-bulletin secret in '
             'bulletins.secret, published nowhere. Three checks in order: the '
             'project is in the registry, the bulletin was addressed to it, '
             'and the code matches THAT project\'s. Still rendered into the '
             'readout, never a JSON field. The project name remains a body '
             'claim: there is no per-project credential on this server and one '
             'was deliberately not invented -- that half is FlareVault\'s.'},
    # THE CONTRAST, and the reason the findings above are cheap to fix: the
    # correct pattern is already written in this repo, one layer out, twice.
    {'route': ('POST', '/api/outbox-ack/'),
     'writes': 'outbox.acked_at + ack_note on one message',
     'owner': 'the project the message is addressed to',
     'key': 'body["project"], CHECKED against outbox.project',
     'key_from': 'BODY',
     'bound': True,
     'note': 'THE RIGHT SHAPE. kernel/outbox.acknowledge refuses outright: '
             '"message N is addressed to X, not Y". A body-supplied name is '
             'fine when it is checked against the record it claims. This is '
             'the exact check read_bulletin is missing, already written here.'},
    {'route': ('POST', '/api/ports/ack'),
     'writes': 'the port-change acknowledgement on this box',
     'owner': 'the operator (gate 1, a UI action, not a project)',
     'key': 'no caller-supplied key — it acks THIS server\'s own snapshot',
     'key_from': 'NONE',
     'bound': True,
     'note': 'CLEAN by shape: there is no id to forge. Listed because a '
             'reverse leg with no key is the cheapest way to hold this '
             'invariant, and it is worth seeing one that does.'},
    {'route': ('POST', '/api/outbox-address/'),
     'writes': 'outbox address — the callback URL the hub will POST to',
     'owner': 'the project',
     'key': 'the project name in the URL path',
     'key_from': 'PATH',
     'bound': False,
     'note': 'SAYS SO IN ITS OWN DOCSTRING: "there is no per-project '
             'credential on this server today, so the hub cannot verify the '
             'caller registering an address for fksinv is fksinv ... That is '
             'visibility, not proof." Loopback is refused, which bounds it.'},
]


# 20404313  show_invariant — hunt for a reverse leg writing what it does not own
def show_invariant(routes):
    print()
    print('  THE INVARIANT — one writer per fact')
    print('  ' + '=' * 74)
    print('    a node is the only writer of its own state; FlareVault the only')
    print('    writer of identity; the registry the only writer of admission.')
    print()
    enforce = _hits(r"HUB_ENFORCE_GATES", files=['hub/kernel/router.py'])
    src = _read(os.path.join(ROOT, 'hub/kernel/router.py'))
    m = re.search(r"ENFORCE_GATES\s*=\s*os\.environ\.get\('HUB_ENFORCE_GATES',\s*'(\d)'\)", src)
    default = m.group(1) if m else '?'
    setters = _hits(r'HUB_ENFORCE_GATES=', files=['bootstrap.sh', 'enroll.sh',
                                                  'hub.service'])
    print('    GATES: declared at router.py:%s, default %r, and %s sets it.'
          % (enforce[0][1] if enforce else '?', default,
             'nothing in the installer' if not setters else 'the installer'))
    print('    So every gate number below is a DECLARATION, not a control. A')
    print('    gate 1 route and a gate 0 route are equally open today.')
    print()
    split = []
    for w in WRITERS:
        r = _route(w['route'][0], w['route'][1], routes)
        gate = ('gate %d' % r['gate']) if r else 'NO ROUTE'
        code = r['code'] if r else '--------'
        risk = (w['key_from'] == 'BODY' and not w['bound'])
        mark = 'SPLIT-BRAIN RISK' if risk else 'ok'
        if risk:
            split.append(w)
        print('  [%-16s] %s %s   %s  %s'
              % (mark, w['route'][0], w['route'][1], gate, code))
        print('       writes   %s' % _wrap(w['writes'], 16))
        print('       owner    %s' % w['owner'])
        where = ('no key' if w['key_from'] == 'NONE'
                 else 'from the %s' % w['key_from'])
        print('       key      %s   (%s)' % (w['key'], where))
        print('       %s' % _wrap(w['note'], 7))
        print()
    print('  ' + '-' * 74)
    if not split:
        print('  No reverse leg writes under a key the caller chose.')
        return
    print('  FINDING — %d reverse leg(s) write a record whose KEY the caller '
          'supplies,' % len(split))
    print('  with nothing binding the caller to that key:')
    for w in split:
        print('    %s %s  ->  %s' % (w['route'][0], w['route'][1], w['key']))
    print()
    print('  CLOSED, 2026-09-27, commit 9c32ac3. Kept here because a finding')
    print('  that vanishes the moment it is fixed teaches nobody why the shape')
    print('  was wrong.')
    print()
    print('  WHAT IT WAS. POST /api/heartbeat and POST /api/mesh/register are')
    print('  gate 0, took the server_id out of the request body, and created a')
    print('  record for an id they had never seen. Any caller that could reach')
    print('  central on :8765 could overwrite ANY node\'s fleet row -- name,')
    print('  status, machine_id, counts -- or invent a node. POST /api/bulletin')
    print('  was worse in kind: one PIN shared across every recipient, so a')
    print('  project could acknowledge a bulletin AS another project and the')
    print('  forged row landed in who_read, the record the operator reads as')
    print('  evidence.')
    print()
    print('  WHAT BINDS THEM NOW. A beat must name a record that already')
    print('  exists and carry the machine_id that record holds; over the edge a')
    print('  recorded identity must match the service token too. register() is')
    print('  the only creator and requires machine_id. The bulletin PIN became')
    print('  per (bulletin, project), an HMAC of a secret published nowhere.')
    print('  Bound, not authenticated: join tokens are still FlareVault\'s, and')
    print('  `authenticated: false` still says so rather than pretending.')
    print()
    print('  A COMMENT THAT WAS NOT TRUE, AND IS NOW. mesh._record_registry')
    print('  claimed "an unknown server_id cannot grow this table behind the')
    print('  fleet\'s back" while the fleet accepted every beat carrying any')
    print('  id. It was made true rather than deleted, because the binding is')
    print('  exactly what it had always claimed.')
    print()
    print('  WHAT IS NOT BROKEN, and worth saying because it is the harder')
    print('  half: no reverse leg writes a fact belonging to a DIFFERENT')
    print('  authority. _record_registry deliberately does not copy a node\'s')
    print('  claims into central\'s control.db. /api/ack and the bulletin read')
    print('  are appends that cannot mutate what they acknowledge. A project')
    print('  cannot write its own band, because no such column exists. The')
    print('  ownership model is right; the identity binding under it is absent.')
    print()
    print('  AND THE FIX IS NOT NEW WORK. kernel/outbox.acknowledge already')
    print('  does exactly the missing check -- it refuses a body-supplied name')
    print('  that does not match the record it claims -- and')
    print('  registry.post_registry_dispose scopes its write the same way. Two')
    print('  worked examples, in this repo, one layer out from the three that')
    print('  do not. That is what makes these findings cheap and what makes')
    print('  leaving them expensive: nobody has to decide anything.')


# ─────────────────────────────────────────────────────────────────────────────
# THE FLAREVAULT SEAMS
#
# Not "future work". Each one is load-bearing code that is standing in for an
# authority and says so, and each has a specific removal. A seam whose removal
# is not written down becomes permanent by default, which is what happened to
# every unchecked assertion this repo has been deleting.
# ─────────────────────────────────────────────────────────────────────────────
SEAMS = [
    {'where': 'hub/kernel/identity.py', 'marker': r'FlareVault mints these',
     'stands_in_for': 'minting the server id and the signing secret',
     'today': '_derive_server_id() hashes /etc/machine-id into fvn_<6 hex>, '
              'and jwt_secret defaults to sha256(machine_id + "|flareshub"). '
              'jwt_issuer is the literal string "self".',
     'when_fv': 'ensure_file() must stop self-issuing: no default server_id, '
                'no default jwt_secret. A box with no provisioned identity '
                'file must report NOT PROVISIONED rather than inventing one. '
                'issue()/verify() need no change — the claims already match '
                'what FV will stamp, which was the point of choosing HS256.',
     'watch': 'the derived id is in the LIVE hostnames '
              '(flareshub-fvn-685a59, flareshub-fvn-3b8c1b) and therefore in '
              'DNS, in the Access app names and in the register. An FV-minted '
              'id that differs renames the entire fleet.'},
    {'where': 'hub/kernel/svctoken.py',
     # The marker is a single-line substring on purpose. _hits is line-based,
     # and the sentence it belongs to wraps across two lines in the source --
     # a longer pattern reported this seam as CLOSED when it is wide open,
     # which is the one way this section could actively mislead.
     'marker': r'brokers node calls',
     'stands_in_for': 'brokering one node\'s call to another',
     'today': 'this hub holds a fleet-wide Access service token at '
              '~/.flare/svctoken.json and presents it on every lobby->node '
              'call. One credential reaches every node.',
     'when_fv': 'delete the file. handlers/lobby.py and handlers/lobbyhost.py '
                'stop calling headers_for() and ask FV to broker the call '
                'instead. The Access policy on each node app changes from '
                'any_valid_service_token to whatever FV brokers with.',
     'watch': 'situation.py already notes that proxying anything sensitive '
              'would let ONE token collect every node\'s inventory in one '
              'pass. That is the exposure this seam carries.'},
    {'where': 'hub/kernel/bank.py', 'marker': r'what FlareVault should do',
     'stands_in_for': 'getting a secret to a machine safely',
     'today': 'a knowing Law V exception: read-once on project scope, 24h '
              'TTL, XOR-with-machine-id at rest, and exception_open() fails '
              'install-preflight --strict while anything is held.',
     'when_fv': 'delete the module and the /api routes that reach it. The '
                'strong version needs a key the operator holds so the box '
                'never has both halves, and that is FV\'s to build.',
     'watch': 'the file is missed by backup.sh by SCOPE, not by an exclusion. '
              'Adding a db/*.db sweep to backup.sh starts copying secrets '
              'silently. Nothing in the repo prevents that.'},
    {'where': 'hub/handlers/door.py', 'marker': r'FLAREVAULT LOGIN-FLOW SPEC',
     'stands_in_for': 'the single human gate and the role it hands out',
     'today': 'implements FV\'s layers 1 and 2 and REFUSES to go further. '
              'Issues exactly one role, "operator", with ceiling 2 and a '
              '30-minute TTL. DOOR_HOST is the apex because login.<zone> does '
              'not resolve.',
     'when_fv': 'it stops MINTING and starts DEFERRING — validate FV\'s token '
                'instead of issuing one. Set HUB_DOOR_HOST=login.<zone> the '
                'day that name resolves; the docstring says nothing else '
                'changes, and that is true because the claims already match.',
     'watch': 'master / client-full / client-viewer are in identity.ROLES and '
              'are never issued by anything. The `servers` claim that scopes '
              'a client to the nodes they own is read by lobby.py and written '
              'by nobody.'},
    {'where': 'enroll.sh', 'marker': r'STOPGAP',
     'stands_in_for': 'provisioning a node',
     'today': 'line 3, verbatim: "STOPGAP — will be replaced by FlareVault '
              'provision_node()". The NODE holds the Cloudflare API token for '
              'the length of the run and writes the tunnel, the DNS record, '
              'the Access app and its policy itself.',
     'when_fv': 'the node presents a one-time JOIN TOKEN and FV provisions '
                'Cloudflare on its behalf. The node then never holds a '
                'zone-scoped API token at all, which removes the single '
                'largest credential on the box.',
     'watch': 'this is also the only writer of ~/.flare/node.json, and '
              'therefore of the zone. fks-services has no node.json while its '
              'hostname answers at the edge — enrolment happened and the node '
              'has no record of it. Any replacement has to close that gap, not '
              'inherit it.'},
    {'where': 'hub/kernel/router.py', 'marker': r'20-29\s+FlareVault',
     'stands_in_for': 'URL and telescope-module space',
     'today': 'telescope modules 20-29 reserved for FV, 30-39 for Metaforge, '
              '40-49 local. /api/vault/* is "RESERVED AND DELIBERATELY '
              'UNIMPLEMENTED". Gate layers 3 and 4 are space FV is holding '
              '(router.py:109).',
     'when_fv': 'FV claims module numbers without asking, which is what the '
                'reservation bought. /api/vault/* must still never appear '
                'here — if it does, the hub is storing credentials.',
     'watch': 'gates 3 and 4 are declared on real routes (POST '
              '/api/lobby/vault is gate 3) and there is no TOTP, so '
              'gate_check returns True for 2 and 3. Every gate above 1 is '
              'currently gate 0.'},
    {'where': 'hub/handlers/mesh.py', 'marker': r'Authentication is FlareVault',
     'stands_in_for': 'authenticating a node to central',
     'today': 'a beat is BOUND but not AUTHENTICATED. Since 9c32ac3 it must '
              'name an existing record and carry that record\'s machine_id, so '
              'it cannot rekey or invent a node; the receiver still records '
              '`authenticated: false`, which remains true and is reported '
              'alongside bound_by.',
     'when_fv': 'join tokens become REQUIRED and an unauthenticated beat is '
                'refused rather than recorded. This closes the TOKEN half only '
                '— the caller-keyed half was closed in 9c32ac3 by binding on '
                'machine_id, without inventing a credential.',
     'watch': 'machine_id binds a beat to a record; it does not PROVE the '
              'sender is that machine, because the payload carries it. A '
              'caller who knows a node\'s machine_id can still beat as it. '
              'That residue is what the join token removes, and nothing '
              'short of it does.'},
    {'where': 'hub/handlers/lobby.py', 'marker': r'layer 3 step-up',
     'stands_in_for': 'the step-up proof for destructive actions, and the vault',
     'today': 'POST /api/lobby/server/<id> refuses writes BY NAME with owner '
              '"FlareVault" and a 501, rather than 404ing as though the route '
              'were gone. PROXY_ALLOW is read-only paths only.',
     'when_fv': 'the 501s become real step-ups. PROXY_ALLOW may then grow '
                'writes — and situation.py\'s warning applies: nothing that '
                'inventories open doors may ever be added to that list.',
     'watch': 'refusing by name is the right stand-in. It means the UI can '
              'render the seam instead of discovering it as a 404.'},
]


# 20404314  show_seams — the placeholders, and what must change when FV arrives
def show_seams():
    print()
    print('  EDGES THAT ARE PLACEHOLDERS FOR AN AUTHORITY THAT HAS NOT ARRIVED')
    print('  ' + '=' * 74)
    print('    FlareVault is reached by NO code path. There is no client, no')
    print('    base URL, no call. What exists is these seams. Each is checked')
    print('    against its marker in the source, so a seam that has been')
    print('    silently closed or silently deleted shows up here.')
    missing = []
    for s in SEAMS:
        hs = _hits(s['marker'], files=[s['where']])
        print()
        if hs:
            print('  %s:%d' % (s['where'], hs[0][1]))
        else:
            print('  %s   MARKER NOT FOUND — seam moved, closed, or renamed'
                  % s['where'])
            missing.append(s['where'])
        print('     stands in for  %s' % _wrap(s['stands_in_for'], 20))
        print('     today          %s' % _wrap(s['today'], 20))
        print('     WHEN FV ARRIVES %s' % _wrap(s['when_fv'], 20))
        print('     watch          %s' % _wrap(s['watch'], 20))
    print()
    if missing:
        print('  %d seam marker(s) not found: %s' % (len(missing), ', '.join(missing)))
        print('  A seam that has lost its marker has lost the only thing that')
        print('  made it temporary.')
        BLIND.append('seam markers not found in: %s' % ', '.join(missing))
    else:
        print('  Every seam still announces itself in the source.')


# ─────────────────────────────────────────────────────────────────────────────
# PRESENCE ON THE TWO LIVE NODES
#
# Node list from CLAUDE.md, the only place both boxes are written down — the
# same limit atlas.py reports, inherited rather than reinvented.
#
# fks-services is LAN-ONLY: its tailnet address is on the older tailnet and
# times out. Which route answered is printed, because a tool that silently
# used the fallback taught nobody anything.
# ─────────────────────────────────────────────────────────────────────────────
NODES = [
    {'node': 'ksgcohub', 'user': 'ksgco', 'ts': '100.107.234.9',
     'lan': '192.168.50.100'},
    {'node': 'fks-services', 'user': 'admin1', 'ts': '100.75.1.105',
     'lan': '192.168.1.229'},
]

# READ-ONLY, AND STRUCTURALLY INCAPABLE OF PRINTING A VALUE. Every credential
# is reported by `test -f` and `stat -c %a`. There is no `cat` of any file that
# holds one, here or anywhere in this module.
PROBE = (
    'echo "HOST:$(hostname)"; '
    'echo "HUB:$(systemctl --user is-active hub 2>/dev/null)"; '
    'echo "UNITS:$(systemctl --user list-units --type=service,timer '
    '--no-legend 2>/dev/null | grep -oE \'(hub[a-z-]*|cloudflared)\\.(service|timer)\' '
    '| sort -u | tr \'\\n\' \' \')"; '
    'echo "CFD:$(systemctl is-active cloudflared 2>/dev/null || true)/'
    '$(systemctl --user is-active cloudflared 2>/dev/null || true)"; '
    'echo "CFDBIN:$(command -v cloudflared || ls -1 ~/bin/cloudflared '
    '2>/dev/null || echo NONE)"; '
    # WHAT IS ON $PATH IS NOT WHAT THE UNIT RUNS, and on ksgcohub those are
    # two different files (/usr/local/bin vs the unit's /usr/bin). Reporting
    # only one of them would have made an upgrade applied to the wrong copy
    # look like an upgrade that did nothing.
    'echo "CFDEXEC:$( { systemctl cat cloudflared 2>/dev/null; '
    'systemctl --user cat cloudflared 2>/dev/null; } | grep -m1 -oE '
    '\'^ExecStart=[^ ]+\' | cut -d= -f2 || echo NONE)"; '
    'echo "CFDTOKEN:$(test -f /etc/cloudflared/token && echo system || true)'
    '$(test -f ~/.cloudflared/token && echo user || true)"; '
    'echo "CFTOKEN:$(test -f ~/.cf-token && stat -c %a ~/.cf-token || echo NONE)"; '
    'echo "SVCTOKEN:$(test -f ~/.flare/svctoken.json && stat -c %a '
    '~/.flare/svctoken.json || echo NONE)"; '
    'echo "NODEJSON:$(test -f ~/.flare/node.json && echo yes || echo MISSING)"; '
    'echo "IDENTITY:$(test -f ~/.flare/server.identity.json && stat -c %a '
    '~/.flare/server.identity.json || echo NONE)"; '
    'echo "ZONE:$(grep -o \'\\"zone\\"[^,]*\' ~/.flare/node.json 2>/dev/null '
    '| head -1 | grep -oE \'[a-z0-9.-]+\\.[a-z]+\' || echo NONE)"; '
    'echo "TS:$(command -v tailscale >/dev/null && tailscale ip -4 '
    '2>/dev/null | head -1 || echo NONE)"; '
    'echo "DOCKER:$(command -v docker >/dev/null && (test -S '
    '/var/run/docker.sock && echo sock || echo nosock) || echo NONE)"; '
    'echo "NTFY:$(docker ps --format \'{{.Names}} {{.Ports}}\' 2>/dev/null '
    '| grep -i ntfy | grep -oE \'[0-9]+->\' | head -1 || echo NONE)"; '
    'echo "ALERTCONF:$(test -f ~/.server-alerts.conf && stat -c %a '
    '~/.server-alerts.conf || echo NONE)"; '
    'echo "MACHINEID:$(test -s /etc/machine-id && echo yes || echo MISSING)"; '
    'echo "CLI:$(for b in ss df ip hostname nproc uptime git curl; do '
    'command -v $b >/dev/null || echo -n "$b "; done; echo -n OK)"; '
    'echo "DBS:$(ls -1 ~/hub/db/*.db 2>/dev/null | xargs -n1 basename '
    '2>/dev/null | tr \'\\n\' \' \')"; '
    'echo "BANKSALT:$(test -f ~/hub/db/.bank-salt && stat -c %a '
    '~/hub/db/.bank-salt || echo NONE)"; '
    'echo "GIT:$(git -C ~/hub rev-parse --short HEAD 2>/dev/null || echo NONE)"; '
    'echo "HUBLOCAL:$(systemctl --user show hub -p Environment 2>/dev/null '
    '| grep -oE \'HUB_LOCAL=[01]\' || echo unset)"; '
    'echo "TRUSTIP:$(systemctl --user show hub -p Environment 2>/dev/null '
    '| grep -oE \'HUB_CF_TRUST_IP=[0-9.]+\' || echo unset)"; '
    'echo "AIKEY:$(command -v python3 >/dev/null && python3 -c '
    '"import sqlite3,os;p=os.path.expanduser(\'~/hub/db/server.db\');'
    'print(sqlite3.connect(p).execute(\'select count(*) from hub_config '
    'where key=?\',(\'ai_api_key\',)).fetchone()[0])" 2>/dev/null || echo "?")"; '
    'echo "ENFORCE:$(systemctl --user show hub -p Environment 2>/dev/null '
    '| grep -oE \'HUB_ENFORCE_GATES=[0-9]\' || echo unset)"'
)


# 20404315  _probe — reach one node by tailnet then LAN, read-only
def _probe(n):
    if LOCAL:
        BLIND.append('%s — not probed (--local)' % n['node'])
        return None
    for label, addr in (('tailnet', n['ts']), ('LAN', n['lan'])):
        ok, out = _sh(['ssh', '-o', 'ConnectTimeout=6', '-o', 'BatchMode=yes',
                       '%s@%s' % (n['user'], addr), PROBE], timeout=70)
        if ok and 'HOST:' in out:
            d = dict(line.split(':', 1) for line in out.splitlines()
                     if ':' in line)
            d['_route'] = '%s (%s)' % (label, addr)
            return d
    BLIND.append('%s — no ssh by tailnet (%s) or LAN (%s); its whole column '
                 'below is unknown, not absent' % (n['node'], n['ts'], n['lan']))
    return None


# Which probe field answers for which edge, and what counts as absent. The
# judgement of "is this edge here" belongs beside the field it reads, not
# scattered through a print loop.
PRESENCE = [
    ('cf-api',      'CFTOKEN',   lambda v: 'mode %s' % v if v not in ('NONE', '') else None),
    ('cloudflared', 'CFD',       lambda v: v if v.strip('/') else None),
    ('cf-access',   'TRUSTIP',   lambda v: v if v != 'unset' else None),
    ('cf-svctoken', 'SVCTOKEN',  lambda v: 'mode %s' % v if v not in ('NONE', '') else None),
    ('zone-dns',    'ZONE',      lambda v: v if v not in ('NONE', '') else None),
    ('tailscale',   'TS',        lambda v: v if v not in ('NONE', '') else None),
    ('github',      'GIT',       lambda v: 'checkout @ %s' % v if v not in ('NONE', '') else None),
    ('ntfy',        'NTFY',      lambda v: 'container :%s' % v.rstrip('->') if v not in ('NONE', '') else None),
    ('docker',      'DOCKER',    lambda v: v if v not in ('NONE', '') else None),
    ('systemd',     'UNITS',     lambda v: v.strip() or None),
    ('sqlite',      'DBS',       lambda v: v.strip() or None),
    ('machine-id',  'MACHINEID', lambda v: v if v == 'yes' else None),
    # OK on its own means every binary answered. Anything before it is MISSING,
    # and a missing one is reported as the absence it is rather than folded
    # into a tick.
    ('host-cli',    'CLI',       lambda v: 'all present' if v == 'OK' else None),
    ('ssh',         'HUBLOCAL',  lambda v: v if v != 'unset' else None),
    ('ai-api',      'AIKEY',     lambda v: ('%s legacy row(s) in hub_config' % v)
                                 if v not in ('0', '?', '') else None),
]


# 20404316  show_presence — is each edge actually attached, on each box
def show_presence():
    print()
    print('  PRESENCE — asked of each box, never remembered.  nodes: CLAUDE.md')
    print('  ' + '=' * 74)
    seen = []
    for n in NODES:
        d = _probe(n)
        print()
        print('  %s' % n['node'])
        if not d:
            print('    COULD NOT REACH IT. Every edge below is UNKNOWN on this')
            print('    box, which is not the same as absent.')
            continue
        print('    route     %s     hub %s     build %s'
              % (d.get('_route'), d.get('HUB', '?'), d.get('GIT', '?')))
        for eid, field, judge in PRESENCE:
            v = (d.get(field) or '').strip()
            got = judge(v)
            print('    %-12s %-8s %s'
                  % (eid, 'present' if got else 'ABSENT', got or '(%s)' % (v or 'empty')))
        # The three facts that are only interesting as a comparison.
        print('    ..        node.json %s, identity %s, alerts.conf %s, '
              'bank-salt %s'
              % (d.get('NODEJSON', '?'), d.get('IDENTITY', '?'),
                 d.get('ALERTCONF', '?'), d.get('BANKSALT', '?')))
        print('    ..        gates %s' % d.get('ENFORCE', '?'))
        # TWO COPIES OF ONE DAEMON. Not cosmetic: an upgrade applied to the one
        # on $PATH is invisible to the one systemd actually launches, and the
        # symptom is a version that will not change.
        onpath, runs = (d.get('CFDBIN') or '').strip(), (d.get('CFDEXEC') or '').strip()
        if onpath and runs and onpath not in ('NONE',) and onpath != runs:
            print('    !!        cloudflared on $PATH is %s but the unit runs'
                  % onpath)
            print('              %s. Two copies. An upgrade to one does '
                  'nothing' % runs)
            print('              to the other, and the symptom is a version '
                  'that will not move.')
        seen.append((n['node'], d))
    if len(seen) < 2:
        BLIND.append('divergence — needs both nodes probed')
        return seen
    print()
    print('  DIVERGENCE — the same repo, two differently-attached machines')
    print('  ' + '-' * 74)
    (an, a), (bn, b) = seen[0], seen[1]
    for field, label in (('CFD', 'cloudflared scope'),
                         ('CFDBIN', 'cloudflared on $PATH'),
                         ('CFDEXEC', 'cloudflared the unit runs'),
                         ('CFDTOKEN', 'tunnel token'), ('CFTOKEN', 'CF API token'),
                         ('NODEJSON', 'node.json'), ('ZONE', 'zone'),
                         ('NTFY', 'ntfy port'), ('ALERTCONF', 'alerts.conf'),
                         ('UNITS', 'units'), ('TRUSTIP', 'HUB_CF_TRUST_IP')):
        av, bv = (a.get(field) or '').strip(), (b.get(field) or '').strip()
        if av == bv:
            continue
        print('    %-26s %-13s %s' % (label, an, av or 'none'))
        print('    %-26s %-13s %s' % ('', bn, bv or 'none'))
    print()
    print('    An edge attached two different ways on two boxes was attached')
    print('    by hand at least once. The third box is what proves which, and')
    print('    by then nobody remembers.')
    return seen


# ─────────────────────────────────────────────────────────────────────────────
# ADDRESSES STILL NAMED THAT DO NOT EXIST
#
# Not a documentation audit — a check that the joints named in prose AND IN
# TOOLS still exist. An address that no longer resolves is worse than none:
# somebody goes and tries it. Shell tools are scanned as well as markdown,
# because an instrument that opens a dead hostname is a worse instance of the
# same fault than a document that names one.
# ─────────────────────────────────────────────────────────────────────────────
DEAD_ADDRESSES = [
    (r'flarevault\.app',
     'the zone is flarevault.DEV, not .app. Both live node hostnames and the '
     'apex are on flarevault.dev; nothing in the register is on a .app'),
    (r'\bflareshub\.(?:<zone>|flarevault\.dev)',
     'the node hostname is flareshub-<server-id>.<zone>, e.g. '
     'flareshub-fvn-685a59.flarevault.dev — no bare flareshub.<zone> exists'),
    (r'\bhub-ksgco\b',
     'superseded by the derived id: flareshub-fvn-685a59.flarevault.dev'),
    (r'\bhub-\$\{?NODE_NAME\}?\.',
     'enroll.sh once built hub-<name>.<zone>; the live scheme is '
     'flareshub-<label>.<zone> from the server id'),
    (r'\bdashboard\.flarevault\.dev',
     'that name belongs to FlareVault. The lobby is the apex flarevault.dev '
     'with path-scoped Access on /fleet and /s/<id>/'),
    (r'\blogin\.flarevault\.dev',
     'does not resolve. handlers/door.py already falls back to the apex and '
     'says so; prose that names it sends a locked-out operator nowhere'),
]


# 20404317  _prose_and_tools — every markdown file, plus the instruments
def _prose_and_tools():
    """Markdown anywhere in the tree (walked separately, because _sources only
    collects code extensions) plus everything under hub/tools. A tool that
    opens a dead hostname is the same fault as a document that names one, and
    the more expensive of the two."""
    out = []
    for base, dirs, files in os.walk(ROOT):
        dirs[:] = [d for d in dirs if d not in SCAN_SKIP]
        for f in files:
            if f.endswith('.md'):
                rel = os.path.relpath(os.path.join(base, f), ROOT).replace('\\', '/')
                out.append(rel)
    out += [r for r in _sources() if r.startswith('hub/tools/')]
    return sorted(set(out))


# 20404319  show_dead_addresses — names still written down that are not there
def show_dead_addresses():
    print()
    print('  ADDRESSES STILL NAMED THAT DO NOT EXIST — checked, not assumed')
    print('  ' + '=' * 74)
    docs = _prose_and_tools()
    print('  scanned %d markdown + instrument file(s)' % len(docs))
    any_found = False
    for pat, correction in DEAD_ADDRESSES:
        hits = _hits(pat, files=docs)
        if not hits:
            continue
        any_found = True
        print()
        print('  %s   %d mention(s)' % (pat, len(hits)))
        print('     correct now: %s' % _wrap(correction, 18))
        for rel, n, _c, _t in hits[:10]:
            print('     %s:%s' % (rel, n))
        if len(hits) > 10:
            print('     ... and %d more' % (len(hits) - 10))
    if not any_found:
        print()
        print('  Nothing scanned names a dead address.')
    else:
        print()
        print('  A hostname written down is an INSTRUCTION. These ones send')
        print('  someone to a name that is not there. The ones inside '
              'hub/tools/')
        print('  are worse than the ones in markdown: an instrument does not '
              'get read')
        print('  sceptically, it gets run.')


# 20404318  main — derive, judge, print, then say what was not seen
def main():
    only = [a for a in sys.argv[1:] if a.startswith('--') and a != '--local']

    def want(k):
        return (not only) or ('--' + k) in only

    print()
    print('  EDGES — every external joint of ServerHub, derived at run time')
    print('  repo: %s' % ROOT)
    print('  read-only: nothing on any machine is written, restarted or fetched.')
    if LOCAL:
        print('  --local: source only. No machine was asked anything.')

    routes = _routes()
    print('  router.py: %d routes parsed' % len(routes))

    claimed = set()
    if want('inventory'):
        claimed = show_inventory()
        show_derived(claimed)
        show_lawv()
    else:
        # A section a flag skipped is a section NOBODY LOOKED AT. Saying the
        # edges are all described when the pass never ran is the exact failure
        # this file's discipline exists to stop.
        BLIND.append('edge inventory + derived pass — not run (filter %s)'
                     % ' '.join(only))

    if want('pairs'):
        show_pairs(routes)
        show_invariant(routes)
    else:
        BLIND.append('paired flows + the one-writer invariant — not run '
                     '(filter %s)' % ' '.join(only))

    if want('seams'):
        show_seams()
    else:
        BLIND.append('FlareVault seams — not run (filter %s)' % ' '.join(only))

    if want('presence'):
        show_presence()
    else:
        BLIND.append('presence on the two nodes — not run (filter %s)'
                     % ' '.join(only))

    if want('addresses'):
        show_dead_addresses()
    else:
        BLIND.append('dead addresses in prose — not run (filter %s)'
                     % ' '.join(only))

    print()
    print('  WHAT I COULD NOT SEE')
    print('  ' + '=' * 74)
    # The standing limits, printed EVERY run, because they are not failures
    # that appear sometimes — they are the shape of what this tool can know.
    standing = [
        'Inside Cloudflare. No API call is made here at all, so whether an '
        'Access app carries the policy it should, and whether a tunnel\'s '
        'ingress points where the DNS record says, is unknown from this page. '
        'tools/situation.py and tools/tracks.py answer that, with the token.',
        'Whether a present edge WORKS. `command -v tailscale` and a running '
        'unit are presence, not function. A tailscaled in NoState with no '
        'route reads as present here and has already been mistaken for a dead '
        'server once.',
        'Any credential\'s content or validity. Sources only, by Law V. A '
        'token file that exists may be expired, revoked or scoped to the '
        'wrong zone and this page will call it present.',
        'The third node. Fleet membership is a list in CLAUDE.md, so an edge '
        'attached to a box nobody wrote down is invisible to every tool here, '
        'including this one.',
        'The exchange legs END TO END. This checks that each leg exists in the '
        'code and what it writes. It does not walk one, so "built" here means '
        'reachable and correctly shaped, not exercised.',
    ]
    for s in standing:
        print('    - %s' % _wrap(s, 6))
    if BLIND:
        print()
        print('    THIS RUN, specifically:')
        for b in BLIND:
            print('    - %s' % _wrap(b, 6))
        print()
        print('    A hole here is not a pass. Everything above is true only of')
        print('    what answered.')
    print()
    return 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(130)
