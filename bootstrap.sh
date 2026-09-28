#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# bootstrap.sh — Server Kit minimal boot
# Gets the hub up at :8765 in under 5 minutes.
# Run the rest of the stack from inside the hub.
#
# Usage:
#   curl -fsSL https://raw.githubusercontent.com/KGSHOPINV/claude-server/master/bootstrap.sh | bash
#   — or —
#   git clone https://github.com/KGSHOPINV/claude-server ~/hub && bash ~/hub/bootstrap.sh
#
#   bash ~/hub/bootstrap.sh --check     is this node finished? changes nothing
#   bash ~/hub/bootstrap.sh --converge  bring it to standard, doing only what
#                                       --check says is missing
#   bash ~/hub/bootstrap.sh --converge --dry-run   print the plan, do nothing
#
#   bash ~/hub/bootstrap.sh --stage <ref>    prove a ref on :8799 first
#   bash ~/hub/bootstrap.sh --promote <ref>  point the live path at it
#   bash ~/hub/bootstrap.sh --promote live   point back
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail

# ── colours ──────────────────────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
BLUE='\033[0;34m'; CYAN='\033[0;36m'; BOLD='\033[1m'; RESET='\033[0m'

ok()   { echo -e "${GREEN}✓${RESET}  $*"; }
info() { echo -e "${CYAN}→${RESET}  $*"; }
warn() { echo -e "${YELLOW}⚠${RESET}  $*"; }
die()  { echo -e "${RED}✗${RESET}  $*" >&2; exit 1; }
# There are nine steps. This counted to eight for as long as there have been
# nine, so the last thing a successful install printed was "[9/8]".
STEPS=9
step() { echo -e "\n${BOLD}${BLUE}[$1/${STEPS}]${RESET} ${BOLD}$2${RESET}"; }

# ═════════════════════════════════════════════════════════════════════════════
#  RE-RUNNING THIS ON A LIVE BOX
#
#  An installer that can only be run once is not an installer, it is a first
#  boot. Everything below this banner exists so that running this file a second
#  time on a machine that is already serving brings it TO standard instead of
#  standing on what the operator put there. The rule these three functions obey,
#  the same rule enroll.sh's ingress block obeys, is:
#
#      MERGE, LEAVE, or BACK UP AND REPORT. Never silently overwrite.
#
#  A step may create what it owns. It may never destroy state it did not create.
# ═════════════════════════════════════════════════════════════════════════════

# 20404834  _unit_merge — add what the standard needs, never remove what the box added
#
# THE FAILURE THIS PREVENTS. Step 5 wrote hub.service with a plain `cat >`. A
# second run of the installer therefore deleted every line the operator had put
# in it. On fks-services that is ExecStartPost=alert-startup.sh and three
# Environment= lines — HUB_CF_ROLE, HUB_SSH_HOST and HUB_CF_TRUST_IP. Losing the
# last one is not cosmetic: it is the Cloudflare door. Without it the hub trusts
# no proxy header, and the public entry chain stops letting anyone in. On
# ksgcohub the unit directory already holds a hub.service.bak, so a rewrite of
# that file has happened at least once before anybody wrote this down.
#
#   _unit_merge <live-unit-path> <standard-body-path>
#
# Three outcomes, and only one of them writes over anything:
#   no live file           the standard is written verbatim            exit 10
#   live file, complete    nothing is written; what is there is listed exit 0
#   live file, incomplete  backed up, then the ABSENT directives are
#                          appended to the section they belong to      exit 11
#
# A directive that is PRESENT with a different value is never changed and never
# removed. fks-services has Restart=always where the standard says on-failure;
# always is the operator's choice, it is the stricter of the two, and an
# installer that overrules it is the bug this function was written for. --check
# already reports that as [!] differs, which is the right place for the
# conversation — a report, not a rewrite.
_unit_merge() {
  python3 - "$1" "$2" <<'PY'
import os, shutil, sys, time

live, std = sys.argv[1], sys.argv[2]


def parse(lines):
    """section -> [(key, value)]. Environment= is split into its individual
    assignments, because `Environment=A=1 B=2` and two Environment= lines mean
    exactly the same thing to systemd and must not read as a difference."""
    out, sec = {}, ''
    for ln in lines:
        s = ln.strip()
        if s.startswith('[') and s.endswith(']'):
            sec = s
            out.setdefault(sec, [])
            continue
        if not s or s.startswith('#') or '=' not in s:
            continue
        k, v = s.split('=', 1)
        k, v = k.strip(), v.strip()
        if k == 'Environment':
            for a in v.split():
                out.setdefault(sec, []).append((k, a))
        else:
            out.setdefault(sec, []).append((k, v))
    return out


with open(std, encoding='utf-8') as f:
    std_lines = f.read().splitlines()

if not os.path.exists(live):
    d = os.path.dirname(live)
    if d:
        os.makedirs(d, exist_ok=True)
    shutil.copyfile(std, live)
    print('  created  %s' % live)
    sys.exit(10)

with open(live, encoding='utf-8', errors='ignore') as f:
    live_lines = f.read().splitlines()

want, got = parse(std_lines), parse(live_lines)
add, differs = {}, []

for sec, pairs in want.items():
    have = got.get(sec, [])
    for k, v in pairs:
        if (k, v) in have:
            continue
        if k == 'Environment':
            # Compared by VARIABLE NAME. Appending HUB_PORT=8765 to a unit that
            # already sets HUB_PORT=9000 would give systemd two answers.
            name = v.split('=', 1)[0]
            mine = [b for a, b in have if a == 'Environment'
                    and b.split('=', 1)[0] == name]
            if mine:
                differs.append('%s Environment %s  (this node sets %s)'
                               % (sec, v, ' / '.join(mine)))
                continue
            add.setdefault(sec, []).append('Environment=%s' % v)
            continue
        mine = [b for a, b in have if a == k]
        if mine:
            differs.append('%s %s=%s  (this node has %s)' % (sec, k, v,
                                                             ' / '.join(mine)))
            continue
        add.setdefault(sec, []).append('%s=%s' % (k, v))

extra = ['%s %s=%s' % (sec, k, v)
         for sec, pairs in got.items() for k, v in pairs
         if (k, v) not in want.get(sec, [])]

if not add:
    print('  kept     %s' % live)
    print('           every directive the standard requires is already there')
    for d in differs:
        print('           left alone (differs from standard): %s' % d)
    if extra:
        print('           %d local addition(s) kept: %s'
              % (len(extra), ', '.join(extra)))
    sys.exit(0)

bak = '%s.bak.%s' % (live, time.strftime('%Y%m%dT%H%M%SZ', time.gmtime()))
shutil.copy2(live, bak)
print('  backup   %s' % bak)


def insert(lines, sec, new):
    """Append `new` to the END of `sec`, creating the section if this unit has
    no such block. Existing lines keep their order and their text."""
    idx = None
    for j, l in enumerate(lines):
        if l.strip() == sec:
            idx = j
            break
    if idx is None:
        if lines and lines[-1].strip():
            lines = lines + ['']
        return lines + [sec] + new
    end = len(lines)
    for j in range(idx + 1, len(lines)):
        s = lines[j].strip()
        if s.startswith('[') and s.endswith(']'):
            end = j
            break
    while end > idx + 1 and not lines[end - 1].strip():
        end -= 1
    return lines[:end] + new + lines[end:]


out = list(live_lines)
for sec, new in add.items():
    for l in new:
        print('  add      %s  %s' % (sec, l))
    out = insert(out, sec, new)
for d in differs:
    print('           left alone (differs from standard): %s' % d)
if extra:
    print('           %d local addition(s) kept: %s' % (len(extra), ', '.join(extra)))

tmp = live + '.new.%d' % os.getpid()
with open(tmp, 'w', encoding='utf-8', newline='\n') as f:
    f.write('\n'.join(out) + '\n')
os.replace(tmp, live)
print('  merged   %s' % live)
sys.exit(11)
PY
}

# 20404835  _pw_hash — the password reaches python on stdin, never as a literal
#
# THE FAILURE THIS PREVENTS. The hash used to be built by interpolating the
# password into a line of Python source:
#     PW_HASH=$(python3 -c "...sha256('${HUB_PASSWORD}'...)")
# A password containing a single quote or a backslash is then a SyntaxError, and
# under `set -euo pipefail` bootstrap dies on that line — AFTER Docker has been
# installed and the repo cloned. That is precisely the half-built machine the
# non-tty guard further down exists to prevent, reached by a different door.
# It was also an argv, so the password was readable in `ps` by every user on the
# box for as long as python took to start.
#
# printf is a shell builtin and the value is passed on a pipe, so it never
# becomes a process argument and never becomes source text. Read as bytes, so a
# password with a non-ASCII character hashes to the same thing every time
# regardless of the locale the installer happened to run under.
_pw_hash() {
  printf '%s' "$1" | python3 -c \
    'import hashlib,sys;sys.stdout.write(hashlib.sha256(sys.stdin.buffer.read()).hexdigest())'
}

