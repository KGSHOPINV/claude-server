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
step() { echo -e "\n${BOLD}${BLUE}[$1/8]${RESET} ${BOLD}$2${RESET}"; }

# ── banner ────────────────────────────────────────────────────────────────────
echo -e "
${BOLD}${CYAN}  ╔══════════════════════════════════════╗
  ║       Server Kit — Bootstrap         ║
  ║   Hub will be live at :8765          ║
  ╚══════════════════════════════════════╝${RESET}
"

# ── --check: converge, do not install ────────────────────────────────────────
# An installer that can only run on a bare machine is a one-shot script. This
# one answers "is this node finished?" on any box, at any time, changing
# nothing -- so the gap between what was documented and what was done stops
# being invisible.
if [ "${1:-}" = "--check" ]; then
  HUB_DIR="${HUB_DIR:-$HOME/hub}"
  exec python3 "$HUB_DIR/hub/tools/install-preflight.py" "${2:---strict}"
fi

# ── --stage / --promote: an upgrade you can look at before you take it ───────
# 20404712  release verbs — stage a ref beside the live hub, then point at it
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

    # Reported, not installed. Installing into the shared site-packages would
    # change the dependencies under the RUNNING hub, which is the one thing
    # --stage promises not to do. The boot above already answered the question
    # empirically: it ran against this machine's existing packages.
    REQNOTE='unchanged'
    if ! diff -q "$HUB_DIR/hub/requirements.txt" "$STAGE/hub/requirements.txt" >/dev/null 2>&1; then
      REQNOTE='DIFFERS'
      warn "requirements.txt differs from the live checkout:"
      diff -u "$HUB_DIR/hub/requirements.txt" "$STAGE/hub/requirements.txt" \
        2>/dev/null | sed -n '3,20p' | sed 's/^/      /' || true
      info "if the boot above failed on an import:  pip3 install -r $STAGE/hub/requirements.txt"
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
requirements=$REQNOTE
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
    echo -e "  ${BOLD}deps${RESET}        requirements $REQNOTE"
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
  # 20404713  promote — one rename, then one user service restarts
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
  info "Hub already cloned — pulling latest..."
  git -C "$HUB_DIR" pull --quiet
  ok "Hub updated"
else
  info "Cloning hub from GitHub..."
  git clone --quiet https://github.com/KGSHOPINV/claude-server "$HUB_DIR"
  ok "Hub cloned to $HUB_DIR"
fi

# Python dependencies
if [ -f "$HUB_DIR/hub/requirements.txt" ]; then
  info "Installing Python dependencies..."
  pip3 install -q -r "$HUB_DIR/hub/requirements.txt"
  ok "Python deps installed"
fi

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

# Hash the password in Python (no external deps)
PW_HASH=$(python3 -c "import hashlib; print(hashlib.sha256('${HUB_PASSWORD}'.encode()).hexdigest())")

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

cat > "$HOME/.config/systemd/user/hub.service" <<EOF
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

# Enable lingering so service survives logout
sudo loginctl enable-linger "$USER" 2>/dev/null || true

systemctl --user daemon-reload
systemctl --user enable hub --quiet
systemctl --user restart hub
sleep 2

# Verify it started
if systemctl --user is-active hub --quiet; then
  ok "Hub service is running"
else
  warn "Hub may have failed to start — check: journalctl --user -u hub -n 30"
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
install -m 755 "$HUB_DIR/hub/tools/backup.sh"  "$HOME/.local/bin/hub-backup.sh"  2>/dev/null || true
install -m 755 "$HUB_DIR/hub/tools/reclaim.sh" "$HOME/.local/bin/hub-reclaim.sh" 2>/dev/null || true

cat > "$HOME/.config/systemd/user/hub-backup.service" <<EOF
[Unit]
Description=ServerHub backup to a device that does not hold the data
[Service]
Type=oneshot
ExecStart=%h/.local/bin/hub-backup.sh
Nice=10
IOSchedulingClass=idle
EOF
cat > "$HOME/.config/systemd/user/hub-backup.timer" <<EOF
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
cat > "$HOME/.config/systemd/user/hub-reclaim.service" <<EOF
[Unit]
Description=Reclaim Docker build cache older than a week
[Service]
Type=oneshot
ExecStart=%h/.local/bin/hub-reclaim.sh
Nice=15
IOSchedulingClass=idle
EOF
cat > "$HOME/.config/systemd/user/hub-reclaim.timer" <<EOF
[Unit]
Description=Weekly Docker cache reclamation
[Timer]
OnCalendar=Sun *-*-* 04:00:00
RandomizedDelaySec=1800
Persistent=true
[Install]
WantedBy=timers.target
EOF

systemctl --user daemon-reload 2>/dev/null || true
systemctl --user enable --now hub-backup.timer hub-reclaim.timer 2>/dev/null   && ok "backup (daily 03:00) and reclamation (Sun 04:00) scheduled"   || warn "timers written but not enabled — run: systemctl --user enable --now hub-backup.timer hub-reclaim.timer"

# ── Finished? ─────────────────────────────────────────────────────────────────
# The installer does not get to declare itself done. It asks.
echo ""
python3 "$HUB_DIR/hub/tools/install-preflight.py" 2>/dev/null || true

# ── UFW ───────────────────────────────────────────────────────────────────────
if command -v ufw &>/dev/null; then
  sudo ufw allow 22/tcp   &>/dev/null  # SSH
  sudo ufw allow 8765/tcp &>/dev/null  # Hub
  sudo ufw --force enable &>/dev/null
  ok "Firewall: 22 (SSH) + 8765 (Hub) open"
fi

# ── Done ─────────────────────────────────────────────────────────────────────
echo -e "
${BOLD}${GREEN}  ══════════════════════════════════════════${RESET}
${BOLD}${GREEN}  ✓  Hub is live${RESET}

  ${BOLD}Open in your browser:${RESET}
  ${CYAN}  http://${SERVER_IP}:8765${RESET}

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
