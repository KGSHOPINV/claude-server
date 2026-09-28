#!/bin/bash
# 20404737  alert-check.sh — every 15 min, is anything down, and tell the phone
#
# THIS COPY IS NOT INVOKED BY ANYTHING. The one hub-alert.service runs is
# scripts/alert-check.sh at the repo root — /home/admin1/hub is a checkout of
# this repo's ROOT, so the unit's "hub/scripts/alert-check.sh" resolves there,
# not here. See scripts/alert-check.sh for the md5 evidence and for why commit
# 51e5030's note in this file said the opposite.
#
# It is kept and kept correct rather than deleted: the two directories are
# deployed together, and a stale copy of an alert script is how this fault
# spread in the first place.
#
# WHERE THE ALERTS WERE GOING: NOWHERE. This defaulted to
# http://localhost:8085/server-alerts. ntfy on fks-services listens on 7001 with
# the topic fks-services and denies anonymous publish. Config now comes from
# ~/.server-alerts.conf via ntfy-lib.sh.
#
# Sends only when the set of down services CHANGES, so a service that stays down
# does not push every 15 minutes forever.
set -uo pipefail

_d="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
for _l in "$_d/ntfy-lib.sh" "$_d/../hub/scripts/ntfy-lib.sh" "$_d/hub/scripts/ntfy-lib.sh"; do
  [ -f "$_l" ] && { . "$_l"; break; }
done
command -v ntfy_push >/dev/null || { echo "[alert-check] ntfy-lib.sh not found — cannot send" >&2; exit 1; }

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