# 20404836  _firewall — add the rules, never switch the firewall on
#
# THE FAILURE THIS PREVENTS. The old block was three lines:
#     sudo ufw allow 22/tcp; sudo ufw allow 8765/tcp; sudo ufw --force enable
# On a box where ufw is inactive — which is the default state, and the state a
# re-run is most likely to find — that last line raises a default-deny firewall
# permitting exactly two ports. Every service in this fleet's own table goes
# dark in one command: Homepage 3000, NPM 81, Portainer 9443, Uptime Kuma 3001,
# Netdata 19999, Dozzle 8090, Cockpit 9090. The operator asked for an installer
# and got an outage.
#
# Whether the firewall is up is operator state, and this script did not create
# it. So the rules are added — `ufw allow` is additive, it removes nothing, and
# on an inactive ufw it changes nothing that is running — and a firewall found
# switched OFF is left OFF with the command printed. A firewall found ON keeps
# every rule it already has.
#
# The port is an argument. 8765 was hardcoded here while the unit above took it
# from a heredoc, so a node moved to another port had the wrong hole opened.
#
#   _firewall <port> [may_prompt]
# may_prompt is 1 only from the install path, where the operator is at the
# keyboard and has already typed a sudo password for apt. --converge passes 0:
# a converge that can stop on a password prompt cannot be run from a timer, and
# it says so by doing nothing rather than by waiting.
_firewall() {
  FW_PORT="$1"; FW_PROMPT="${2:-0}"
  if ! command -v ufw >/dev/null 2>&1; then
    warn "no ufw on PATH — no firewall rule added"
    return 0
  fi
  FW_SUDO="sudo -n"
  FW_STATUS=$(sudo -n ufw status 2>/dev/null || true)
  if [ -z "$FW_STATUS" ] && [ "$FW_PROMPT" = "1" ] && [ -t 0 ]; then
    FW_SUDO="sudo"
    FW_STATUS=$(sudo ufw status 2>/dev/null || true)
  fi
  if [ -z "$FW_STATUS" ]; then
    warn "cannot read the ufw rule table without a password — nothing added,"
    warn "  nothing enabled. Look for yourself:  sudo ufw status verbose"
    return 0
  fi
  for p in 22 "$FW_PORT"; do
    if printf '%s\n' "$FW_STATUS" | grep -qE "^${p}(/tcp)?[[:space:]]"; then
      ok "ufw: ${p}/tcp already allowed"
    elif $FW_SUDO ufw allow "${p}/tcp" >/dev/null 2>&1; then
      ok "ufw: ${p}/tcp allowed"
    else
      warn "ufw: could not add the ${p}/tcp rule — run it yourself:"
      warn "    sudo ufw allow ${p}/tcp"
    fi
  done
  if printf '%s\n' "$FW_STATUS" | grep -q 'Status: active'; then
    ok "firewall active — nothing here switched it on or off"
  else
    warn "the firewall is INACTIVE and this installer will not switch it on."
    warn "  Enabling it would default-deny everything but 22 and ${FW_PORT}, which"
    warn "  on this fleet stops Homepage 3000, NPM 81, Portainer 9443, Uptime"
    warn "  Kuma 3001, Netdata 19999, Dozzle 8090 and Cockpit 9090 answering."
    warn "  Decide that with the rule table in front of you:"
    warn "    sudo ufw status numbered   then   sudo ufw enable"
  fi
}

# 20404837  _install_tool — the script, or no timer at all
#
# THE FAILURE THIS PREVENTS. Step 7 read:
#     install -m 755 .../backup.sh ~/.local/bin/hub-backup.sh 2>/dev/null || true
# and then wrote the timer and enabled it whatever happened. If the source is
# not in the checkout the copy fails silently, the timer is enabled anyway, the
# step prints success, and the node has a nightly backup that fails forever. A
# backup you have been told you have and do not have is worse than no backup.
#
# It also only ever INSTALLED, and bootstrap only ever ran once — so an updated
# backup.sh in the repo never reached ~/.local/bin. ksgcohub is running a copy
# from before CONTROL_DB existed, which means control.db, the release and event
# history, is in no backup at all. So a stale copy is refreshed here, and what
# is being replaced is backed up first, because a copy that differs might have
# been edited on purpose.
_install_tool() {
  IT_SRC="$1"; IT_DEST="$2"
  if [ ! -r "$IT_SRC" ]; then
    warn "$IT_SRC is not in this checkout"
    warn "  NOT installing $(basename "$IT_DEST") and NOT scheduling it — a timer"
    warn "  pointing at a script that is not there fails silently every night."
    return 1
  fi
  mkdir -p "$(dirname "$IT_DEST")"
  if [ -f "$IT_DEST" ] && cmp -s "$IT_SRC" "$IT_DEST"; then
    chmod 755 "$IT_DEST"
    ok "$(basename "$IT_DEST") already matches the checkout"
    return 0
  fi
  if [ -f "$IT_DEST" ]; then
    IT_BAK="$IT_DEST.bak.$(date -u +%Y%m%dT%H%M%SZ)"
    cp -p "$IT_DEST" "$IT_BAK" || {
      warn "could not back up $IT_DEST — leaving it exactly as it is"
      return 1
    }
    info "the installed copy differs — kept as $IT_BAK"
  fi
  install -m 755 "$IT_SRC" "$IT_DEST" || {
    warn "could not install $IT_DEST"
    return 1
  }
  ok "$(basename "$IT_DEST") installed from ${IT_SRC##*/} (mode 755)"
  return 0
}

