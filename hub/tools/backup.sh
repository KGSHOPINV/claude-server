#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# 20404708  tools/backup.sh — the backup step bootstrap.sh never had
#
# MASTER.md lists "7. Backup — set up before adding data". bootstrap.sh is 241
# lines and implements five steps, none of them this one. ksgcohub therefore ran
# from install with no backups at all, while a 458GB disk sat 99% empty.
#
# Backs up to the DATA disk, which must be a different physical device from the
# one holding the data. A copy on the same disk survives a bad rm and nothing
# else.
#
# WHAT IT COPIES
#   docker named volumes     minus any whose name contains "cache"
#   docker bind mounts       every bind a running container declares, minus
#                            /proc /sys /dev /etc /run /usr /lib /bin /sbin
#   /srv/docker              compose files and configs, minus */data and .env
#   db/server.db             via the sqlite3 backup API, never cp
#   db/control.db            likewise — the registry, bulletins, acks, releases
#
# WHAT IT REFUSES, and each of these is a decision written down rather than an
# omission discovered later:
#   volumes named *cache*    regenerable. On ksgcohub netdata_netdata-cache is
#                            1.6GB versus babyhelp-data at 1.0MB — a naive
#                            "every volume" job copies the 1.6GB nightly and
#                            the 1MB you would actually mourn once.
#   db/bank.db               SECRETS. See the BANK_DB block below for the
#                            ruling and its reasons. Never add a db/*.db sweep.
#   ~/.flare/svctoken.json   the Access service token, same class.
#   */.env                   already excluded from the configs tar.
# The refusals are printed on every run and recorded in the set's MANIFEST.txt,
# because a set that silently omits something reads exactly like a set that
# lost it.
#
#   ./backup.sh              run a backup
#   ./backup.sh --dry-run    list what would be backed up, touch nothing
#
# Reads only. It never stops a container: Docker volumes are tarred in place.
# ─────────────────────────────────────────────────────────────────────────────
set -uo pipefail

# Derived, not hardcoded. The first version of this script defaulted to
# /srv/data/backups -- which on ksgcohub is the SAME PHYSICAL DEVICE as the
# data root, so one disk failure would have taken the data and its only backup
# together. kernel/storage.py already knows which device holds the data and
# which does not; ask it rather than guessing, the same way /api/admit derives
# the data path instead of assuming one.
_derive_dest() {
  python3 - <<'PY' 2>/dev/null
import os, sys
# This script may be invoked from ~/.local/bin, from the repo, or from a
# worktree, so locate the package rather than assuming one layout.
for _p in (os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
           if '__file__' in dir() else '',
           os.path.expanduser('~/hub/hub'),
           os.path.expanduser('~/hub')):
    if _p and os.path.isdir(os.path.join(_p, 'kernel')):
        sys.path.insert(0, _p)
        break
try:
    from kernel import storage as st
    bt = st.backup_target()
    print(bt['path'] if bt.get('dedicated') else '')
except Exception:
    print('')
PY
}
DEST_ROOT="${BACKUP_DEST:-$(_derive_dest)}"
if [ -z "$DEST_ROOT" ]; then
  echo "no valid backup target: every mount shares a device with the data." >&2
  echo "Set BACKUP_DEST explicitly if you accept that limitation." >&2
  exit 1
fi
KEEP="${BACKUP_KEEP:-14}"
HUB_DB="${HUB_DB:-$HOME/hub/db/server.db}"
# kernel/control.py keeps control.db beside server.db and reads this same
# override, so a hub pointed at another file is still the file backed up here.
# Derived the same way as HUB_DB rather than a second convention: two ways of
# naming one file is how the backup ends up copying the database nobody uses.
CONTROL_DB="${HUB_CONTROL_DB:-$HOME/hub/db/control.db}"
DOCKER_ROOT="${HUB_DOCKER_ROOT:-/srv/docker}"
VOL_ROOT=/var/lib/docker/volumes

