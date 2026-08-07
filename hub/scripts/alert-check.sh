#!/bin/bash
# alert-check.sh — service health check every 15 min → ntfy
# Systemd timer: hub-alert.timer
# Only sends a notification when state CHANGES (down → up or up → down)
NTFY="http://localhost:8085/server-alerts"
HOST="192.168.1.229"
STATE_FILE="/tmp/.alert-state"

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

# Load previous state
prev_down=""
[ -f "$STATE_FILE" ] && prev_down=$(cat "$STATE_FILE")
curr_down="${down[*]}"

# Write current state
echo "$curr_down" > "$STATE_FILE"

# Alert only if state changed
if [ "$curr_down" != "$prev_down" ]; then
  if [ ${#down[@]} -eq 0 ]; then
    # Recovery
    curl -s -X POST "$NTFY" \
      -H "Title: ✅ All Services Recovered" \
      -H "Priority: default" \
      -H "Tags: white_check_mark,server" \
      -d "Previously down: $prev_down — all services are now responding." > /dev/null
  else
    # New outage
    msg="${down[*]}"
    n=${#down[@]}
    curl -s -X POST "$NTFY" \
      -H "Title: 🔴 $n Service$([ $n -gt 1 ] && echo s) Down" \
      -H "Priority: high" \
      -H "Tags: rotating_light,server" \
      -d "$msg" > /dev/null
  fi
fi