# ── --check: assert this node, install nothing ───────────────────────────────
# 20404831  check verb — "did step 7 happen" as a command, not a memory
#
# An installer that can only run on a bare machine is a one-shot script. It
# cannot answer "is this node finished?" about a box that is already running, so
# the answer stayed a memory -- and a memory cannot fail. Of the two servers in
# this fleet, this file produced exactly one of them, and nothing would have
# said so.
#
# This verb asserts every step below, in this order, and changes nothing: no
# package, no file, no unit, no database write, and no question. It is safe on a
# live production box at any time, and it never prompts -- which is why it is
# handled HERE, above the banner and above the interactive guard, before any
# part of the install path has had a chance to run.
#
# It delegates: tools/install-check.py derives the standard from THIS FILE's own
# heredocs, and hands checklist B2's ten rows to tools/install-preflight.py
# rather than re-implementing them.
#
#   bash bootstrap.sh --check            exit 0 only if nothing is missing
#   bash bootstrap.sh --check --strict   warns and unknowns fail too
if [ "${1:-}" = "--check" ]; then
  HUB_DIR="${HUB_DIR:-$HOME/hub}"
  export HUB_DIR
  # The standard is the installer you invoked, not whichever copy is at
  # $HOME/hub. Under `curl | bash` there is no such file, and install-check says
  # so rather than asserting against a guess.
  SELF_DIR=""
  SELF_DIR=$(cd "$(dirname "$0")" 2>/dev/null && pwd) || SELF_DIR=""
  [ -n "$SELF_DIR" ] && [ -r "$SELF_DIR/bootstrap.sh" ] \
    && export HUB_BOOTSTRAP="$SELF_DIR/bootstrap.sh"
  CHECK=""
  for c in "$SELF_DIR/hub/tools/install-check.py" \
           "$HUB_DIR/hub/tools/install-check.py"; do
    [ -n "$c" ] && [ -r "$c" ] && { CHECK="$c"; break; }
  done
  if [ -n "$CHECK" ]; then
    if [ $# -gt 1 ]; then exec python3 "$CHECK" "$2"; else exec python3 "$CHECK"; fi
  fi
  # Older checkout: the step-by-step assertion is not here. Say which half is
  # missing instead of printing a narrower report as if it were the whole one.
  echo "install-check.py is not in this checkout — only checklist B2 is asserted," >&2
  echo "not bootstrap.sh's own steps. Update the checkout for the full check." >&2
  exec python3 "$HUB_DIR/hub/tools/install-preflight.py" "${2:---strict}"
fi

# ── --converge: bring this node to standard, and nothing else ────────────────
# 20404838  converge verb — do only what --check says is missing
#
# --check can say a box is short of standard. Until now nothing could close the
# gap: the only thing that installed was the install path, and the install path
# was not safe to point at a live machine. So the answer to "this node is
# missing its backup timer" was a rebuild, and a fleet you can only bring to
# standard by rebuilding is a fleet of one-offs — which is exactly why an image
# taken today would be a photograph of one box's luck rather than a standard.
#
# WHAT IT DOES. It runs install-check --json and repairs the rows that come back
# `missing`, in the order the installer would have done them. It never derives
# its own idea of the standard: the unit bodies it writes are the ones
# install-check lifted out of this file's own heredocs.
#
# WHAT IT WILL NOT DO, and each of these is a decision, not an omission:
#   - it never removes or changes anything. Units go through _unit_merge, which
#     adds absent directives and leaves every local addition and every differing
#     value alone. A row --check calls `different` is reported, not corrected.
#   - it never restarts the hub. If it merges hub.service it says so and prints
#     the restart command; the operator picks the moment, not a script.
#   - it installs no packages and no Docker. That is `apt` and a remote pipe to
#     a root shell, on a machine that is serving.
#   - it never touches the git checkout. New code goes through --stage/--promote.
#   - it never seeds or changes the admin password: that needs a prompt, and a
#     converge that can block on a question cannot be run from a timer.
#   - it never switches the firewall on. See _firewall above.
#   - it does not enrol. Enrolment writes public DNS.
# Everything in that list is printed at the end as LEFT FOR YOU, with the row
# that asked for it, so the gap stays visible instead of quietly closing.
#
#   bash bootstrap.sh --converge            act
#   bash bootstrap.sh --converge --dry-run  print the plan and stop
if [ "${1:-}" = "--converge" ]; then
  HUB_DIR="${HUB_DIR:-$HOME/hub}"
  export HUB_DIR
  DRY=0
  for a in "$@"; do [ "$a" = "--dry-run" ] && DRY=1; done

  # The standard is the installer you invoked, exactly as --check resolves it.
  SELF_DIR=""
  SELF_DIR=$(cd "$(dirname "$0")" 2>/dev/null && pwd) || SELF_DIR=""
  [ -n "$SELF_DIR" ] && [ -r "$SELF_DIR/bootstrap.sh" ] \
    && export HUB_BOOTSTRAP="$SELF_DIR/bootstrap.sh"
  CHECK=""
  for c in "$SELF_DIR/hub/tools/install-check.py" \
           "$HUB_DIR/hub/tools/install-check.py"; do
    [ -n "$c" ] && [ -r "$c" ] && { CHECK="$c"; break; }
  done
  [ -n "$CHECK" ] || die "--converge needs hub/tools/install-check.py to tell it what is
    missing, and there is none in this checkout. It will not guess: an installer
    repairing rows nobody asserted is the thing this verb exists to replace."

  WORK=$(mktemp -d "${TMPDIR:-/tmp}/hub-converge.XXXXXX") \
    || die "cannot create a working directory — nothing has been changed"
  trap 'rm -rf "$WORK"' EXIT

  echo -e "\n${BOLD}${BLUE}[converge]${RESET} ${BOLD}$(hostname)${RESET}"
  info "asking --check what is missing (it changes nothing)"
  # Exit 1 from install-check means "this node is not at standard", which is the
  # normal case here and not an error. A missing FILE is an error.
  python3 "$CHECK" --json >"$WORK/check.json" 2>"$WORK/check.err" || true
  [ -s "$WORK/check.json" ] || { sed 's/^/      /' "$WORK/check.err" >&2
    die "install-check produced no report — nothing has been changed"; }

  # The plan, derived from those rows and written down before anything runs. A
  # converge that acts first and reports afterwards cannot be read in --dry-run,
  # and --dry-run is the only way to look at this before it touches a live box.
  python3 - "$WORK" <<'PY' >"$WORK/plan.tsv" || die "could not read the check report"
import json, os, sys

work = sys.argv[1]
with open(os.path.join(work, 'check.json'), encoding='utf-8') as f:
    d = json.load(f)
std = d['standard']
home, tools = std['home'], std['tools']
units_dir = os.path.join(home, '.config', 'systemd', 'user')
bindir = os.path.join(home, '.local', 'bin')

# The whole of converge's authority, written out. A row whose name is not in
# one of these four tables is reported and left alone — there is no default
# branch that acts.
UNITS = ('hub.service', 'hub-backup.service', 'hub-backup.timer',
         'hub-reclaim.service', 'hub-reclaim.timer')
SCRIPTS = {'hub-backup.sh': 'backup.sh', 'hub-reclaim.sh': 'reclaim.sh'}
TIMERS = {'hub-backup.timer scheduled': 'hub-backup.timer',
          'hub-reclaim.timer scheduled': 'hub-reclaim.timer'}
DIRS = {'systemd user dir': units_dir, '~/.local/bin': bindir}

os.makedirs(os.path.join(work, 'units'), exist_ok=True)
plan, leave = [], []


def body(name):
    """Write the standard body for `name` where the bash side can read it. It
    comes from install-check's std_unit(), which lifted it out of bootstrap.sh's
    own heredoc — converge does not carry a second copy of any unit."""
    lines = (std.get('units') or {}).get(name)
    if not lines:
        return ''
    p = os.path.join(work, 'units', name)
    with open(p, 'w', encoding='utf-8', newline='\n') as fh:
        fh.write('\n'.join(lines) + '\n')
    return p


def emit(verb, a, b, why):
    # '-' rather than '' for an unused column. A tab is IFS WHITESPACE in bash,
    # so `read` collapses two adjacent tabs into one delimiter and every field
    # after an empty one shifts left -- which silently blanked the "because"
    # line on every mkdir. No column is ever empty.
    plan.append((verb, a or '-', b or '-', why or '-'))


for r in d['rows']:
    name, state, detail = r['name'], r['state'], r['detail']
    if state == 'ok':
        continue
    if name in DIRS and state == 'missing':
        emit('mkdir', DIRS[name], '', name)
    elif name in UNITS and state in ('missing', 'different'):
        # `different` is passed through on purpose: _unit_merge adds only what
        # is ABSENT, so a unit that differs because the operator added to it
        # comes back untouched, and one that differs because a directive is
        # gone gets that directive back. Neither case can lose a line.
        p = body(name)
        if p:
            emit('unit', os.path.join(units_dir, name), p, '%s (%s)' % (name, state))
        else:
            leave.append((name, 'the standard carries no body for it — '
                                'nothing to write'))
    elif name in SCRIPTS and state in ('missing', 'different'):
        emit('script', os.path.join(tools, SCRIPTS[name]),
             os.path.join(bindir, name), '%s (%s)' % (name, state))
    elif name in TIMERS and state == 'missing':
        emit('timer', TIMERS[name], '', name)
    elif name == 'lingering' and state == 'missing':
        emit('linger', os.environ.get('USER', ''), '', name)
    elif name.endswith('/tcp allowed') and state == 'missing':
        emit('ufw', name.split('/')[0], '', name)
    else:
        leave.append((name, '%s — %s' % (state, detail)))

for verb, a, b, why in plan:
    print('\t'.join(('PLAN', verb, a, b, why.replace('\t', ' '))))
for name, why in leave:
    print('\t'.join(('LEAVE', name, why.replace('\t', ' ') or '-')))
PY

  PLAN_N=$(grep -c '^PLAN' "$WORK/plan.tsv" || true)
  LEAVE_N=$(grep -c '^LEAVE' "$WORK/plan.tsv" || true)

  echo ""
  echo -e "  ${BOLD}PLAN${RESET}  ${PLAN_N:-0} action(s). Every one of them is printed again as it runs."
  echo "  ------------------------------------------------------------------------"
  if [ "${PLAN_N:-0}" = "0" ]; then
    echo "    nothing to do — no row came back missing that converge may repair"
  else
    while IFS="$(printf '\t')" read -r kind verb a b why; do
      [ "$kind" = "PLAN" ] || continue
      case "$verb" in
        mkdir)  echo "    mkdir   $a" ;;
        unit)   echo "    unit    $a   (merge, never replace)" ;;
        script) echo "    script  $a  ->  $b" ;;
        timer)  echo "    timer   systemctl --user enable --now $a" ;;
        linger) echo "    linger  sudo loginctl enable-linger $a" ;;
        ufw)    echo "    ufw     sudo ufw allow $a/tcp   (adds a rule; enables nothing)" ;;
      esac
      echo "            because --check said: $why"
    done < "$WORK/plan.tsv"
  fi

  if [ "$DRY" -eq 1 ]; then
    echo ""
    warn "--dry-run: nothing above was done."
    echo ""
    echo -e "  ${BOLD}LEFT FOR YOU${RESET}  ${LEAVE_N:-0} row(s) converge will not touch"
    echo "  ------------------------------------------------------------------------"
    while IFS="$(printf '\t')" read -r kind a b; do
      [ "$kind" = "LEAVE" ] || continue
      printf '    %-22s %s\n' "$a" "$b"
    done < "$WORK/plan.tsv"
    echo ""
    exit 0
  fi

  echo ""
  echo -e "  ${BOLD}DOING IT${RESET}"
  echo "  ------------------------------------------------------------------------"
  RELOAD=0; HUB_UNIT_CHANGED=0; FAILED=0
  # Timers whose script did NOT land, so they must not be switched on.
  #
  # The install path has guarded this since _install_tool was written: step 7
  # holds BACKUP_OK / RECLAIM_OK and refuses to enable a timer whose script is
  # missing, because "a timer pointing at a script that is not there fails
  # silently every night" and the operator is told they have a backup they do
  # not have. Converge repairs the same two rows and had no such link: a
  # failed `script` action set FAILED=1 and the `timer` action three lines
  # later enabled the unit anyway. The defect the installer fixed was back, by
  # the other door, on exactly the boxes converge exists for.
  #
  # The rows are independent by design — converge only ever does what --check
  # asked for — so the dependency between them has to be carried here.
  SKIP_TIMER=""
  while IFS="$(printf '\t')" read -r kind verb a b why; do
    [ "$kind" = "PLAN" ] || continue
    case "$verb" in
      mkdir)
        info "mkdir -p $a"
        mkdir -p "$a" && ok "$a" || { warn "could not create $a"; FAILED=1; }
        ;;
      unit)
        info "merging $a"
        RC=0; _unit_merge "$a" "$b" || RC=$?
        case "$RC" in
          0)  : ;;
          10|11) RELOAD=1
                 case "$a" in *hub.service) HUB_UNIT_CHANGED=1 ;; esac ;;
          *)  warn "could not merge $a"; FAILED=1 ;;
        esac
        ;;
      script)
        info "installing $b"
        if _install_tool "$a" "$b"; then :; else
          FAILED=1
          case "$(basename "$b")" in
            hub-backup.sh)  SKIP_TIMER="$SKIP_TIMER hub-backup.timer" ;;
            hub-reclaim.sh) SKIP_TIMER="$SKIP_TIMER hub-reclaim.timer" ;;
          esac
        fi
        ;;
      timer)
        case " $SKIP_TIMER " in
          *" $a "*)
            warn "$a NOT enabled — its script did not install (above)."
            warn "  Scheduling it anyway would give this node a nightly job that"
            warn "  fails silently forever, and a report saying the step is done."
            FAILED=1
            continue
            ;;
        esac
        info "systemctl --user enable --now $a"
        # daemon-reload first: the unit may have been written seconds ago by the
        # line above, and systemd will not enable a unit it has not read.
        systemctl --user daemon-reload 2>/dev/null || true
        systemctl --user enable --now "$a" 2>/dev/null \
          && ok "$a scheduled" \
          || { warn "could not enable $a — run it yourself and read the error:"
               warn "    systemctl --user enable --now $a"; FAILED=1; }
        ;;
      linger)
        info "sudo -n loginctl enable-linger $a"
        sudo -n loginctl enable-linger "$a" 2>/dev/null \
          && ok "lingering enabled — user units now survive logout" \
          || { warn "needs a password, so it was not done. Run:"
               warn "    sudo loginctl enable-linger $a"; }
        ;;
      ufw)
        info "adding the ufw rule for $a/tcp (nothing is enabled)"
        _firewall "$a"
        ;;
    esac
  done < "$WORK/plan.tsv"

  if [ "$RELOAD" -eq 1 ]; then
    systemctl --user daemon-reload 2>/dev/null \
      && ok "systemctl --user daemon-reload" \
      || warn "daemon-reload failed — run it yourself: systemctl --user daemon-reload"
  fi

  echo ""
  echo -e "  ${BOLD}LEFT FOR YOU${RESET}  ${LEAVE_N:-0} row(s) converge will not touch"
  echo "  ------------------------------------------------------------------------"
  while IFS="$(printf '\t')" read -r kind a b; do
    [ "$kind" = "LEAVE" ] || continue
    printf '    %-22s %s\n' "$a" "$b"
  done < "$WORK/plan.tsv"

  echo ""
  if [ "$HUB_UNIT_CHANGED" -eq 1 ]; then
    warn "hub.service changed on disk. The RUNNING hub is still the old unit."
    warn "  Converge does not pick the moment a live service restarts. You do:"
    warn "    systemctl --user restart hub"
  fi
  if [ "$FAILED" -eq 1 ]; then
    warn "at least one action above did not complete — read it, fix it, run again."
  fi
  info "converge changes nothing it was not asked for. Ask again:"
  echo -e "     ${CYAN}bash $0 --check${RESET}"
  echo ""
  exit 0