# ── db/bank.db — NAMED HERE SO THAT REFUSING IT IS A DECISION ────────────────
# Read kernel/bank.py before changing anything below it. Its header says, of
# "never backed up":
#
#     BY ACCIDENT OF SCOPE, NOT BY AN EXCLUSION. [...] Add a db/*.db sweep to
#     backup.sh and the secrets start being copied, silently.
#
# That accident is closed here. bank.db is named, and named in order to be
# refused, so the next person who wants "just back up db/" has to read why not
# instead of discovering it afterwards.
#
# THE RULING: bank.db is NOT copied. Four reasons, in the order they matter.
#
#   1. Everything in it is designed to be gone within a day. Project-scope
#      slots are deleted the moment they are collected; every slot carries a
#      24h TTL. KEEP is 14, so a nightly sweep of db/ would hold fourteen
#      copies of a secret whose entire safety argument is that it expires. The
#      backup would outlive the thing it copied by two weeks, every night.
#
#   2. Losing it costs one paste. bank.db holds a handoff IN TRANSIT — a token
#      on its way from the operator's desktop to a project. If the disk dies
#      mid-handoff the operator re-deposits it; they still have it, that is
#      what a handoff means. Compare control.db above, which holds what nothing
#      can re-derive. That asymmetry is the whole argument: this file copies
#      what cannot be got back, and a secret you can simply paste again is not
#      that.
#
#   3. The encryption is not a licence to copy it. kernel/bank.py's _key() is
#      sha256(db/.bank-salt + /etc/machine-id), and .bank-salt sits in the same
#      directory as bank.db. Tar that directory and the archive carries both
#      halves of the key for anyone who can also read /etc/machine-id — which
#      is every process on the box. bank.py says this plainly: the encryption
#      protects a copy that LEAVES the machine, it does not make a local copy
#      safe. A backup set is a local copy, fourteen of them, on a second disk.
#
#   4. The exception is only tolerable while it is loud. exception_open() fails
#      install-preflight for as long as the bank holds anything, so the
#      operator is pushed to empty it. A backup quietly re-creating the
#      contents on restore turns a 24h exception into an indefinite one.
#
# HOW IT IS ANNOUNCED. Silence would leave the same hole pointing the other
# way: an operator restoring a set could believe the secrets came back. So the
# run SAYS bank.db was refused, says whether it was holding anything at the
# time, and the MANIFEST records the exclusion — a restorer reads what is NOT
# in a set from the set itself, not from this file.
#
# The count is read through sqlite in read-only mode and is a COUNT. No slot
# name, no note, and certainly no blob is read, logged or written anywhere.
BANK_DB="${HUB_BANK_DB:-$HOME/hub/db/bank.db}"

# ~/.flare/svctoken.json is the other credential on this box, and it is not
# here for the same reason by a different route: kernel/svctoken.py keeps it
# 0600 outside db/ deliberately, and nothing in this script walks ~/.flare. It
# is named in the manifest so the gap is stated rather than assumed.
SVCTOKEN="${HUB_SVCTOKEN:-$HOME/.flare/svctoken.json}"

# 20404739  _bank_holding — how many slots, and nothing else about them
_bank_holding() {
  [ -f "$BANK_DB" ] || { echo "absent"; return; }
  python3 - "$BANK_DB" <<'PY' 2>/dev/null || echo "present, contents unreadable"
import sqlite3, sys
try:
    c = sqlite3.connect('file:%s?mode=ro' % sys.argv[1], uri=True)
    n = c.execute('SELECT COUNT(*) FROM secrets').fetchone()[0]
    c.close()
except Exception:
    print('present, contents unreadable')
else:
    print('present, holding %d slot(s)' % n)
PY
}

DRY=0
[ "${1:-}" = "--dry-run" ] && DRY=1

