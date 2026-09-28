#!/bin/bash
# 20404726  alert-check.sh — every 15 min, is anything down, and tell the phone
#
# THIS IS THE LIVE ONE. There were two divergent copies of this file:
#
#   hub/scripts/alert-check.sh   this file. ~/.config/systemd/user/
#                                hub-alert.service runs it every 15 minutes
#                                via hub-alert.timer. Note USER, not system:
#                                an earlier audit looked only in
#                                /etc/systemd/system, found nothing, and
#                                declared this script dead. It has been running
#                                the whole time.
#   scripts/alert-check.sh       DELETED 2026-09-27. Nothing invoked it, it was
#                                not present on either box, and it was the copy
#                                with the wrong values hardcoded.
#
# WHERE THE ALERTS WERE GOING: NOWHERE. Both copies defaulted to
# http://localhost:8085/server-alerts. ntfy on fks-services listens on 7001
# with the topic fks-services, its ACL denies anonymous publish, and
# hub-alert.service sets no environment at all — so every one of these pushes
# was a POST to a closed port for as long as the timer has existed.
#
# ~/.server-alerts.conf is where the true values already live. kernel/log.py
# reads it, alert-startup.sh sources it, and it holds NTFY_URL, NTFY_TOPIC and
# NTFY_TOKEN on fks today. It is read here for the same reason: one file, one
# answer, and a default that is a guess stops being load-bearing.
#
# Sends only when the set of down services CHANGES, so a service that stays
# down does not push every 15 minutes forever.
set -uo pipefail

[ -f "$HOME/.server-alerts.conf" ] && . "$HOME/.server-alerts.conf"

# Env beats nothing, the conf file beats the defaults, and the defaults are the
# values this fleet actually uses rather than the ones it was first written with.
NTFY_URL="${HUB_NTFY_URL:-${NTFY_URL:-http://localhost:7001}}"
NTFY_TOPIC="${HUB_NTFY_TOPIC:-${NTFY_TOPIC:-fks-services}}"
NTFY_TOKEN="${NTFY_TOKEN:-}"
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

# 20404727  push — one notification, with an ASCII title
#
# THE TITLE IS ASCII ON PURPOSE. ntfy carries the title in an HTTP header, and
# a header is not a UTF-8 field: an em dash in one killed every push from
# ksgcohub's hub, 24 failed and 0 sent, which is what kernel/log.py's
# _ascii_header exists for. The emoji that used to sit in the title are moved
# to Tags, which is the field ntfy renders as emoji anyway, so the phone shows
# the same thing and the header stays legal.
push() { # push TITLE PRIORITY TAGS BODY
  local headers=(-H "Title: $1" -H "Priority: $2" -H "Tags: $3")
  [ -n "$NTFY_TOKEN" ] && headers+=(-H "Authorization: Bearer $NTFY_TOKEN")
  curl -s -o /dev/null --max-time 8 -X POST "${headers[@]}" \
    -d "$4" "$NTFY_URL/$NTFY_TOPIC" 2>/dev/null || true
}

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
    push "All services recovered" "default" "white_check_mark,server" \
         "Previously down: ${prev_down} - all services are now responding."
  else
    n=${#down[@]}
    push "$n service$([ "$n" -gt 1 ] && echo s) down" "high" "rotating_light,server" \
         "${down[*]}"
  fi
fi
