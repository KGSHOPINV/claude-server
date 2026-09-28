#!/bin/bash
# 20404733  alert-load.sh — CPU load average check → ntfy
#
# Systemd timer: hub-load.timer. NOTHING INVOKES THIS SCRIPT TODAY. fks-services
# has hub-alert, hub-daily and hub-maintenance user units and no hub-load unit;
# ksgcohub has no alert units at all. It is fixed here because it carried the
# same closed-port default as its siblings and would have been dead on arrival
# the day someone installed the timer.
#
# Alerts only on state TRANSITIONS (ok→high or high→ok), so a box that stays
# busy does not push on every tick.
#
# THRESHOLD IS STILL A GUESS. 4 was written for a 4-core box; fks-services has
# 24 cores, where a load of 4 is idle. ~/.server-alerts.conf carries LOAD_WARN,
# but on fks that is 80 — a PERCENTAGE, not a load average, so it is not a
# drop-in and is deliberately not wired in here. The default now scales with the
# core count instead, and LOAD_THRESHOLD overrides it.
set -uo pipefail

_d="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
for _l in "$_d/ntfy-lib.sh" "$_d/../hub/scripts/ntfy-lib.sh" "$_d/hub/scripts/ntfy-lib.sh"; do
  [ -f "$_l" ] && { . "$_l"; break; }
done
command -v ntfy_push >/dev/null || { echo "[alert-load] ntfy-lib.sh not found — cannot send" >&2; exit 1; }

STATE_FILE="${ALERT_LOAD_STATE:-/tmp/.alert-load-state}"
CORES=$(nproc 2>/dev/null || echo 4)
THRESHOLD="${LOAD_THRESHOLD:-$CORES}"

LOAD=$(awk '{print $1}' /proc/loadavg)
LOAD_INT=${LOAD%%.*}

prev_state=""
[ -f "$STATE_FILE" ] && prev_state=$(cat "$STATE_FILE")

if [ "$LOAD_INT" -ge "$THRESHOLD" ]; then
  curr_state="high"
else
  curr_state="ok"
fi

echo "$curr_state" > "$STATE_FILE"

if [ "$curr_state" != "$prev_state" ]; then
  if [ "$curr_state" = "high" ]; then
    ntfy_push "High load: $LOAD" "high" "fire,server" \
      "Load average is $LOAD on $CORES cores (threshold $THRESHOLD) — server is under heavy load."
  else
    ntfy_push "Load normal: $LOAD" "default" "white_check_mark,server" \
      "Load average returned to normal: $LOAD on $CORES cores (threshold $THRESHOLD)."
  fi
fi
