#!/usr/bin/env python3
"""
# 20404718  tools.install-check — assert what bootstrap.sh installs, change nothing

    bash bootstrap.sh --check                     the installer's own entry point
    python3 hub/tools/install-check.py
    python3 hub/tools/install-check.py --strict    also fail on warns and unknowns

THE PROBLEM THIS EXISTS FOR. Of the two servers in this fleet, bootstrap.sh
produced exactly one. ksgcohub carries hub.service, hub-backup.timer and
hub-reclaim.timer — the units the installer writes. fks-services carries
hub-alert.timer, hub-daily.timer and hub-maintenance.timer, three units this
installer has never heard of, and none of the installer's own. It predates the
installer and was never brought to standard.

Nobody was careless. There was simply no command that would have said so. An
installer that can only run on a bare machine cannot answer "is this node
finished" about a machine that is already running, so "did step 7 happen" stayed
a memory, and a memory cannot fail. docs/flareshub-checklists.md B2 names this
as step 9: --check mode — assert, change nothing.

WHAT IT ASSERTS AGAINST. bootstrap.sh itself, read at runtime. The expected
systemd units are lifted out of the installer's own heredocs rather than re-typed
here, and the package list, the recognised OS ids, the clone URL and the config
keys are parsed out of it the same way. If the standard moves, this moves with
it — a check that quotes the installer from memory is one more document to go
stale. The standard's path, commit and cleanliness are printed at the top, so a
reader can tell whether a `missing` row means the box is wrong or the standard
moved under it.

WHAT IT DOES NOT DO. It installs nothing, writes nothing, starts nothing, and
prompts for nothing. Every subprocess runs with stdin closed, so nothing can ask
a question; the only privileged call is `sudo -n`, which fails rather than asks;
the database is opened mode=ro or not at all. Where it cannot see, it says so
under WHAT I COULD NOT DETERMINE — because the dangerous output is not a FAIL,
it is a clean report with a hole in it.

WHAT IT DOES NOT DUPLICATE. tools/install-preflight.py already asserts
checklist B2's rows against a machine. Its module is imported and its own checks
are run in process, so each of those ten rows has exactly one definition. They
are printed in their own section, labelled with the bootstrap step each covers.
"""
import os
import shlex
import subprocess
import sys

HOME = os.path.expanduser('~')
# What bootstrap.sh itself uses, so the check looks where the installer looks.
HUB_DIR = os.environ.get('HUB_DIR') or os.path.join(HOME, 'hub')

# Normally this file sits in <checkout>/hub/tools/. Piped in -- `ssh box python3
# - < install-check.py`, which is how it is proved against a node without
# putting a file on it -- there is no __file__ to locate, so the checkout is
# taken from HUB_DIR and the header says which one it used. A check that cannot
# be run without first writing to the machine is not a read-only check.
_SELF = globals().get('__file__') or ''       # `python3 -` may not define it
PIPED = not (_SELF and os.path.exists(os.path.abspath(_SELF)))
if PIPED:
    ROOT = HUB_DIR
else:
    ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(_SELF))))
TOOLS = os.path.join(ROOT, 'hub', 'tools')
BOOT_PATH = os.environ.get('HUB_BOOTSTRAP') or os.path.join(ROOT, 'bootstrap.sh')

OK, MISSING, DIFFERENT, WARN, UNKNOWN = 'ok', 'missing', 'different', 'warn', 'unknown'
MARK = {OK: '[x]', MISSING: '[ ]', DIFFERENT: '[!]', WARN: '[~]', UNKNOWN: '[?]'}

ROWS = []          # (step, name, state, detail)
BLIND = []         # strings: what could not be determined, and why
NOTES = []         # observations that are not pass/fail

# Description is the only directive whose value nobody obeys, so a box that
# renamed its unit is not off standard for that alone. Every other difference
# is a difference.
COSMETIC = ('Description',)


def row(step, name, state, detail):
    ROWS.append((step, name, state, detail))


def blind(what):
    BLIND.append(what)


