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
# What it skips, and why that matters: volumes whose name contains "cache".
# On ksgcohub that is netdata_netdata-cache at 1.6GB -- versus babyhelp-data at
# 1.0MB. A naive "back up every volume" job copies 1.6GB of regenerable cache
# nightly and 1MB of the thing you would actually mourn.
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
DOCKER_ROOT="${HUB_DOCKER_ROOT:-/srv/docker}"
VOL_ROOT=/var/lib/docker/volumes

DRY=0
[ "${1:-}" = "--dry-run" ] && DRY=1

STAMP=$(date +%F)
DEST="$DEST_ROOT/$STAMP"
LOG="$DEST_ROOT/backup.log"
FAILED=0

say() { echo "$(date +%T) $*" | tee -a "$LOG" 2>/dev/null || echo "$(date +%T) $*"; }

if [ "$DRY" = "0" ]; then
  mkdir -p "$DEST" || { echo "cannot write $DEST"; exit 1; }
  say "=== backup start -> $DEST"
else
  echo "DRY RUN — nothing will be written"
fi

# ── Docker volumes ───────────────────────────────────────────────────────────
# Tarred from the host rather than through a helper container: spawning one
# would appear in docker ps and pollute the container list the hub reports
# about itself.
for vol in $(docker volume ls -q 2>/dev/null); do
  case "$vol" in
    *cache*) [ "$DRY" = "1" ] && echo "  skip  $vol  (cache — regenerable)"; continue;;
  esac
  src="$VOL_ROOT/$vol/_data"
  sudo -n test -d "$src" 2>/dev/null || continue
  if [ "$DRY" = "1" ]; then
    echo "  back  $vol"
    continue
  fi
  if sudo -n tar czf "$DEST/vol-$vol.tar.gz" -C "$src" . 2>/dev/null; then
    say "  ok   vol $vol"
  else
    say "  FAIL vol $vol"; FAILED=1
  fi
done

# ── Compose files and project configs ────────────────────────────────────────
if [ -d "$DOCKER_ROOT" ]; then
  if [ "$DRY" = "1" ]; then
    echo "  back  $DOCKER_ROOT (compose files, .env excluded)"
  elif sudo -n tar czf "$DEST/docker-configs.tar.gz" \
        --exclude='*/data' --exclude='.env' -C "$DOCKER_ROOT" . 2>/dev/null; then
    say "  ok   $DOCKER_ROOT"
  else
    say "  FAIL $DOCKER_ROOT"; FAILED=1
  fi
fi

# ── Hub database ─────────────────────────────────────────────────────────────
# sqlite3's backup API rather than cp: the hub is running and writing, and a
# copied file mid-write is a corrupt file that looks fine until you need it.
if [ -f "$HUB_DB" ]; then
  if [ "$DRY" = "1" ]; then
    echo "  back  $HUB_DB (hot backup via sqlite3 API)"
  elif python3 - "$HUB_DB" "$DEST/hub-server.db" <<'PY' 2>/dev/null
import sqlite3, sys
src = sqlite3.connect('file:%s?mode=ro' % sys.argv[1], uri=True)
dst = sqlite3.connect(sys.argv[2])
with dst:
    src.backup(dst)
dst.close(); src.close()
PY
  then
    say "  ok   hub database"
  else
    say "  FAIL hub database"; FAILED=1
  fi
fi

[ "$DRY" = "1" ] && exit 0

# ── Manifest ─────────────────────────────────────────────────────────────────
{
  echo "backup      $STAMP"
  echo "host        $(hostname)"
  echo "machine_id  $(cat /etc/machine-id 2>/dev/null)"
  echo "skipped     volumes matching *cache* (regenerable)"
  echo ""
  ls -lh "$DEST" | tail -n +2
} > "$DEST/MANIFEST.txt" 2>/dev/null

SIZE=$(du -sh "$DEST" 2>/dev/null | cut -f1)
say "=== backup done: $SIZE in $DEST"

# ── Retention ────────────────────────────────────────────────────────────────
# Pruned only after a successful run, so a run of failures cannot quietly age
# out the last good copy.
if [ "$FAILED" = "0" ]; then
  ls -1d "$DEST_ROOT"/20* 2>/dev/null | sort | head -n -"$KEEP" | while read -r old; do
    rm -rf "$old" && say "  pruned $old"
  done
else
  say "  retention skipped — this run had failures, keeping every copy"
fi

exit $FAILED
