#!/bin/bash
# alert-load.sh — CPU load average check → ntfy
# Systemd timer: hub-load.timer
# Only alerts on state TRANSITIONS (ok→high or high→ok), not every high reading.
NTFY="${HUB_NTFY_URL:-http://localhost:8085}/server-alerts"
STATE_FILE="/tmp/.alert-load-state"
THRESHOLD=4  # adjust to number of cores if possible

# Get 1-min load average
LOAD=$(cat /proc/loadavg | awk '{print $1}')
LOAD_INT=$(echo "$LOAD" | awk -F. '{print $1}')

prev_state=""
[ -f "$STATE_FILE" ] && prev_state=$(cat "$STATE_FILE")

if [ "$LOAD_INT" -ge "$THRESHOLD" ]; then
  curr_state="high"
else
  curr_state="ok"
fi

echo "$curr_state" > "$STATE_FILE"

# Only alert on state change
if [ "$curr_state" != "$prev_state" ]; then
  if [ "$curr_state" = "high" ]; then
    curl -s -X POST "$NTFY" \
      -H "Title: 🔥 High Load: $LOAD" \
      -H "Priority: high" \
      -H "Tags: fire,server" \
      -d "Load average is $LOAD — server is under heavy load." > /dev/null
  else
    curl -s -X POST "$NTFY" \
      -H "Title: ✅ Load Normal: $LOAD" \
      -H "Priority: default" \
      -H "Tags: white_check_mark,server" \
      -d "Load average returned to normal: $LOAD" > /dev/null
  fi
fi