def sh(cmd, timeout=15):
    """Run and return (rc, stdout). stdin is closed on purpose: a --check that
    can be made to wait for an answer is not non-interactive. Never raises — a
    probe that dies is a blind spot, not a crash."""
    try:
        p = subprocess.run(cmd, shell=True, capture_output=True, text=True,
                           timeout=timeout, stdin=subprocess.DEVNULL)
        return p.returncode, (p.stdout or '').strip(), (p.stderr or '').strip()
    except Exception as e:
        return 1, '', str(e)[:120]


# --no-optional-locks is not a nicety. Plain `git status` refreshes the index
# and takes .git/index.lock to do it, which is a WRITE -- proved by running this
# check against a live node and watching .git's mtime move. A read-only check
# that writes into the repository it is reading is not read-only.
GIT = 'git --no-optional-locks'


def q(path):
    """Shell-quote a path. A node whose $HOME has a space in it is not a reason
    for a check to report `git ? on ?` and call it an answer."""
    return shlex.quote(str(path))


def have(cmd):
    return sh('command -v %s' % cmd)[0] == 0


def read(path):
    try:
        with open(path, encoding='utf-8', errors='ignore') as f:
            return f.read()
    except Exception:
        return None


# ── the standard ─────────────────────────────────────────────────────────────
BOOT = read(BOOT_PATH)


def std_unit(name):
    """The body bootstrap.sh writes for `name`, taken out of the installer's own
    heredoc. Derived rather than restated, so this check cannot drift from the
    thing it is checking. ${HUB_DIR} is the only expansion those bodies use."""
    if not BOOT:
        return None
    marker = 'user/%s" <<EOF' % name
    out, on = [], False
    for line in BOOT.splitlines():
        if not on:
            if marker in line and line.lstrip().startswith('cat >'):
                on = True
            continue
        if line == 'EOF':
            break
        out.append(line.replace('${HUB_DIR}', HUB_DIR))
    return out or None


def std_list(varname):
    """A shell assignment like PACKAGES="curl git ..." read out of the installer."""
    if not BOOT:
        return []
    for line in BOOT.splitlines():
        s = line.strip()
        if s.startswith('%s="' % varname):
            return s.split('"', 2)[1].split()
    return []


def std_os_ids():
    """The OS ids bootstrap.sh recognises, parsed from its own case arms rather
    than listed again here."""
    if not BOOT:
        return []
    ids, on = [], False
    for line in BOOT.splitlines():
        s = line.strip()
        if s.startswith('case "$OS_ID" in'):
            on = True
            continue
        if not on:
            continue
        if s == 'esac':
            break
        if not s.endswith(')'):
            continue
        arm = s[:-1]
        if arm == '*' or not arm:
            continue                        # the fallback arm is not a claim
        if not all(c.isalnum() or c in '|-_.' for c in arm):
            continue                        # not a case arm, just a line with )
        ids += [a for a in arm.split('|') if a]
    return ids


def repo_tail(u):
    """owner/repo out of any remote spelling — https, ssh or with .git. The
    installer clones over https; a node cloned over ssh from the same repo is
    the same checkout and must not read as a different one."""
    u = (u or '').strip().rstrip('/')
    if u.endswith('.git'):
        u = u[:-4]
    u = u.split('://', 1)[-1]
    if '@' in u and ':' in u:
        u = u.split(':', 1)[-1]
    parts = [p for p in u.split('/') if p]
    return '/'.join(parts[-2:])


def std_clone_url():
    if not BOOT:
        return ''
    for line in BOOT.splitlines():
        if 'git clone --quiet http' in line:
            for tok in line.split():
                if tok.startswith('http'):
                    return tok
    return ''


def std_config_keys():
    """The keys bootstrap writes into db/.hub_config, from its own heredoc."""
    if not BOOT:
        return []
    keys, on = [], False
    for line in BOOT.splitlines():
        if not on:
            if 'db/.hub_config" <<EOF' in line:
                on = True
            continue
        if line == 'EOF':
            break
        if '=' in line:
            keys.append(line.split('=', 1)[0])
    return keys


# ── systemd, asked once ──────────────────────────────────────────────────────
# A --check run over a non-login ssh session can land without a user bus. If
# that is not detected, every unit row reports missing and the report blames a
# healthy box. So the manager is probed first, and when it is unreachable the
# unit-state rows become unknown rather than false.
def user_manager():
    rc, out, err = sh('systemctl --user list-units --no-legend --type=service')
    if rc == 0:
        return True, ''
    bad = err or out or 'systemctl --user returned %d' % rc
    return False, bad.splitlines()[0][:100] if bad else 'no detail'