# Volumes live under root-owned paths, so this script needs passwordless sudo.
# Check ONCE, loudly. The first version tested `sudo -n` per volume and fell
# through to `continue` on failure, so on a host where sudo prompts every volume
# was silently skipped.
#
# CORRECTION (2026-09-23): commit b5d9fb6's message overstated what followed.
# It claimed the run then "exited 0 while deleting the oldest real backup".
# A reviewing agent checked and it was wrong: /srv/docker exists on both real
# servers (verified), so the configs tar would also fail, set FAILED=1, skip
# retention and exit 1. The silent-success-then-prune path needs a host with no
# /srv/docker AND no readable hub database — neither machine here.
#
# The real defect was smaller and still worth fixing: a run that backed up
# almost nothing reported a specific failure rather than the actual problem
# (it cannot read its sources at all), and it did that AFTER attempting every
# volume instead of stopping at the first sign. Fail fast, say why.
#
# Recording the correction rather than quietly editing it: a commit message
# that overstates a bug is still a record disagreeing with the machine, and
# being harsh about my own code does not exempt it from being accurate.
CAN_SUDO=1
if ! sudo -n true 2>/dev/null; then
  CAN_SUDO=0
fi

# REVISED 2026-09-24. The previous version exited 1 here when sudo prompts,
# which was right about not pretending and wrong about the consequence: on
# fks-services it meant NOTHING was backed up at all while waiting for a sudo
# grant -- including Metaforge's 45-file schema and two months of FlareVault
# state, both of which are readable without root.
#
# Refusing entirely is only correct when nothing can be read. Otherwise: back
# up what is reachable, and say loudly and specifically what is not. A partial
# backup that names its own gaps beats no backup, and beats a full-looking one
# that hides them.
if [ "$CAN_SUDO" = "0" ] && [ "$DRY" = "0" ]; then
  echo "backup.sh: no passwordless sudo — Docker NAMED VOLUMES cannot be read." >&2
  echo "  Proceeding with readable sources only. Volumes will be listed as EXPOSED." >&2
  # ${USER:-...} because this file runs under `set -u` and $USER is not always
  # exported -- reproduced 2026-09-24: the script aborted on this very line,
  # i.e. the advice line about a degraded run killed the degraded run.
  echo "  To cover them:  echo '${USER:-$(id -un)} ALL=(ALL) NOPASSWD: /usr/bin/tar' | sudo tee /etc/sudoers.d/hub-backup" >&2
fi

# A helper image needs only tar and a shell. Prefer one already pulled, so a
# backup never depends on the network: a node that cannot reach a registry must
# still be able to protect its data.
HELPER_IMAGE=""
CAN_DOCKER_READ=0
if [ "$CAN_SUDO" = "0" ] && docker ps -q >/dev/null 2>&1; then
  for img in alpine:latest busybox:latest alpine busybox; do
    if docker image inspect "$img" >/dev/null 2>&1; then
      HELPER_IMAGE="$img"; CAN_DOCKER_READ=1; break
    fi
  done
fi

# read_dir — can this process read the directory, with or without sudo?
read_dir() {
  if [ "$CAN_SUDO" = "1" ]; then sudo -n test -d "$1" 2>/dev/null
  else test -r "$1" -a -d "$1" 2>/dev/null; fi
}
# NEVER_TAR — the secrets, refused at every route into an archive.
#
# The BANK_DB block above refuses to copy bank.db as a named source. That is
# only one of the ways it could get into a set. Bind-mount ~/hub/db into any
# container and the bind loop below tars the whole directory — bank.db AND the
# .bank-salt that is half its key, in one archive, with no line anywhere saying
# it happened. Nothing does that today. "Nothing does that today" is how
# bank.py came to describe its own protection as an accident of scope.
#
# So the refusal is a property of tarring, not of one call site. GNU tar
# matches a bare --exclude name at any depth, so this holds for a directory
# three levels above them as well as for their own.
NEVER_TAR="--exclude=bank.db --exclude=.bank-salt --exclude=svctoken.json"

