#!/bin/bash
# 20404736  alert-check.sh — every 15 min, is anything down, and tell the phone
#
# THIS IS THE COPY THAT RUNS, AND IT IS SCHEDULED FOR DELETION ON ANOTHER
# BRANCH. Read this before resolving that conflict.
#
#   scripts/alert-check.sh      this file. ~/.config/systemd/user/
#   (repo root)                 hub-alert.service runs
#                               /home/admin1/hub/scripts/alert-check.sh every
#                               15 minutes via hub-alert.timer.
#   hub/scripts/alert-check.sh  no unit on either box invokes it.
#
# Commit 51e5030 on fix/project-port-band has it the other way round: it fixed
# hub/scripts/alert-check.sh as "THE LIVE ONE" and deleted this file as "not
# present on either box". The machine disagrees. Verified 2026-09-28 on
# fks-services: md5sum of ~/hub/scripts/alert-check.sh is 1a915771f00b…, which
# is this file (LF-normalised) and not hub/scripts/alert-check.sh (41b175f3…);
# ~/hub is a clean checkout of this repo's ROOT, so "hub/scripts/" in the unit
# file resolves to the repo's scripts/ directory; ~/hub/hub/scripts/ holds the
# other family, untouched and uninvoked.
#
# If that deletion lands and fks deploys, hub-alert.service's ExecStart points
# at a file that no longer exists and the health check stops entirely.
#
# WHERE THE ALERTS WERE GOING: NOWHERE. NTFY was hardcoded to
# http://localhost:8085/server-alerts. ntfy on fks listens on 7001 with the
# topic fks-services, its ACL denies anonymous publish, and hub-alert.service
# sets no environment — so every push this timer has made was a POST to a closed
# port. Config now comes from ~/.server-alerts.conf via ntfy-lib.sh.
#
# Sends only when the set of down services CHANGES, so a service that stays down
# does not push every 15 minutes forever.
set -uo pipefail

_d="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
for _l in "$_d/ntfy-lib.sh" "$_d/../hub/scripts/ntfy-lib.sh" "$_d/hub/scripts/ntfy-lib.sh"; do
  [ -f "$_l" ] && { . "$_l"; break; }
done
command -v ntfy_push >/dev/null || { echo "[alert-check] ntfy-lib.sh not found — cannot send" >&2; exit 1; }

# HOST was hardcoded to fks-services' LAN address, which made this script wrong
# on any other box. localhost is what the checks actually mean.
HOST="${HUB_SERVER_IP:-localhost}"
STATE_FILE="${ALERT_STATE:-/tmp/.alert-state}"

declare -A SERVICES=(
  [hub]="8765"
  [npm]="81"
  [portainer]="9443"
  [homepage]="3000"
  [uptime-kuma]="3001"
  [netdata]="19999"
  [dozzle]="8090"
  [n8n]="5678"
  [adminer]="8082"
  [mailpit]="8025"
  [wikijs]="3002"
)

down=()
for name in "${!SERVICES[@]}"; do
  port="${SERVICES[$name]}"
  code=$(curl -sk -o /dev/null -w "%{http_code}" --connect-timeout 4 "http://$HOST:$port/" 2>/dev/null)
  [[ "$code" =~ ^[23] ]] || down+=("$name")
done

prev_down=""
[ -f "$STATE_FILE" ] && prev_down=$(cat "$STATE_FILE")
curr_down="${down[*]-}"

echo "$curr_down" > "$STATE_FILE"

if [ "$curr_down" != "$prev_down" ]; then
  if [ ${#down[@]} -eq 0 ]; then
    ntfy_push "All services recovered" "default" "white_check_mark,server" \
      "Previously down: $prev_down — all services are now responding."
  else
    n=${#down[@]}
    ntfy_push "$n service$([ "$n" -gt 1 ] && echo s) down" "high" "rotating_light,server" \
      "${down[*]}"
  fi
fi