SYSTEMD_OK, SYSTEMD_WHY = user_manager()
USER_UNIT_DIR = os.path.join(HOME, '.config', 'systemd', 'user')


def unit_enabled(unit, step, label):
    if not SYSTEMD_OK:
        row(step, label, UNKNOWN, 'user manager unreachable — state not asked')
        blind('%s enabled/disabled — systemctl --user is unreachable (%s)'
              % (unit, SYSTEMD_WHY))
        return
    rc, out, _ = sh('systemctl --user is-enabled %s' % unit)
    if out != 'enabled':
        # No last-trigger question for a unit that is not scheduled: "it has
        # never fired" about a unit that does not exist reads as a second
        # finding when it is the same one.
        row(step, label, MISSING,
            'systemctl --user reports "%s"' % out if out
            else 'not a known unit to the user manager')
        return
    extra = ''
    if unit.endswith('.timer'):
        _rc, last, _ = sh('systemctl --user show %s -p LastTriggerUSec --value'
                          % unit)
        if last in ('', 'n/a', '0'):
            extra = (' — but it has NEVER FIRED. Scheduled is not the same as '
                     'having run.')
        elif last:
            extra = ' — last fired %s' % last
    row(step, label, OK, 'enabled%s' % extra)


# ── unit bodies, compared directive by directive ─────────────────────────────
def directives(lines):
    """Key -> set of values. Environment= is split into its individual
    assignments, because `Environment=A=1 B=2` and two Environment= lines mean
    the same thing to systemd and must not read as a difference."""
    d = {}
    for ln in lines:
        s = ln.strip()
        if not s or s.startswith('#') or s.startswith('['):
            continue
        if '=' not in s:
            continue
        k, v = s.split('=', 1)
        k, v = k.strip(), v.strip()
        if k == 'Environment':
            for a in v.split():
                d.setdefault(k, set()).add(a)
        else:
            d.setdefault(k, set()).add(v)
    return d


def check_unit(unit, step):
    label = unit
    std = std_unit(unit)
    path = os.path.join(USER_UNIT_DIR, unit)
    if std is None:
        row(step, label, UNKNOWN, 'no heredoc for it in the standard — cannot compare')
        blind('%s — bootstrap.sh at %s writes no such unit, so there is nothing '
              'to assert against' % (unit, BOOT_PATH))
        return
    body = read(path)
    if body is None:
        row(step, label, MISSING, 'no unit file at %s' % path)
        return

    want, got = directives(std), directives(body.splitlines())
    absent, changed, cosmetic = [], [], []
    for k, vals in want.items():
        if k not in got:
            (cosmetic if k in COSMETIC else absent).append(k)
            continue
        for v in sorted(vals):
            if v not in got[k]:
                item = '%s=%s (has %s)' % (k, v, ' / '.join(sorted(got[k])))
                (cosmetic if k in COSMETIC else changed).append(item)
    extra = []
    for k, vals in got.items():
        for v in sorted(vals):
            if k not in want or v not in want[k]:
                extra.append('%s=%s' % (k, v))

    bits = []
    if absent:
        bits.append('missing %s' % ', '.join(sorted(absent)))
    if changed:
        bits.append('differs: %s' % '; '.join(changed))
    tail = ''
    if extra:
        tail = '  (+%d local addition(s): %s)' % (
            len(extra), ', '.join(sorted(extra)[:4]))
    if bits:
        row(step, label, DIFFERENT, '; '.join(bits) + tail)
    else:
        note = 'at standard'
        if cosmetic:
            note += ' (%s differs — cosmetic, nothing obeys it)' % ', '.join(
                sorted(set(c.split('=')[0] for c in cosmetic)))
        row(step, label, OK, note + tail)


# ═════════════════════════════════════════════════════════════════════════════
#  the steps, in the order bootstrap.sh performs them
# ═════════════════════════════════════════════════════════════════════════════