# tar_dir — same call either way, so the callers below do not branch
tar_dir() {
  if [ "$CAN_SUDO" = "1" ]; then
    # shellcheck disable=SC2086  # NEVER_TAR is a word list on purpose
    sudo -n tar czf "$1" $NEVER_TAR -C "$2" . 2>"${3:-/dev/null}" </dev/null
  else
    # shellcheck disable=SC2086
    tar czf "$1" $NEVER_TAR -C "$2" . 2>"${3:-/dev/null}" </dev/null
  fi
}
# sqlite_copy — sqlite3's backup API rather than cp or tar. The hub is running
# and writing while this runs, and a database file copied mid-write is corrupt
# in a way that looks fine until the day you need it. One helper, so a second
# database cannot end up copied by a weaker method than the first.
sqlite_copy() {
  python3 - "$1" "$2" <<'PY' 2>/dev/null
import sqlite3, sys
src = sqlite3.connect('file:%s?mode=ro' % sys.argv[1], uri=True)
dst = sqlite3.connect(sys.argv[2])
with dst:
    src.backup(dst)
dst.close(); src.close()
PY
}

STAMP=$(date +%F)
DEST="$DEST_ROOT/$STAMP"
LOG="$DEST_ROOT/backup.log"
FAILED=0
ATTEMPTED=0
WROTE=0
HOT=0
EXPOSED=0

say() { echo "$(date +%T) $*" | tee -a "$LOG" 2>/dev/null || echo "$(date +%T) $*"; }

# 20404740  _assert_dest — the destination is checked in BOTH modes, before anything
#
# WHAT THIS COSTS WHEN IT IS MISSING. On fks-services the derived target is
# /backup on /dev/sdb1 — 4.4TB, 0% used — and it is owned root:root 0755, so
# the hub user cannot create a directory in it. Verified 2026-09-28: `test -w
# /backup` is false for admin1. Install the timer on that box as it stands and
# every night at 03:00 the run dies on `mkdir -p`, writes nothing, and the
# operator finds out the day they need a restore.
#
# The old code checked this with `mkdir -p "$DEST" || echo "cannot write $DEST"`
# inside the non-dry branch, which was wrong twice: --dry-run — the one mode
# you would use to look before scheduling — never asked the question at all, and
# the message named a directory without saying who owns the one above it or
# what single command fixes it. A refusal that does not carry its own fix gets
# read as "backups are hard" rather than "run this line".
_assert_dest() {
  if [ ! -d "$DEST_ROOT" ]; then
    PARENT=$(dirname "$DEST_ROOT")
    # --dry-run must not create it. A dry run that quietly makes a directory is
    # a dry run you cannot trust about anything else it claims not to do, so
    # the question is ASKED rather than answered by trying.
    if [ "$DRY" = "1" ]; then
      [ -w "$PARENT" ] && { echo "  dest  $DEST_ROOT (would be created)"; return 0; }
      echo "backup.sh: $DEST_ROOT does not exist and $PARENT is not writable" >&2
      echo "  by $(id -un). Nothing would be backed up." >&2
      echo "  Fix:  sudo install -d -o $(id -un) -g $(id -gn) -m 755 $DEST_ROOT" >&2
      return 1
    fi
    # The parent may itself be unwritable, in which case mkdir -p on DEST_ROOT
    # is the failure, not the symptom. Say which.
    mkdir -p "$DEST_ROOT" 2>/dev/null || {
      echo "backup.sh: $DEST_ROOT does not exist and cannot be created." >&2
      echo "  Owner of $PARENT: $(stat -c '%U:%G %a' "$PARENT" 2>/dev/null || echo unknown)" >&2
      echo "  Fix:  sudo install -d -o $(id -un) -g $(id -gn) -m 755 $DEST_ROOT" >&2
      return 1
    }
  fi
  [ -w "$DEST_ROOT" ] || {
    echo "backup.sh: $DEST_ROOT is not writable by $(id -un)." >&2
    echo "  It is $(stat -c 'owned %U:%G mode %a' "$DEST_ROOT" 2>/dev/null || echo 'of unknown ownership')," >&2
    echo "  on device $(findmnt -no SOURCE --target "$DEST_ROOT" 2>/dev/null || echo unknown)." >&2
    echo "  Nothing has been written. This is the whole backup, not one source." >&2
    echo "  Fix:  sudo chown $(id -un):$(id -gn) $DEST_ROOT" >&2
    return 1
  }
  return 0
}