fi

# ── banner ────────────────────────────────────────────────────────────────────
echo -e "
${BOLD}${CYAN}  ╔══════════════════════════════════════╗
  ║       Server Kit — Bootstrap         ║
  ║   Hub will be live at :8765          ║
  ╚══════════════════════════════════════╝${RESET}
"

# ── --stage / --promote: an upgrade you can look at before you take it ───────
# 20404832  release verbs — stage a ref beside the live hub, then point at it
#
# Every real defect found in this repo this fortnight was found the same way: a
# copy of the code was run somewhere harmless and made to prove itself, instead
# of being deployed and watched. `git pull && systemctl restart` skips that
# step entirely, so the first machine to execute new code is the one holding
# the data. This is that method written down as a command.
#
#   bootstrap.sh --stage <ref>    check <ref> out NEXT TO the live hub, boot it
#                                 on :8799 against a COPY of the database, run
#                                 the preflight, report. Touches nothing live.
#   bootstrap.sh --promote <ref>  point the live path at a ref that was staged
#                                 and restart the hub user service.
#   bootstrap.sh --promote live   point back at the original clone (rollback).
#   bootstrap.sh --stage          list what is staged and what is live now.
#
# Neither verb stops, starts or builds a container, and neither asks a
# question -- so both are safe from a timer, over ssh, or on a live box.
#
# Law IV applies throughout: when either verb finds something wrong it prints
# the command that fixes it and stops. It never installs a dependency, never
# rolls itself back, and never repairs a half-finished stage.
if [ "${1:-}" = "--stage" ] || [ "${1:-}" = "--promote" ]; then
  HUB_DIR="${HUB_DIR:-$HOME/hub}"
  RELEASES="${HUB_RELEASES:-$HOME/hub-releases}"
  CURRENT="${HUB_CURRENT:-$HOME/hub-current}"
  RECEIPTS="$RELEASES/.receipts"
  # 8799 sits inside the Tools lane (8000-8999, kernel/collect.py:383), which
  # is declared but unallocated. Declared is not free, so the stage tests the
  # port rather than assuming it -- see _port_free below.
  STAGE_PORT="${HUB_STAGE_PORT:-8799}"

  # The port the live hub is actually on, asked of the running unit rather than
  # read from a config file beside it. Law I: the unit is what systemd obeys;
  # db/.hub_config is a copy of an intention.
  # The trailing `|| true` is not decoration: `set -o pipefail` is on, so on a
  # box with no hub unit this pipeline returns non-zero and set -e would end
  # the script here with no message at all.
  LIVE_PORT=$(systemctl --user show hub -p Environment --value 2>/dev/null \
              | tr ' ' '\n' | sed -n 's/^HUB_PORT=//p' | head -1 || true)
  LIVE_PORT="${LIVE_PORT:-8765}"

  # A ref name is not a directory name: `origin/fix/x` has a slash in it.
  _slug() { printf '%s' "$1" | tr -c 'A-Za-z0-9._-' '_'; }

  # Binds exactly the way http.server does -- HTTPServer sets
  # allow_reuse_address, so a socket merely in TIME_WAIT is not a conflict and
  # must not be reported as one. This answers the question the staged hub is
  # about to ask, not a similar-looking one.
  _port_free() {
    python3 - "$1" <<'PY'
import socket, sys
s = socket.socket()
s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
try:
    s.bind(('0.0.0.0', int(sys.argv[1])))
except OSError:
    sys.exit(1)
finally:
    s.close()
PY
  }

  # `cp` of a SQLite file the hub is writing to can copy a torn page: the file
  # looks fine and fails on the query you care about. The backup API takes a
  # consistent snapshot of a database in use, which is the only kind this
  # machine has.
  _db_copy() {
    python3 - "$1" "$2" <<'PY'
import os, sqlite3, sys
src, dst = sys.argv[1], sys.argv[2]
if not os.path.exists(src):
    sys.exit(0)
os.makedirs(os.path.dirname(dst), exist_ok=True)
s = sqlite3.connect('file:%s?mode=ro' % src, uri=True)
d = sqlite3.connect(dst)
s.backup(d)
d.close()
s.close()
PY
  }

  _http_code() {
    python3 - "$1" <<'PY'
import sys, urllib.error, urllib.request
try:
    with urllib.request.urlopen(sys.argv[1], timeout=3) as r:
        print(r.status)
except urllib.error.HTTPError as e:
    print(e.code)          # 401/403 means routing works and a gate is armed
except Exception:
    print('000')           # nothing answered: that is the failure
PY
  }

  # Sorted and indented on the way to disk, so a diff between two snapshots is
  # about the machine and never about dict ordering.
  _receipt_snapshot() {
    python3 - "$1" "$2" <<'PY'
import json, sys, urllib.request
url, dest = sys.argv[1], sys.argv[2]
try:
    with urllib.request.urlopen(url, timeout=10) as r:
        data = json.loads(r.read().decode())
except Exception as e:
    data = {'_unavailable': '%s: %s' % (type(e).__name__, e)}
with open(dest, 'w', encoding='utf-8') as f:
    json.dump(data, f, indent=2, sort_keys=True, default=str)
    f.write('\n')
PY
  }

  # Reads one field out of a stage receipt, and returns 0 even when the file is
  # not there -- callers use it inside $( ), where a non-zero status under
  # pipefail + set -e would kill the script instead of yielding an empty value.
  _receipt_get() { { sed -n "s/^$2=//p" "$1" 2>/dev/null || true; } | head -1; }

  # What is staged, and what is live. Derived from the filesystem every time --
  # the symlink IS the answer to "which code is running", so nothing else is
  # asked and nothing else is kept.
  _list_releases() {
    echo ""
    if [ -L "$CURRENT" ]; then
      echo -e "  ${BOLD}live path${RESET}  $CURRENT -> $(readlink "$CURRENT")"
    else
      echo -e "  ${BOLD}live path${RESET}  $HUB_DIR  (not switched to a symlink yet)"
    fi
    echo -e "  ${BOLD}staged${RESET}"
    local found=0
    if [ -d "$RELEASES" ]; then
      for d in "$RELEASES"/*/; do
        [ -d "$d/.git" ] || continue
        found=1
        r="$d.stage-receipt"
        if [ -f "$r" ]; then
          printf '    %-22s %-9s %s  preflight %s/%s  boot %s\n' \
            "$(_receipt_get "$r" ref)" \
            "$(_receipt_get "$r" sha | cut -c1-8)" \
            "$(_receipt_get "$r" at)" \
            "$(_receipt_get "$r" staged_done)" \
            "$(_receipt_get "$r" live_done)" \
            "$(_receipt_get "$r" probe)"
        else
          printf '    %-22s no receipt — that stage did not finish\n' "$(basename "$d")"
        fi
      done
    fi
    [ "$found" -eq 0 ] && echo "    (nothing staged)"
    echo ""
  }

  # ── --stage ────────────────────────────────────────────────────────────────
  if [ "$1" = "--stage" ]; then
    REF="${2:-}"
    [ -z "$REF" ] && { _list_releases; exit 0; }
    [ -d "$HUB_DIR/.git" ] || die "no git checkout at $HUB_DIR — nothing to stage from"

    mkdir -p "$RELEASES"
    STAGE="$RELEASES/$(_slug "$REF")"

    echo -e "\n${BOLD}${BLUE}[stage]${RESET} ${BOLD}$REF${RESET}"

    # --no-hardlinks on purpose. A clone that shares object storage with the
    # live repo is not separate from it, and separate is the entire claim this
    # verb is making.
    if [ -d "$STAGE/.git" ]; then
      info "re-staging into $STAGE"
    else
      info "cloning $HUB_DIR -> $STAGE"
      git clone --quiet --no-hardlinks "$HUB_DIR" "$STAGE"
    fi

    # Fetch from the REAL origin, not from the live checkout, so the live
    # repository is only ever read here. `git -C "$HUB_DIR" fetch` would write
    # into the running hub's .git, which is a promise this verb should not have
    # to qualify.
    ORIGIN=$(git -C "$HUB_DIR" remote get-url origin 2>/dev/null || echo '')
    if [ -n "$ORIGIN" ]; then
      git -C "$STAGE" remote set-url origin "$ORIGIN"
      git -C "$STAGE" fetch --quiet --tags origin 2>/dev/null \
        || warn "fetch from $ORIGIN failed — resolving '$REF' from what is already here"
    fi

    # origin/<ref> is tried FIRST: `--stage master` means the master upstream
    # has, not the local branch this box happens to be sitting on.
    if git -C "$STAGE" rev-parse --verify --quiet "origin/$REF^{commit}" >/dev/null; then
      TARGET="origin/$REF"
    elif git -C "$STAGE" rev-parse --verify --quiet "$REF^{commit}" >/dev/null; then
      TARGET="$REF"
    else
      die "no such ref: '$REF' (tried origin/$REF and $REF in $STAGE)"
    fi
    git -C "$STAGE" checkout --quiet --detach "$TARGET"
    SHA=$(git -C "$STAGE" rev-parse HEAD)
    ok "checked out $TARGET  $SHA"

    # A copy, because the staged hub WRITES: db_ensure_tables, log_activity and
    # the port scanner all run at boot. Pointing it at the live file would make
    # a dry run a live run.
    info "copying the database (hot-safe snapshot)"
    _db_copy "$HUB_DIR/db/server.db"  "$STAGE/db/server.db" \
      || die "could not snapshot $HUB_DIR/db/server.db — staging against no database proves nothing"
    _db_copy "$HUB_DIR/db/control.db" "$STAGE/db/control.db" \
      || warn "no control.db snapshot — this checkout may predate kernel/control.py"
    ok "database copied to $STAGE/db"

    # The staged hub gets its own HOME. Not tidiness: kernel/log.py:80 reads
    # ~/.server-alerts.conf and that file OVERRIDES HUB_NTFY_URL, so a stage
    # sharing $HOME pushes duplicate alerts to the real topic; and
    # kernel/identity.py:44 reads ~/.flare/server.identity.json, so it would
    # boot wearing the live node's identity and heartbeat to central as a
    # second copy of this machine. A fresh identity file has no central_* set
    # (identity.py:88), so the staged node announces itself to nobody.
    STAGE_HOME="$STAGE/.stage-home"
    mkdir -p "$STAGE_HOME/.flare"

    _port_free "$STAGE_PORT" || die "port $STAGE_PORT is already in use — staging would fight whatever holds it.
    Find it:          ss -ltnp 'sport = :$STAGE_PORT'
    Or pick another:  HUB_STAGE_PORT=8798 bash $0 --stage $REF"

    BOOTLOG="$STAGE/.stage-boot.log"
    info "booting staged hub on :$STAGE_PORT (ufw opens 22 and $LIVE_PORT only, so this is host-local)"
    # exec, so $! is python's pid and not a shell that outlives the kill below.
    (
      cd "$STAGE/hub" && exec env \
        HOME="$STAGE_HOME" \
        HUB_LOCAL=1 \
        HUB_PORT="$STAGE_PORT" \
        HUB_DB="$STAGE/db/server.db" \
        HUB_CONTROL_DB="$STAGE/db/control.db" \
        HUB_IDENTITY_FILE="$STAGE_HOME/.flare/server.identity.json" \
        HUB_NTFY_URL="http://127.0.0.1:9" \
        python3 server.py
    ) >"$BOOTLOG" 2>&1 &
    STAGE_PID=$!

    PROBE='no answer'
    for _i in $(seq 1 30); do
      sleep 0.5
      if ! kill -0 "$STAGE_PID" 2>/dev/null; then PROBE='exited'; break; fi
      CODE=$(_http_code "http://127.0.0.1:$STAGE_PORT/api/receipt")
      if [ "$CODE" != "000" ]; then PROBE="$CODE"; break; fi
    done
    kill "$STAGE_PID" 2>/dev/null || true
    wait "$STAGE_PID" 2>/dev/null || true

    case "$PROBE" in
      2*|3*|4*) ok   "staged hub answered /api/receipt with HTTP $PROBE, then stopped" ;;
      5*)       warn "staged hub answered HTTP $PROBE — it runs, but the receipt is broken" ;;
      *)        warn "staged hub never answered ($PROBE) — last lines of $BOOTLOG:"
                tail -n 15 "$BOOTLOG" | sed 's/^/      /' ;;
    esac

    # The preflight reads the LIVE database path on purpose. check_layout
    # (install-preflight.py:158) calls any server.db that is not DB_PATH a
    # rival copy, so pointing it at the stage copy would make every single
    # stage report a WARN about the machine's real database. The question this
    # check answers is "would this node be finished if this code were live",
    # and that is a question about the live layout. It only reads: the one
    # query it runs opens the file mode=ro.
    PRE_STAGED="$STAGE/.stage-preflight.txt"
    PRE_LIVE="$STAGE/.live-preflight.txt"
    set +e
    HUB_DB="$HUB_DIR/db/server.db" python3 "$STAGE/hub/tools/install-preflight.py" \
      >"$PRE_STAGED" 2>&1
    HUB_DB="$HUB_DIR/db/server.db" python3 "$HUB_DIR/hub/tools/install-preflight.py" \
      >"$PRE_LIVE" 2>&1
    set -e
    # An absolute pass is the wrong bar. A node with no enrolment or no second
    # disk never reaches 10 of 10, so gating on --strict would mean every real
    # upgrade gets forced through and the check stops meaning anything. The
    # question worth failing on is whether the new code asserts LESS than the
    # code already running -- a regression, derived by running both.
    STAGED_DONE=$(sed -n 's/^\([0-9]*\) of .*complete$/\1/p' "$PRE_STAGED" | head -1 || true)
    LIVE_DONE=$(sed -n 's/^\([0-9]*\) of .*complete$/\1/p' "$PRE_LIVE" | head -1 || true)
    STAGED_DONE="${STAGED_DONE:-0}"
    LIVE_DONE="${LIVE_DONE:-0}"
    # What --strict would have said, recorded because it is the honest answer
    # to "is this node finished", and kept OUT of the gate for the reason
    # above. Derived from the report rather than from a second run: --strict
    # changes the exit code and nothing else, and anything that is not [x] is
    # exactly what makes it exit 1 (install-preflight.py:242).
    STRICT=pass
    grep -qE '^ *\[[ ~]\]' "$PRE_STAGED" && STRICT=fail
    sed 's/^/      /' "$PRE_STAGED"

    # Reported, not installed. Installing anything here would change the
    # dependencies under the RUNNING hub, which is the one thing --stage
    # promises not to do. The boot above already answered the question
    # empirically: it ran against this machine's existing packages.
    #
    # This used to diff a hub pip requirements file between the two checkouts.
    # No such file has ever existed in this repo, so `diff -q` compared two
    # absent paths, returned non-zero, and EVERY stage printed a dependency
    # drift warning about a file that is not there. The hub's dependencies are
    # the system packages in PACKAGES= — that is the real list, so that is the
    # list compared.
    PKGNOTE='unchanged'
    LIVE_PKGS=$(sed -n 's/^PACKAGES="\(.*\)"$/\1/p' "$HUB_DIR/bootstrap.sh" 2>/dev/null | head -1 || true)
    STAGE_PKGS=$(sed -n 's/^PACKAGES="\(.*\)"$/\1/p' "$STAGE/bootstrap.sh" 2>/dev/null | head -1 || true)
    if [ "$LIVE_PKGS" != "$STAGE_PKGS" ]; then
      PKGNOTE='DIFFERS'
      warn "the staged installer wants a different package list:"
      echo "        live:   ${LIVE_PKGS:-(none found)}"
      echo "        staged: ${STAGE_PKGS:-(none found)}"
      info "install them BEFORE promoting, so the promote is only a rename:"
      info "  sudo apt-get install -y ${STAGE_PKGS}"
    fi

    VERDICT=fail
    case "$PROBE" in
      2*|3*|4*) [ "$STAGED_DONE" -ge "$LIVE_DONE" ] && VERDICT=pass ;;
    esac

    # The one thing here that is NOT derivable: that this code was proved on
    # this machine at this time. A sha is readable from git forever; "it booted
    # and answered" is an event, and events are stored (kernel/control.py:13).
    cat > "$STAGE/.stage-receipt" <<EOF
ref=$REF
resolved=$TARGET
sha=$SHA
at=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
port=$STAGE_PORT
probe=$PROBE
staged_done=$STAGED_DONE
live_done=$LIVE_DONE
strict=$STRICT
packages=$PKGNOTE
verdict=$VERDICT
EOF

    # Best-effort mirror into the control database, which is where release
    # history lives so it survives a hub that a bad promote broke. Older
    # checkouts have no kernel.control; the receipt file above is the record
    # promote actually reads, so this failing costs nothing.
    python3 - "$HUB_DIR" "$REF" "$SHA" "$VERDICT" "$STAGED_DONE" "$LIVE_DONE" "$PROBE" <<'PY' 2>/dev/null || true
import os, sys
sys.path.insert(0, os.path.join(sys.argv[1], 'hub'))
from kernel import control
control.release(sys.argv[2], 'staged',
                preflight='preflight %s/%s, boot %s' % (sys.argv[5], sys.argv[6], sys.argv[7]),
                note='sha %s verdict %s' % (sys.argv[3], sys.argv[4]))
PY

    echo ""
    echo -e "  ${BOLD}stage${RESET}       $STAGE"
    echo -e "  ${BOLD}sha${RESET}         $SHA"
    echo -e "  ${BOLD}boot${RESET}        :$STAGE_PORT -> $PROBE"
    echo -e "  ${BOLD}preflight${RESET}   staged $STAGED_DONE complete · live $LIVE_DONE complete · --strict would $STRICT"
    echo -e "  ${BOLD}deps${RESET}        system packages $PKGNOTE"
    if [ "$VERDICT" = "pass" ]; then
      ok "staged and proved — nothing live was touched"
      echo -e "     promote it with:  ${CYAN}bash $0 --promote $REF${RESET}"
      exit 0
    fi
    warn "staged, NOT proved — promote will refuse this ref"
    echo "     boot:      $PROBE          (2xx/3xx/4xx means it served)"
    echo "     preflight: $STAGED_DONE complete, against $LIVE_DONE live"
    echo "     evidence:  $BOOTLOG"
    echo "                $PRE_STAGED"
    exit 1
  fi

  # ── --promote ──────────────────────────────────────────────────────────────
  # 20404833  promote — one rename, then one user service restarts
  #
  # The live path is a symlink, and every promote and every rollback is a
  # single rename of it. That is the whole reason for the indirection: a
  # rename either happened or it did not, so the live path always points at
  # exactly one complete checkout and never at a half-copied one.
  REF="${2:-}"
  if [ -z "$REF" ]; then
    _list_releases
    die "say which ref to promote:  bash $0 --promote <ref>   (or 'live' to go back)"
  fi
  [ -f "$HOME/.config/systemd/user/hub.service" ] \
    || die "no hub.service — this node was never bootstrapped. Run: bash $0"

  ANYWAY=0
  for a in "$@"; do [ "$a" = "--anyway" ] && ANYWAY=1; done

  if [ "$REF" = "live" ]; then
    # Rollback is never gated. The original clone is what was running before
    # any of this existed; refusing to point back at it because it carries no
    # stage receipt would make the escape hatch the hardest door to open.
    TARGET_DIR="$HUB_DIR"
    info "pointing back at the original clone $HUB_DIR"
  else
    STAGE="$RELEASES/$(_slug "$REF")"
    TARGET_DIR="$STAGE"
    RCPT="$STAGE/.stage-receipt"
    [ -d "$STAGE/.git" ] || die "'$REF' was never staged on this machine, so nothing here has ever run it.
    Stage it first:  bash $0 --stage $REF"
    [ -f "$RCPT" ] || die "$STAGE exists but carries no stage receipt — that stage did not finish.
    Re-run:  bash $0 --stage $REF"
    R_SHA=$(_receipt_get "$RCPT" sha)
    NOW_SHA=$(git -C "$STAGE" rev-parse HEAD 2>/dev/null || echo 'unreadable')
    [ "$R_SHA" = "$NOW_SHA" ] \
      || die "the staged tree moved after it was staged (receipt $R_SHA, now $NOW_SHA).
    Nothing has proved the code sitting there. Re-run:  bash $0 --stage $REF"
    R_VERDICT=$(_receipt_get "$RCPT" verdict)
    if [ "$R_VERDICT" != "pass" ] && [ "$ANYWAY" -eq 0 ]; then
      die "'$REF' was staged but did not prove itself (boot $(_receipt_get "$RCPT" probe), preflight $(_receipt_get "$RCPT" staged_done) against $(_receipt_get "$RCPT" live_done) live).
    Read:      $STAGE/.stage-boot.log
    Override:  bash $0 --promote $REF --anyway"
    fi
  fi

  echo -e "\n${BOLD}${BLUE}[promote]${RESET} ${BOLD}$REF${RESET}"

  # Adopt the existing clone as the first release, so there is always somewhere
  # to point back TO before there is anything to point away from.
  if [ -L "$CURRENT" ]; then
    PREV_DIR=$(readlink "$CURRENT")
  elif [ -e "$CURRENT" ]; then
    die "$CURRENT exists and is not a symlink — refusing to replace a real directory"
  else
    ln -s "$HUB_DIR" "$CURRENT"
    PREV_DIR="$HUB_DIR"
    ok "live path is now a symlink: $CURRENT -> $HUB_DIR"
  fi
  PREV_REF='live'
  if [ "$PREV_DIR" != "$HUB_DIR" ]; then
    PREV_REF=$(_receipt_get "$PREV_DIR/.stage-receipt" ref)
    PREV_REF="${PREV_REF:-live}"
  fi

  # The drop-in, rewritten every promote so it is identical on every node.
  #
  # HUB_DB and HUB_CONTROL_DB are the load-bearing lines. kernel/db.py:15
  # resolves the database RELATIVE TO THE CHECKOUT, so without them a promote
  # would move the hub onto the staged COPY of the database and every user,
  # session and journal entry written since the stage would silently vanish.
  # Pinned here, the data stays with $HUB_DIR whichever code is live.
  DROPIN="$HOME/.config/systemd/user/hub.service.d"
  mkdir -p "$DROPIN"
  cat > "$DROPIN/10-current.conf" <<EOF
# Written by bootstrap.sh --promote. The unit points at a symlink; promote and
# rollback move the symlink. ExecStart= must be cleared before it is set again.
[Service]
WorkingDirectory=${CURRENT}/hub
ExecStart=
ExecStart=/usr/bin/python3 ${CURRENT}/hub/server.py
Environment=HUB_DB=${HUB_DIR}/db/server.db
Environment=HUB_CONTROL_DB=${HUB_DIR}/db/control.db
EOF

  # Receipt BEFORE. Two snapshots of the one projection, either side of the
  # flip: whatever differs between them IS what this promote did -- written by
  # the machine rather than by whoever wrote the commit message.
  mkdir -p "$RECEIPTS"
  STAMP=$(date -u +"%Y%m%dT%H%M%SZ")
  BEFORE="$RECEIPTS/$STAMP-$(_slug "$REF")-before.json"
  AFTER="$RECEIPTS/$STAMP-$(_slug "$REF")-after.json"
  _receipt_snapshot "http://127.0.0.1:$LIVE_PORT/api/receipt" "$BEFORE"
  ok "receipt before: $BEFORE"

  # The flip. ln then mv, not `ln -sfn`: ln -sfn unlinks and re-creates, so
  # there is a moment with no live path at all. mv -T over a symlink is one
  # rename(2) and cannot half-happen.
  TMPLINK="$CURRENT.new.$$"
  ln -s "$TARGET_DIR" "$TMPLINK" || die "cannot write beside $CURRENT — nothing has changed"
  mv -Tf "$TMPLINK" "$CURRENT" || { rm -f "$TMPLINK"
    die "the rename failed — $CURRENT still points at $PREV_DIR"; }
  ok "$CURRENT -> $TARGET_DIR"

  systemctl --user daemon-reload || die "daemon-reload failed — the live path moved but systemd has not read it yet.
    Point back:  bash $0 --promote $PREV_REF"
  systemctl --user restart hub || die "restart failed — the live path is already at $TARGET_DIR.
    What happened:  journalctl --user -u hub -n 40 --no-pager
    Point back:     bash $0 --promote $PREV_REF"
  info "hub user service restarted (no container was touched)"

  UP='no answer'
  for _i in $(seq 1 30); do
    sleep 0.5
    CODE=$(_http_code "http://127.0.0.1:$LIVE_PORT/api/receipt")
    if [ "$CODE" != "000" ]; then UP="$CODE"; break; fi
  done

  if [ "$UP" = "no answer" ]; then
    # Report, never repair. An automatic rollback here would hide which ref
    # broke and hand the operator a working hub with no idea why.
    echo -e "\n${RED}✗${RESET}  the hub did not answer on :$LIVE_PORT after the promote."
    echo "    what happened:  journalctl --user -u hub -n 40 --no-pager"
    echo "    point back:     bash $0 --promote $PREV_REF"
    exit 1
  fi
  ok "hub answering on :$LIVE_PORT (HTTP $UP)"

  _receipt_snapshot "http://127.0.0.1:$LIVE_PORT/api/receipt" "$AFTER"
  ok "receipt after:  $AFTER"

  python3 - "$HUB_DIR" "$REF" "$TARGET_DIR" "$PREV_REF" <<'PY' 2>/dev/null || true
import os, sys
sys.path.insert(0, os.path.join(sys.argv[1], 'hub'))
from kernel import control
control.release(sys.argv[2], 'promoted',
                preflight='', note='from %s -> %s' % (sys.argv[4], sys.argv[3]))
PY

  echo ""
  echo -e "  ${BOLD}what changed in the receipt${RESET}  (a live machine also carries clocks"
  echo    "  and usage, so read a noisy diff rather than trusting a quiet one)"
  diff -u "$BEFORE" "$AFTER" | sed -n '3,120p' | sed 's/^/      /' || true

  echo ""
  ok "promoted $REF"
  echo -e "     roll back with:  ${CYAN}bash $0 --promote $PREV_REF${RESET}"
  exit 0
fi

# ── interactive check ────────────────────────────────────────────────────────
# This script asks for a password with `read -rp`. Under `set -euo pipefail`
# and a piped stdin (curl | bash), that read hits EOF and the script dies --
# AFTER installing Docker and cloning the repo, leaving a half-built machine.
# Refuse up front instead, while nothing has been changed yet.
if [ ! -t 0 ]; then
  echo "bootstrap.sh needs an interactive terminal (it asks for an admin password)." >&2
  echo "  Download first, then run it:" >&2
  echo "    git clone https://github.com/KGSHOPINV/claude-server ~/hub && bash ~/hub/bootstrap.sh" >&2
  exit 1
fi

# ── root check ────────────────────────────────────────────────────────────────
[[ $EUID -eq 0 ]] && die "Don't run as root. Run as your normal user (with sudo access)."

# ── OS detection ─────────────────────────────────────────────────────────────
step 1 "Detecting OS"
if [ -f /etc/os-release ]; then
  . /etc/os-release
  OS_ID="${ID:-unknown}"
  OS_NAME="${PRETTY_NAME:-unknown}"
else
  die "Cannot read /etc/os-release — unsupported OS"
fi

case "$OS_ID" in
  ubuntu|debian|raspbian)
    PKG_UPDATE="sudo apt-get update -qq"
    PKG_INSTALL="sudo apt-get install -y -qq"
    ;;
  fedora|rhel|centos|rocky|almalinux)
    PKG_UPDATE="sudo dnf check-update -q || true"
    PKG_INSTALL="sudo dnf install -y -q"
    ;;
  arch|manjaro)
    PKG_UPDATE="sudo pacman -Sy --noconfirm"
    PKG_INSTALL="sudo pacman -S --noconfirm"
    ;;
  *)
    warn "Unrecognised OS: $OS_ID — attempting apt fallback"
    PKG_UPDATE="sudo apt-get update -qq"
    PKG_INSTALL="sudo apt-get install -y -qq"
    ;;
esac

ok "Detected: $OS_NAME"
info "Package manager set"

# ── system packages ───────────────────────────────────────────────────────────
step 2 "Installing system packages"
info "Updating package index..."
eval "$PKG_UPDATE"

PACKAGES="curl git python3 python3-pip ufw"
info "Installing: $PACKAGES"
eval "$PKG_INSTALL $PACKAGES"
ok "System packages ready"

# ── Docker ────────────────────────────────────────────────────────────────────
step 3 "Installing Docker"
if command -v docker &>/dev/null; then
  ok "Docker already installed ($(docker --version | cut -d' ' -f3 | tr -d ','))"
else
  info "Fetching Docker install script..."
  curl -fsSL https://get.docker.com | sudo sh
  sudo usermod -aG docker "$USER"
  ok "Docker installed"
  warn "You may need to log out and back in for Docker group to take effect"
  warn "If docker commands fail, run: newgrp docker"
fi

# Ensure Docker is running
sudo systemctl enable docker --quiet
sudo systemctl start docker
ok "Docker is running"

# ── Clone / update hub ────────────────────────────────────────────────────────
step 4 "Setting up the hub"
HUB_DIR="$HOME/hub"

if [ -d "$HUB_DIR/.git" ]; then
  # THIS DOES NOT PULL, and that is the point.
  #
  # `git pull` here puts new code underneath a hub that is running, which is the
  # one move --stage and --promote were written to replace: stage a ref on
  # :8799 against a COPY of the database, watch it answer, then move one
  # symlink. An installer that also deploys means the first machine to execute
  # new code is the one holding the data.
  #
  # It could also simply blow up. Both nodes sit on a local branch (notify-live)
  # tracking origin/deploy-notify, and fks-services has uncommitted changes — so
  # the pull either merges a branch nobody asked for or aborts, and under
  # `set -euo pipefail` aborting ends the installer HERE, after Docker has been
  # touched and before the service is written.
  HUB_SHA=$(git --no-optional-locks -C "$HUB_DIR" rev-parse --short HEAD 2>/dev/null || echo '?')
  HUB_BRANCH=$(git --no-optional-locks -C "$HUB_DIR" rev-parse --abbrev-ref HEAD 2>/dev/null || echo '?')
  HUB_DIRTY=$(git --no-optional-locks -C "$HUB_DIR" status --porcelain 2>/dev/null | wc -l | tr -d ' ')
  ok "Hub already at $HUB_DIR — $HUB_SHA on $HUB_BRANCH, left exactly as it is"
  [ "${HUB_DIRTY:-0}" != "0" ] \
    && warn "  $HUB_DIRTY uncommitted change(s) here. Nothing below touches them."
  info "  to move this node's code, prove it first, then flip one symlink:"
  info "    bash $0 --stage <ref>   then   bash $0 --promote <ref>"
else
  info "Cloning hub from GitHub..."
  git clone --quiet https://github.com/KGSHOPINV/claude-server "$HUB_DIR"
  ok "Hub cloned to $HUB_DIR"
fi

# NO pip STEP, ON PURPOSE.
#
# There used to be an `if [ -f <a pip requirements file> ]; then pip3 install`
# block here. That file has never existed anywhere in this repo, so the block
# was dead — and tools/atlas.py scored the kernel plane DONE on the strength of
# the installer MENTIONING it.
#
# The hub is standard library only. Every import under hub/ except one resolves
# in cpython's own tree; the exception is hub/launcher.py, a desktop tray icon
# that wants PIL and pystray, which the service never imports and this installer
# never runs. The dependency list this node actually has is PACKAGES= in step 2.
#
# If a Python dependency is ever genuinely needed, it does NOT come back as a
# pip3 line here. Ubuntu 24.04 and 26.04 ship PEP 668 environments, so
# `pip3 install` into the system interpreter exits non-zero with
# externally-managed-environment, and under `set -euo pipefail` that kills
# bootstrap at this line — after Docker, after the clone, with no service. Add
# the distro package to PACKAGES= above, or give the hub a venv and point
# hub.service's ExecStart at it. Both are changes to what this file installs,
# which is what --check reads, so either one stays asserted.

# The database directory the HUB ACTUALLY OPENS.
# kernel/db.py:15 resolves DB_PATH as <repo>/db/server.db. This used to create
# $HOME/db, one level too high, so the admin password seeded below went into a
# file nothing ever read and every bootstrapped node silently stood on the
# default credentials instead. Asserted now by tools/install-preflight.py.
mkdir -p "$HUB_DIR/db"

# ── Hub prompt ────────────────────────────────────────────────────────────────
echo ""
echo -e "${BOLD}Quick setup:${RESET}"

# Get server IP
SERVER_IP=$(hostname -I | awk '{print $1}')
read -rp "  Server IP address [${SERVER_IP}]: " INPUT_IP
SERVER_IP="${INPUT_IP:-$SERVER_IP}"

# Admin password
while true; do
  read -rsp "  Hub admin password: " HUB_PASSWORD
  echo ""
  read -rsp "  Confirm password: " HUB_PASSWORD2
  echo ""
  [ "$HUB_PASSWORD" = "$HUB_PASSWORD2" ] && break
  warn "Passwords don't match — try again"
done

# Hash the password in Python (no external deps). On stdin — see _pw_hash.
PW_HASH=$(_pw_hash "$HUB_PASSWORD")
[ ${#PW_HASH} -eq 64 ] || die "the password hash came back malformed — refusing to
    seed a login nobody can use. Nothing after this point has run."

# Write hub config
cat > "$HUB_DIR/db/.hub_config" <<EOF
SERVER_IP=${SERVER_IP}
HUB_PORT=8765
ADMIN_PW_HASH=${PW_HASH}
BOOTSTRAP_DATE=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
EOF
ok "Hub config written"

# Seed the admin user THROUGH kernel.db, so the schema is defined in exactly
# one place. This script used to CREATE its own users table with different
# columns (id/username/password_hash/created_at) than the one db.py inserts
# into (username/display/password_hash/role/created) -- two schemas for one
# table, in a file the hub never opened anyway.
PW_HASH="$PW_HASH" SERVER_IP="$SERVER_IP" python3 - "$HUB_DIR" <<'PYEOF'
import os, sqlite3, sys
sys.path.insert(0, os.path.join(sys.argv[1], 'hub'))
from kernel.db import DB_PATH, db_ensure_tables

db_ensure_tables()                       # the one schema definition
conn = sqlite3.connect(DB_PATH)
conn.execute("UPDATE users SET password_hash = ? WHERE username = 'admin'",
             (os.environ['PW_HASH'],))
if conn.total_changes == 0:
    conn.execute("INSERT INTO users (username, display, password_hash, role, created) "
                 "VALUES ('admin','Administrator',?,'admin',datetime('now'))",
                 (os.environ['PW_HASH'],))
conn.commit()
conn.close()
print("  Database seeded at %s" % DB_PATH)
PYEOF

# ── systemd service ───────────────────────────────────────────────────────────
step 5 "Starting hub service"
mkdir -p "$HOME/.config/systemd/user" "$HOME/.local/bin"

# The standard unit bodies are written HERE, to a scratch directory, and then
# merged into whatever the node already has. They are not written straight over
# a live unit: see _unit_merge for what that cost this fleet.
#
# They stay heredocs, and the path in each `cat >` line still ends in
# .../systemd/user/<unit>, because tools/install-check.py derives the standard
# by reading these exact lines out of this exact file. One definition of the
# standard, written once, read by the installer and by the check.
STD_DIR=$(mktemp -d "${TMPDIR:-/tmp}/hub-standard.XXXXXX") \
  || die "cannot create a scratch directory for the unit bodies"
trap 'rm -rf "$STD_DIR"' EXIT
mkdir -p "$STD_DIR/systemd/user"

cat > "$STD_DIR/systemd/user/hub.service" <<EOF
[Unit]
Description=Server Hub
After=network.target

[Service]
Type=simple
WorkingDirectory=${HUB_DIR}/hub
ExecStart=/usr/bin/python3 ${HUB_DIR}/hub/server.py
Restart=on-failure
RestartSec=5
Environment=HUB_LOCAL=1
Environment=HUB_PORT=8765

[Install]
WantedBy=default.target
EOF

# The port the standard unit actually sets, read back from the body just
# written instead of typed a second time. The ufw block below used to hardcode
# 8765 while this heredoc was the real answer, so the two could disagree.
HUB_PORT=$(sed -n 's/^Environment=HUB_PORT=//p' "$STD_DIR/systemd/user/hub.service" | head -1)
HUB_PORT="${HUB_PORT:-8765}"

UNIT_RC=0
_unit_merge "$HOME/.config/systemd/user/hub.service" \
            "$STD_DIR/systemd/user/hub.service" || UNIT_RC=$?
# 0 kept, 10 created, 11 merged. Anything else is _unit_merge failing, and a
# failure here means the node has no unit it can be trusted to be running.
case "$UNIT_RC" in
  0|10|11) : ;;
  *) die "could not bring hub.service to standard (rc $UNIT_RC). The unit on
    disk has NOT been changed — whatever was there is still there." ;;
esac

# Enable lingering so service survives logout
sudo loginctl enable-linger "$USER" 2>/dev/null || true

systemctl --user daemon-reload
systemctl --user enable hub --quiet

# Restart only when there is a reason to. A re-run that changed nothing must not
# drop a live hub's connections to prove it ran; a re-run that DID change the
# unit has to, or the running process keeps the old one.
if [ "$UNIT_RC" -eq 0 ] && systemctl --user is-active hub --quiet; then
  ok "Hub service already running on the unit it already had — not restarted"
else
  systemctl --user restart hub
  sleep 2
  if systemctl --user is-active hub --quiet; then
    ok "Hub service is running"
  else
    warn "Hub may have failed to start — check: journalctl --user -u hub -n 30"
  fi
fi

# ── Storage, backups, reclamation ─────────────────────────────────────────────
# These three were MASTER.md steps 6-8 and were never implemented. Commit
# fdc4276 -- titled "the two steps bootstrap.sh never had" -- added the scripts
# and did not touch this file, so a fresh node still received neither. Wiring
# them here is the actual fix; the scripts were only ever half of it.

step 6 "Checking storage"
if python3 "$HUB_DIR/hub/tools/storage-preflight.py" 2>/dev/null; then
  :
else
  warn "storage preflight could not run (older checkout?) — continuing"
fi

step 7 "Installing backups"
# The destination is DERIVED by the script from this machine's disks: it must
# be a different physical device from the one holding the data, or a single
# disk failure takes both. Nothing is hardcoded here on purpose.
#
# The timer is written and enabled ONLY if the script it points at is really
# there. See _install_tool: this used to swallow the copy's failure and
# schedule the timer regardless.
BACKUP_OK=1
_install_tool "$HUB_DIR/hub/tools/backup.sh"  "$HOME/.local/bin/hub-backup.sh"  || BACKUP_OK=0
RECLAIM_OK=1
_install_tool "$HUB_DIR/hub/tools/reclaim.sh" "$HOME/.local/bin/hub-reclaim.sh" || RECLAIM_OK=0

cat > "$STD_DIR/systemd/user/hub-backup.service" <<EOF
[Unit]
Description=ServerHub backup to a device that does not hold the data
[Service]
Type=oneshot
ExecStart=%h/.local/bin/hub-backup.sh
Nice=10
IOSchedulingClass=idle
EOF
cat > "$STD_DIR/systemd/user/hub-backup.timer" <<EOF
[Unit]
Description=Daily ServerHub backup
[Timer]
OnCalendar=*-*-* 03:00:00
RandomizedDelaySec=900
Persistent=true
[Install]
WantedBy=timers.target
EOF

step 8 "Installing cache reclamation"
cat > "$STD_DIR/systemd/user/hub-reclaim.service" <<EOF
[Unit]
Description=Reclaim Docker build cache older than a week
[Service]
Type=oneshot
ExecStart=%h/.local/bin/hub-reclaim.sh
Nice=15
IOSchedulingClass=idle
EOF
cat > "$STD_DIR/systemd/user/hub-reclaim.timer" <<EOF
[Unit]
Description=Weekly Docker cache reclamation
[Timer]
OnCalendar=Sun *-*-* 04:00:00
RandomizedDelaySec=1800
Persistent=true
[Install]
WantedBy=timers.target
EOF

for u in hub-backup.service hub-backup.timer hub-reclaim.service hub-reclaim.timer; do
  _unit_merge "$HOME/.config/systemd/user/$u" "$STD_DIR/systemd/user/$u" || true
done

systemctl --user daemon-reload 2>/dev/null || true

# Enabled one at a time, and only the one whose script actually landed. As one
# call, a node missing reclaim.sh got NEITHER timer and a line saying both had
# failed -- which is how a working backup ends up switched off by the failure of
# something else.
if [ "$BACKUP_OK" -eq 1 ]; then
  systemctl --user enable --now hub-backup.timer 2>/dev/null \
    && ok "backup scheduled (daily 03:00, 15min jitter)" \
    || warn "hub-backup.timer written but NOT enabled — run it and read the error:
    systemctl --user enable --now hub-backup.timer"
else
  warn "hub-backup.timer NOT enabled: hub-backup.sh is not installed (above)."
fi
if [ "$RECLAIM_OK" -eq 1 ]; then
  systemctl --user enable --now hub-reclaim.timer 2>/dev/null \
    && ok "reclamation scheduled (Sun 04:00, 30min jitter)" \
    || warn "hub-reclaim.timer written but NOT enabled — run it and read the error:
    systemctl --user enable --now hub-reclaim.timer"
else
  warn "hub-reclaim.timer NOT enabled: hub-reclaim.sh is not installed (above)."
fi

# ── Finished? ─────────────────────────────────────────────────────────────────
# The installer does not get to declare itself done. It asks.
echo ""
python3 "$HUB_DIR/hub/tools/install-preflight.py" 2>/dev/null || true

# ── UFW ───────────────────────────────────────────────────────────────────────
# Adds the two rules. Does NOT switch the firewall on — _firewall says why, and
# what one command would have done to every other service on this box.
_firewall "$HUB_PORT" 1

# ── Enrolment ─────────────────────────────────────────────────────────────────
# THE PREMISE: install -> hostname -> reachable, as ONE operation.
#
# bootstrap and enroll were two commands, so a fresh server ended at "installed,
# now go configure Cloudflare" -- which plan/BUILT-VS-ASKED.md names as the
# thing that has never once been attempted in code. This closes it.
#
# Skipped, never failed, when the zone or the token is absent. A server with a
# working hub and no public hostname is a correct outcome; refusing to finish
# bootstrap because Cloudflare was not configured would make the common case
# depend on the optional one.
step 9 "Enrolment"
ZONE_FILE="$HOME/.flare/zone"
ENROLL_ZONE="${FLARE_ZONE:-}"
[ -z "$ENROLL_ZONE" ] && [ -r "$ZONE_FILE" ] && ENROLL_ZONE=$(cat "$ZONE_FILE" 2>/dev/null | tr -d '
')

HAVE_TOKEN=0
[ -n "${CF_API_TOKEN:-}" ] && HAVE_TOKEN=1
[ -r "$HOME/.cf-token" ] && HAVE_TOKEN=1
[ -r /etc/flare/token ] && HAVE_TOKEN=1

if [ -z "$ENROLL_ZONE" ]; then
  warn "no zone — skipping. Set FLARE_ZONE or write it to ~/.flare/zone, then:"
  warn "  ./enroll.sh --zone <yourzone>"
elif [ "$HAVE_TOKEN" = "0" ]; then
  warn "no Cloudflare token — skipping. Put it at ~/.cf-token (chmod 600), then:"
  warn "  ./enroll.sh --zone ${ENROLL_ZONE}"
elif [ ! -x "$(dirname "$0")/enroll.sh" ] && [ ! -f "$(dirname "$0")/enroll.sh" ]; then
  warn "enroll.sh not beside bootstrap.sh — skipping"
else
  ok "zone ${ENROLL_ZONE}, token present — enrolling"
  bash "$(dirname "$0")/enroll.sh" --zone "$ENROLL_ZONE" ||     warn "enrolment did not complete — the hub is still up; re-run ./enroll.sh"
fi

# The hostname this node ended with, if any. Printed below so the operator sees
# a live address rather than being told to go and find one.
PUBLIC_HOST=""
if [ -r "$HOME/.flare/node.json" ]; then
  PUBLIC_HOST=$(python3 -c "import json;print((json.load(open('$HOME/.flare/node.json')) or {}).get('hostname',''))" 2>/dev/null || echo "")
fi

# ── Done ─────────────────────────────────────────────────────────────────────
echo -e "
${BOLD}${GREEN}  ══════════════════════════════════════════${RESET}
${BOLD}${GREEN}  ✓  Hub is live${RESET}

  ${BOLD}Open in your browser:${RESET}
  ${CYAN}  http://${SERVER_IP}:${HUB_PORT}${RESET}${PUBLIC_HOST:+
  ${CYAN}  https://${PUBLIC_HOST}${RESET}  (public, behind Cloudflare Access)}

  ${BOLD}Login:${RESET}
    Username:  admin
    Password:  (what you just set)

  ${BOLD}Next steps — from inside the hub:${RESET}
    → Run the full stack installer (scripts 01–16)
    → Configure port lanes
    → Set up alerts

  ${BOLD}SSH command log:${RESET}
    journalctl --user -u hub -f

${BOLD}${GREEN}  ══════════════════════════════════════════${RESET}
"