def step1_os():
    osr = read('/etc/os-release')
    if osr is None:
        row('1', 'os-release readable', MISSING,
            'cannot read /etc/os-release — bootstrap.sh dies here')
        return
    vals = {}
    for ln in osr.splitlines():
        if '=' in ln:
            k, v = ln.split('=', 1)
            vals[k] = v.strip().strip('"')
    oid = vals.get('ID', 'unknown')
    row('1', 'os-release readable', OK, vals.get('PRETTY_NAME', oid))
    known = std_os_ids()
    if not known:
        row('1', 'OS recognised', UNKNOWN, 'could not parse the installer case arms')
        blind('recognised OS ids — the case block in %s did not parse' % BOOT_PATH)
    elif oid in known:
        row('1', 'OS recognised', OK, '%s is one of %s' % (oid, ', '.join(known)))
    else:
        row('1', 'OS recognised', WARN,
            '%s is not in the installer case list (%s) — it would take the apt '
            'fallback' % (oid, ', '.join(known)))


# python3-pip installs the pip3 command; everything else in PACKAGES is named
# after the command it provides. Mapped here because presence is what can be
# checked without asking a package manager to refresh anything.
PKG_CMD = {'python3-pip': 'pip3'}


def step2_packages():
    pkgs = std_list('PACKAGES')
    if not pkgs:
        row('2', 'system packages', UNKNOWN, 'PACKAGES= not found in the standard')
        blind('system packages — PACKAGES= did not parse out of %s' % BOOT_PATH)
        return
    for p in pkgs:
        cmd = PKG_CMD.get(p, p)
        if have(cmd):
            row('2', p, OK, 'command %s present' % cmd)
        else:
            row('2', p, MISSING, 'no %s on PATH' % cmd)


def step3_docker():
    if not have('docker'):
        row('3', 'docker installed', MISSING, 'no docker on PATH')
        return
    _rc, ver, _ = sh('docker --version')
    row('3', 'docker installed', OK, ver or 'present')
    rc, out, _ = sh('systemctl is-enabled docker')
    row('3', 'docker enabled', OK if out == 'enabled' else MISSING,
        out or 'systemctl is-enabled docker said nothing (rc %d)' % rc)
    rc, out, _ = sh('systemctl is-active docker')
    row('3', 'docker running', OK if out == 'active' else MISSING,
        out or 'systemctl is-active docker said nothing (rc %d)' % rc)
    _rc, groups, _ = sh('id -nG')
    if 'docker' in groups.split():
        row('3', 'user in docker group', OK, groups)
    else:
        row('3', 'user in docker group', MISSING,
            'bootstrap runs usermod -aG docker only when it installs docker '
            'itself; groups are: %s' % groups)