_assert_dest || exit 1

if [ "$DRY" = "0" ]; then
  mkdir -p "$DEST" || { echo "cannot write $DEST"; exit 1; }
  say "=== backup start -> $DEST"
else
  echo "DRY RUN — nothing will be written"
  echo "  dest  $DEST_ROOT (writable)"
fi

# ── Docker volumes ───────────────────────────────────────────────────────────
# Tarred from the host rather than through a helper container: spawning one
# would appear in docker ps and pollute the container list the hub reports
# about itself.
for vol in $(docker volume ls -q 2>/dev/null); do
  case "$vol" in
    *cache*) [ "$DRY" = "1" ] && echo "  skip  $vol  (cache — regenerable)"; continue;;
  esac
  ATTEMPTED=$((ATTEMPTED + 1))
  src="$VOL_ROOT/$vol/_data"
  if [ "$DRY" = "1" ]; then
    echo "  back  $vol"
    continue
  fi
  # An unreadable source is a FAILURE, not something to skip past. A volume
  # that exists and cannot be read is exactly the case worth shouting about.
  if ! read_dir "$src"; then
    # No host sudo: read the volume through a throwaway container instead.
    # Docker mounts it as root inside, so the data is reachable without any
    # privilege on the host — only membership of the docker group, which the
    # hub user already needs to do its job.
    #
    # This was rejected earlier on the grounds that spawning a container
    # pollutes the container list the hub reports about itself. That was a bad
    # trade: it left 21 volumes on fks-services unbacked, including two months
    # of FlareVault state, to keep `docker ps` tidy for a few seconds. The
    # container is --rm and lives for the length of one tar.
    if [ "$CAN_SUDO" = "0" ] && [ "$CAN_DOCKER_READ" = "1" ]; then
      if docker run --rm -v "$vol":/src:ro -v "$DEST":/dst "$HELPER_IMAGE" \
           tar czf "/dst/vol-$vol.tar.gz" $NEVER_TAR -C /src . 2>/dev/null; then
        say "  ok   vol $vol (via container)"; WROTE=$((WROTE + 1)); continue
      fi
      say "  FAIL vol $vol — container read failed"; FAILED=1; continue
    fi
    if [ "$CAN_SUDO" = "0" ]; then
      say "  EXPOSED vol $vol — no sudo and no usable helper image, NOT backed up"
      EXPOSED=$((EXPOSED + 1)); continue
    fi
    say "  FAIL vol $vol — source unreadable at $src"; FAILED=1; continue
  fi
  if tar_dir "$DEST/vol-$vol.tar.gz" "$src"; then
    say "  ok   vol $vol"; WROTE=$((WROTE + 1))
  else
    say "  FAIL vol $vol"; FAILED=1
  fi
done