def step4_hub():
    if not os.path.isdir(os.path.join(HUB_DIR, '.git')):
        row('4', 'hub checkout', MISSING, 'no git checkout at %s' % HUB_DIR)
    else:
        _rc, sha, _ = sh(GIT + ' -C %s rev-parse --short HEAD' % q(HUB_DIR))
        _rc, br, _ = sh(GIT + ' -C %s rev-parse --abbrev-ref HEAD' % q(HUB_DIR))
        _rc, url, _ = sh(GIT + ' -C %s remote get-url origin' % q(HUB_DIR))
        want = std_clone_url()
        same = want and url and repo_tail(url) == repo_tail(want)
        state = OK if (not want or same) else DIFFERENT
        row('4', 'hub checkout', state,
            '%s at %s (%s), origin %s%s'
            % (HUB_DIR, sha or '?', br or '?', url or 'none',
               '' if state == OK else ' — the installer clones %s' % want))
        blind('whether %s is current with origin — that needs a git fetch, '
              'which writes into .git, so it was not asked' % HUB_DIR)

    # The installer only installs python deps `if [ -f requirements.txt ]`, so
    # a checkout without one is at standard, not short of it.
    req = os.path.join(HUB_DIR, 'hub', 'requirements.txt')
    if not os.path.exists(req):
        row('4', 'python deps', OK,
            'no hub/requirements.txt in the standard — the installer skips this')
    else:
        missing = []
        for ln in (read(req) or '').splitlines():
            name = ln.strip().split('==')[0].split('>')[0].split('[')[0].strip()
            if not name or name.startswith('#'):
                continue
            if sh('python3 -c "import %s"' % name.replace('-', '_'))[0] != 0:
                missing.append(name)
        if missing:
            row('4', 'python deps', WARN,
                'not importable: %s — import name may differ from the package '
                'name, so this is a hint, not a verdict' % ', '.join(missing))
        else:
            row('4', 'python deps', OK, 'every requirement imports')

    # The one the installer's own comment calls out: the db directory it creates
    # must be the directory kernel/db.py opens.
    dbdir = os.path.join(HUB_DIR, 'db')
    resolved = None
    try:
        sys.path.insert(0, os.path.join(ROOT, 'hub'))
        from kernel.db import DB_PATH          # noqa: E402
        resolved = os.path.dirname(os.path.abspath(DB_PATH))
    except Exception as e:
        row('4', 'db directory', UNKNOWN, 'cannot resolve kernel.db: %s' % e)
        blind('db directory — kernel.db would not import, so the path the hub '
              'actually opens is unknown')
    if resolved is not None:
        if not os.path.isdir(dbdir):
            row('4', 'db directory', MISSING, '%s does not exist' % dbdir)
        elif os.path.abspath(dbdir) != resolved:
            row('4', 'db directory', DIFFERENT,
                'the installer creates %s but kernel/db.py opens %s'
                % (dbdir, resolved))
        else:
            row('4', 'db directory', OK, '%s — the directory the hub opens' % dbdir)

    cfg = os.path.join(dbdir, '.hub_config')
    keys = std_config_keys()
    body = read(cfg)
    if body is None:
        # WARN, not MISSING, and the reason is printed rather than assumed:
        # nothing in this repo reads this file, so its absence cannot break
        # anything. Failing a node over it would make --check cry wolf.
        row('4', 'db/.hub_config', WARN,
            'not present at %s — part of the standard, but no code in this '
            'repo reads it, so nothing depends on it' % cfg)
        NOTES.append('db/.hub_config is written by bootstrap step 4 and read by '
                     'nothing. Both live nodes are missing it and neither is '
                     'affected. It is a write, not a setting.')
    else:
        absent = [k for k in keys if ('\n%s=' % k) not in '\n' + body]
        if absent:
            row('4', 'db/.hub_config', DIFFERENT,
                'present but missing %s' % ', '.join(absent))
        else:
            row('4', 'db/.hub_config', OK,
                'present with %s' % ', '.join(keys))
    blind('whether the admin password in the database is the one the operator '
          'typed — only its hash is stored, by design. install-preflight below '
          'can only rule out the seeded default.')


def step5_service():
    for d, label in ((USER_UNIT_DIR, 'systemd user dir'),
                     (os.path.join(HOME, '.local', 'bin'), '~/.local/bin')):
        row('5', label, OK if os.path.isdir(d) else MISSING, d)
    check_unit('hub.service', '5')
    dropin = os.path.join(USER_UNIT_DIR, 'hub.service.d', '10-current.conf')
    if os.path.exists(dropin):
        NOTES.append('hub.service.d/10-current.conf exists, so --promote has run '
                     'here: the effective unit is the file above plus that '
                     'drop-in, and WorkingDirectory/ExecStart come from it.')
    if not SYSTEMD_OK:
        row('5', 'lingering', UNKNOWN, 'loginctl not asked — no user manager')
        blind('lingering — loginctl is unreliable without a user manager')
    else:
        _rc, out, _ = sh('loginctl show-user %s -p Linger --value'
                         % q(os.environ.get('USER', '')))
        if out == 'yes':
            row('5', 'lingering', OK, 'enabled — the hub survives logout')
        else:
            row('5', 'lingering', MISSING,
                'Linger=%s — user units stop when the last session ends'
                % (out or 'unreadable'))