# ── Bind-mounted project data ────────────────────────────────────────────────
# Named volumes were the only thing backed up until 2026-09-24, which missed
# every project that bind-mounts its data instead. On ksgcohub that was:
#
#   n8n        /srv/data/n8n
#   surrealdb  /srv/data/surrealdb
#   fks-api    /srv/docker/fksinv/data     (also hit by --exclude='*/data')
#
# and the run still LOOKED successful, because orphaned named volumes with
# matching names (n8n_n8n-data, surrealdb_surrealdb-data, 0 links) were being
# tarred instead. It backed up the dead copies and skipped the live ones.
#
# Worse, /api/admit tells every new project to put its data at
# /srv/data/<project> -- a bind mount. The contract and the backup disagreed.
#
# So: ask Docker where every container actually keeps its data, and back that
# up. Derived from the machine, like everything else here.
SKIP_BINDS='^/(proc|sys|dev|etc|run|var/run|usr|lib|bin|sbin)($|/)'
for src in $(docker ps -q 2>/dev/null | xargs -r -I{} docker inspect {} \
      --format '{{range .Mounts}}{{if eq .Type "bind"}}{{.Source}}{{"\n"}}{{end}}{{end}}' \
      2>/dev/null | sort -u); do
  [ -n "$src" ] || continue
  echo "$src" | grep -qE "$SKIP_BINDS" && continue    # docker.sock, /proc, /sys …
  read_dir "$src" || continue                         # a bind to a FILE is config, not data
  ATTEMPTED=$((ATTEMPTED + 1))
  name=$(echo "${src#/}" | tr '/' '-')
  if [ "$DRY" = "1" ]; then
    echo "  back  $src  (bind mount)"
    continue
  fi
  # tar's exit codes are NOT the same failure. 1 means "a file changed while I
  # was reading it" -- the archive exists but a live database copied that way
  # may not restore. 2 is a real failure. Treating them alike either loses a
  # usable backup or, worse, reports a hot-copied database as clean.
  #
  # SurrealDB is the live example: its write-ahead log changes mid-read, so
  # /srv/data/surrealdb produced a valid-looking 18MB archive AND exit 1.
  #
  # This is where recognition would earn its keep -- a known database should be
  # dumped by its own tool rather than tarred from underneath. Until then, say
  # plainly that the copy is hot, instead of implying it is trustworthy.
  tar_dir "$DEST/bind-$name.tar.gz" "$src" "$DEST/.tarerr"
  rc=$?
  if [ "$rc" = "0" ]; then
    say "  ok   bind $src"; WROTE=$((WROTE + 1))
  elif [ "$rc" = "1" ]; then
    changed=$(head -1 "$DEST/.tarerr" 2>/dev/null | sed 's/^tar: //')
    say "  HOT  bind $src — captured, but written during the copy ($changed)"
    say "       a live database copied this way may not restore"
    WROTE=$((WROTE + 1)); HOT=$((HOT + 1))
  else
    say "  FAIL bind $src (tar exit $rc)"; FAILED=1
  fi
  rm -f "$DEST/.tarerr"
done

# ── Compose files and project configs ────────────────────────────────────────
if [ -d "$DOCKER_ROOT" ]; then
  if [ "$DRY" = "1" ]; then
    echo "  back  $DOCKER_ROOT (compose files, .env excluded)"
  elif sudo -n tar czf "$DEST/docker-configs.tar.gz" \
        --exclude='*/data' --exclude='.env' $NEVER_TAR -C "$DOCKER_ROOT" . 2>/dev/null; then
    say "  ok   $DOCKER_ROOT"
  else
    say "  FAIL $DOCKER_ROOT"; FAILED=1
  fi
fi

# ── Hub database ─────────────────────────────────────────────────────────────
if [ -f "$HUB_DB" ]; then
  ATTEMPTED=$((ATTEMPTED + 1))
  if [ "$DRY" = "1" ]; then
    echo "  back  $HUB_DB (hot backup via sqlite3 API)"
  elif sqlite_copy "$HUB_DB" "$DEST/hub-server.db"; then
    say "  ok   hub database"; WROTE=$((WROTE + 1))
  else
    say "  FAIL hub database"; FAILED=1
  fi
fi

# ── Control database ─────────────────────────────────────────────────────────
# Everything else in this script is a copy of something the machine could hand
# back: volumes, bind mounts and compose files all still exist to be re-read.
# control.db is the one file here that holds what NOTHING can re-derive -- the
# claims projects filed, the masters they acknowledged, and the release history.
# `docker ps` can tell you what is running; it cannot tell you which ref a
# project agreed to, or which release was last promoted, which is precisely
# what a rollback has to know. Losing this file means losing what to roll back
# TO, and no amount of reading the machine gets it back.
#
# It was not backed up until 2026-09-24 -- the same class of gap as the one in
# this file's header, where the step was believed to be covered because a
# neighbouring step was.
if [ -f "$CONTROL_DB" ]; then
  ATTEMPTED=$((ATTEMPTED + 1))
  if [ "$DRY" = "1" ]; then
    echo "  back  $CONTROL_DB (hot backup via sqlite3 API)"
  elif sqlite_copy "$CONTROL_DB" "$DEST/hub-control.db"; then
    say "  ok   control database"; WROTE=$((WROTE + 1))
  else
    say "  FAIL control database"; FAILED=1
  fi
fi

# ── Secrets: refused out loud ────────────────────────────────────────────────
# See the BANK_DB block at the top for the ruling and its four reasons. This is
# the half that makes the ruling visible on the night it applies: a set that
# silently omits something is indistinguishable from a set that lost it.
BANK_STATE=$(_bank_holding)
SVCTOKEN_STATE="absent"
[ -f "$SVCTOKEN" ] && SVCTOKEN_STATE="present"
if [ "$DRY" = "1" ]; then
  echo "  SKIP  $BANK_DB — secrets, deliberately not copied ($BANK_STATE)"
  echo "  SKIP  $SVCTOKEN — Access service token, deliberately not copied ($SVCTOKEN_STATE)"
else
  say "  SKIP secrets: bank.db $BANK_STATE — deliberately NOT copied (kernel/bank.py)"
  case "$BANK_STATE" in
    present,*holding\ 0\ slot*|absent) : ;;
    present*)
      say "       the bank is holding something. It expires on its own; a"
      say "       restore of this set will NOT bring it back. Collect it."
      ;;
  esac
fi

[ "$DRY" = "1" ] && exit 0

# ── Manifest ─────────────────────────────────────────────────────────────────
# `excluded` is a first-class line, not a footnote. The person reading this
# file is restoring, and the one thing a restore cannot discover on its own is
# what was never in the box.
{
  echo "backup      $STAMP"
  echo "host        $(hostname)"
  echo "machine_id  $(cat /etc/machine-id 2>/dev/null)"
  echo "skipped     volumes matching *cache* (regenerable)"
  echo "excluded    db/bank.db — secrets, refused by design ($BANK_STATE)"
  echo "excluded    ~/.flare/svctoken.json — Access service token ($SVCTOKEN_STATE)"
  echo "excluded    $DOCKER_ROOT/**/.env — refused by the configs tar"
  echo ""
  ls -lh "$DEST" | tail -n +2
} > "$DEST/MANIFEST.txt" 2>/dev/null

SIZE=$(du -sh "$DEST" 2>/dev/null | cut -f1)
say "=== backup done: $SIZE in $DEST"
[ "$HOT" -gt 0 ] && say "    $HOT source(s) were written during the copy — see HOT lines above"
[ "$EXPOSED" -gt 0 ] && say "    $EXPOSED source(s) NOT BACKED UP — need root. Grant NOPASSWD for tar."

# ── Retention ────────────────────────────────────────────────────────────────
# Pruned only after a successful run, so a run of failures cannot quietly age
# out the last good copy.
# Zero artifacts written is a failed backup, however quiet it was. Without this
# a run that skipped everything reports success and then prunes.
#
# The two databases COUNT toward this. Reproduced 2026-09-24: a host with no
# readable volumes and no /srv/docker copied both databases successfully and
# then printed "attempted 0 sources, wrote 0. Not a backup." and exited 1 --
# having just backed up the only two files on the machine that cannot be
# re-derived. A verdict that is wrong in the safe direction is still a verdict
# operators learn to ignore, and this one arrives by systemd timer.
if [ "$WROTE" = "0" ]; then
  say "  FAIL — attempted $ATTEMPTED sources, wrote 0. Not a backup."
  FAILED=1
fi

if [ "$FAILED" = "0" ]; then
  ls -1d "$DEST_ROOT"/20* 2>/dev/null | sort | head -n -"$KEEP" | while read -r old; do
    rm -rf "$old" && say "  pruned $old"
  done
else
  say "  retention skipped — this run had failures, keeping every copy"
fi

exit $FAILED