def step6_storage():
    sp = os.path.join(TOOLS, 'storage-preflight.py')
    if not os.path.exists(sp):
        row('6', 'storage preflight', MISSING, 'tools/storage-preflight.py absent')
        return
    rc, out, err = sh('python3 %s' % q(sp), timeout=60)
    if not out:
        row('6', 'storage preflight', UNKNOWN, 'produced no output: %s' % (err[:80]))
        blind('storage preflight — it ran but said nothing')
        return
    findings = [ln.strip() for ln in out.splitlines()
                if ln.startswith('  !!') or ln.startswith('   !')]
    row('6', 'storage preflight', OK if not findings else WARN,
        'runs; %d finding(s)%s' % (len(findings),
                                   (': ' + findings[0][:70]) if findings else ''))


def step7_backups():
    for dest, src in (('hub-backup.sh', os.path.join(TOOLS, 'backup.sh')),
                      ('hub-reclaim.sh', os.path.join(TOOLS, 'reclaim.sh'))):
        p = os.path.join(HOME, '.local', 'bin', dest)
        if not os.path.exists(p):
            row('7', dest, MISSING, 'not installed at %s' % p)
            continue
        mode = oct(os.stat(p).st_mode & 0o777)[2:]
        want = read(src)
        got = read(p)
        if want is None:
            row('7', dest, UNKNOWN, 'installed (mode %s) but %s is not in this '
                                    'checkout to compare against' % (mode, src))
            blind('%s — no %s here, so drift from the standard is unknown'
                  % (dest, src))
        elif want != got:
            row('7', dest, DIFFERENT,
                'installed copy differs from %s — the node is running an older '
                'or edited script' % os.path.relpath(src, ROOT))
        elif mode != '755':
            row('7', dest, DIFFERENT, 'matches the repo but mode is %s, not 755'
                % mode)
        else:
            row('7', dest, OK, 'matches %s, mode 755' % os.path.relpath(src, ROOT))
    check_unit('hub-backup.service', '7')
    check_unit('hub-backup.timer', '7')
    unit_enabled('hub-backup.timer', '7', 'hub-backup.timer scheduled')


def step8_reclaim():
    check_unit('hub-reclaim.service', '8')
    check_unit('hub-reclaim.timer', '8')
    unit_enabled('hub-reclaim.timer', '8', 'hub-reclaim.timer scheduled')


def step_ufw():
    """bootstrap opens 22 and 8765 and forces ufw on. Reading the rule table
    needs root, and `sudo -n` is the only form allowed here — it fails instead
    of asking, which is the difference between a check and a prompt."""
    if not have('ufw'):
        row('ufw', 'ufw installed', MISSING, 'no ufw on PATH')
        return
    row('ufw', 'ufw installed', OK, 'present')
    rc, out, err = sh('sudo -n ufw status')
    if rc != 0 or not out:
        row('ufw', 'ufw rules', UNKNOWN,
            'sudo -n ufw status is not available to this user without a password')
        blind('ufw: active state and the 22/8765 rules — `sudo -n ufw status` '
              'was refused, and prompting for a password is not allowed here')
        return
    active = 'Status: active' in out
    row('ufw', 'ufw active', OK if active else MISSING,
        out.splitlines()[0] if out else 'no status line')
    for port in ('22', '8765'):
        hit = any(ln.startswith(port + '/tcp') or ln.startswith(port + ' ')
                  for ln in out.splitlines())
        row('ufw', '%s/tcp allowed' % port, OK if hit else MISSING,
            'in the rule table' if hit else 'no rule for %s in ufw status' % port)


def step9_enrol():
    """The installer SKIPS enrolment when the zone or the token is absent, and
    says so: a hub with no public hostname is a correct outcome. So these rows
    are warns — a box without a token is not off standard, it took the branch
    the standard defines."""
    zone = os.environ.get('FLARE_ZONE') or ''
    zf = os.path.join(HOME, '.flare', 'zone')
    if not zone and os.access(zf, os.R_OK):
        zone = (read(zf) or '').strip()
    if zone:
        row('9', 'zone', OK, '%s' % zone)
    else:
        row('9', 'zone', WARN,
            'no FLARE_ZONE and no readable ~/.flare/zone — the installer skips '
            'enrolment here, by design')
    tok = []
    if os.environ.get('CF_API_TOKEN'):
        tok.append('CF_API_TOKEN')
    for p in (os.path.join(HOME, '.cf-token'), '/etc/flare/token'):
        if os.access(p, os.R_OK):
            tok.append(p)
    if tok:
        row('9', 'cloudflare token', OK, 'readable from %s' % ', '.join(tok))
    else:
        row('9', 'cloudflare token', WARN,
            'none of CF_API_TOKEN, ~/.cf-token, /etc/flare/token is readable — '
            'the installer skips enrolment here, by design')
    es = os.path.join(os.path.dirname(BOOT_PATH), 'enroll.sh')
    row('9', 'enroll.sh beside the installer',
        OK if os.path.exists(es) else MISSING, es)


# ── delegated: checklist B2, asserted by install-preflight ───────────────────
# Which bootstrap step each of its rows stands for. Printed so the delegation is
# visible rather than implied.
DELEGATED_TO_STEP = {
    'hub service': '5', 'identity': '9', 'data root': '6',
    'backup target': '7', 'backups running': '7', 'cache reclamation': '8',
    'storage sound': '6', 'layout': '4', 'admin password': '4',
    'enrolled': '9',
}


def delegate():
    """Import install-preflight and run ITS checks. Not a re-implementation and
    not a scrape of its stdout: the module is the one definition of these rows,
    so they cannot drift from it here."""
    path = os.path.join(TOOLS, 'install-preflight.py')
    if not os.path.exists(path):
        blind('checklist B2 rows — tools/install-preflight.py is not in this '
              'checkout, so ten rows were not asserted at all')
        return []
    try:
        import importlib.util
        spec = importlib.util.spec_from_file_location('_install_preflight', path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
    except Exception as e:
        blind('checklist B2 rows — install-preflight would not import (%s), so '
              'ten rows were not asserted' % str(e)[:80])
        return []
    xlate = {mod.OK: OK, mod.MISSING: MISSING, mod.WARN: WARN}
    out = []
    for name, fn in mod.CHECKS:
        try:
            state, detail = fn()
        except Exception as e:
            state, detail = mod.MISSING, 'check itself failed: %s' % str(e)[:70]
        out.append((DELEGATED_TO_STEP.get(name, '-'), name,
                    xlate.get(state, UNKNOWN), detail))
    return out


# ── report ───────────────────────────────────────────────────────────────────
def header():
    print()
    print('  INSTALL CHECK — does this node match what bootstrap.sh installs?')
    print('  It asserts. It changes nothing: no package, no file, no unit, no')
    print('  database write, no prompt. Safe on a live box at any time.')
    print()
    if not BOOT:
        print('  standard    UNREADABLE at %s' % BOOT_PATH)
        print('              Every row derived from the installer is unknown '
              'below.')
        blind('the standard itself — %s could not be read, so the expected '
              'units, packages, OS list and config keys are all unknown'
              % BOOT_PATH)
    else:
        d = os.path.dirname(BOOT_PATH) or '.'
        _rc, sha, _ = sh(GIT + ' -C %s rev-parse --short HEAD' % q(d))
        _rc, br, _ = sh(GIT + ' -C %s rev-parse --abbrev-ref HEAD' % q(d))
        _rc, dirty, _ = sh(GIT + ' -C %s status --porcelain -- bootstrap.sh' % q(d))
        print('  standard    bootstrap.sh steps 1-9, read from %s' % BOOT_PATH)
        print('              git %s on %s%s' % (sha or '?', br or '?',
              '  (UNCOMMITTED CHANGES to bootstrap.sh)' if dirty else ''))
        print('              A "missing" row below means this node lacks what')
        print('              THAT file installs. If the file moved, the rows moved.')
    print('  checkout    %s%s' % (ROOT, '   (this tool was piped in, not read '
                                        'from disk — nothing was written here)'
                                  if PIPED else ''))
    if os.path.abspath(ROOT) != os.path.abspath(HUB_DIR):
        print('              NOT the standard location %s — the database and' % HUB_DIR)
        print('              layout rows below judge this checkout, not that one.')
        blind('this tool is running from %s while the standard location is %s, '
              'so the delegated layout/password rows describe the wrong '
              'checkout' % (ROOT, HUB_DIR))
    _rc, host, _ = sh('hostname')
    print('  node        %s as %s' % (host or '?', os.environ.get('USER', '?')))
    if not SYSTEMD_OK:
        print('  systemd     USER MANAGER UNREACHABLE — %s' % SYSTEMD_WHY)


STEP_TITLE = {
    '1': 'Detecting OS',
    '2': 'Installing system packages',
    '3': 'Installing Docker',
    '4': 'Setting up the hub',
    '5': 'Starting hub service',
    '6': 'Checking storage',
    '7': 'Installing backups',
    '8': 'Installing cache reclamation',
    'ufw': 'Firewall (unnumbered, after step 8)',
    '9': 'Enrolment',
}


def main():
    strict = '--strict' in sys.argv
    header()

    step1_os()
    step2_packages()
    step3_docker()
    step4_hub()
    step5_service()
    step6_storage()
    step7_backups()
    step8_reclaim()
    step_ufw()
    step9_enrol()

    order = ['1', '2', '3', '4', '5', '6', '7', '8', 'ufw', '9']
    print()
    print('  ASSERTED HERE — bootstrap.sh step by step, in the installer order')
    print('  ' + '-' * 74)
    for s in order:
        mine = [r for r in ROWS if r[0] == s]
        if not mine:
            continue
        print()
        print('  step %-3s %s' % (s, STEP_TITLE.get(s, '')))
        for _s, name, state, detail in mine:
            print('    %s %-28s %s' % (MARK[state], name, detail))

    dele = delegate()
    print()
    print('  DELEGATED — checklist B2, asserted by tools/install-preflight.py')
    print('  ' + '-' * 74)
    print('  These ten rows are not re-implemented here. That module is imported')
    print('  and its own checks are run, so each row has one definition. The')
    print('  number is the bootstrap step it stands for.')
    print()
    if dele:
        for s, name, state, detail in dele:
            print('    %s step %-3s %-18s %s' % (MARK[state], s, name, detail))
    else:
        print('    NOT RUN — see WHAT I COULD NOT DETERMINE.')

    allrows = ROWS + dele
    n = {}
    for _s, _name, state, _d in allrows:
        n[state] = n.get(state, 0) + 1
    bad = n.get(MISSING, 0) + n.get(DIFFERENT, 0)

    print()
    print('  WHAT I COULD NOT DETERMINE')
    print('  ' + '-' * 74)
    if BLIND:
        for b in BLIND:
            print('    - %s' % b)
        print()
        print('    Everything above is true only of what answered. A hole here is')
        print('    not a pass.')
    else:
        print('    Nothing. Every row was asked of the machine.')

    if NOTES:
        print()
        print('  NOTED — not pass or fail')
        print('  ' + '-' * 74)
        for t in NOTES:
            print('    - %s' % t)

    print()
    print('  ' + '-' * 74)
    print('  %d of %d at standard   ·   %d missing   ·   %d different   ·   '
          '%d warn   ·   %d could not determine'
          % (n.get(OK, 0), len(allrows), n.get(MISSING, 0), n.get(DIFFERENT, 0),
             n.get(WARN, 0), n.get(UNKNOWN, 0)))
    print('  marks   [x] at standard   [ ] missing   [!] differs from standard')
    print('          [~] warn, and the row says why it is not a failure')
    print('          [?] could not be determined — listed above')
    print()
    print('  EXIT CODE: 0 only when nothing is [ ] or [!]. Warns do not fail —')
    print('  a one-disk box or a node with no Cloudflare token can never reach an')
    print('  absolute pass, and a gate nobody can satisfy stops being read. With')
    print('  --strict, [~] and [?] fail too.')
    if bad:
        print()
        print('  THIS NODE IS NOT AT STANDARD. %d row(s) above are what '
              'bootstrap.sh' % bad)
        print('  would have installed and this machine does not have. Nothing here')
        print('  fixed any of them: this instrument reports and never repairs.')
    elif strict and (n.get(WARN, 0) or n.get(UNKNOWN, 0)):
        print()
        print('  --strict: at standard, but %d warn(s) and %d unknown(s) above.'
              % (n.get(WARN, 0), n.get(UNKNOWN, 0)))
    else:
        print()
        print('  At standard, as far as this node could be asked.')
    print()

    if bad:
        return 1
    if strict and (n.get(WARN, 0) or n.get(UNKNOWN, 0)):
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
