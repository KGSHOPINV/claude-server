#!/bin/bash
# daily-summary.sh — 7am morning server brief → ntfy
# Systemd timer: hub-daily.timer
NTFY="http://localhost:8085/server-alerts"

running=$(docker ps -q 2>/dev/null | wc -l)
total=$(docker ps -aq 2>/dev/null | wc -l)
stopped=$(docker ps --filter status=exited --format '{{.Names}}' 2>/dev/null | tr '\n' ' ' | xargs)

disk_pct=$(df -h / | tail -1 | awk '{print $5}')
disk_used=$(df -h / | tail -1 | awk '{print $3}')
disk_size=$(df -h / | tail -1 | awk '{print $2}')
mem_used=$(free -h | grep ^Mem | awk '{print $3}')
mem_total=$(free -h | grep ^Mem | awk '{print $2}')
load=$(uptime | grep -oP 'load average: \K[\d.]+')

if [ -z "$stopped" ]; then
  health_line="✅ $running/$total containers up"
  priority="low"
  tag="white_check_mark"
else
  health_line="⚠️ $running/$total up — stopped: $stopped"
  priority="default"
  tag="warning"
fi

body="$health_line
💿 Disk: $disk_used / $disk_size ($disk_pct)
🧠 RAM: $mem_used / $mem_total
⚡ Load: $load (24 cores)"

curl -s -X POST "$NTFY" \
  -H "Title: ☀️ Morning Server Brief" \
  -H "Priority: $priority" \
  -H "Tags: $tag,calendar" \
  -d "$body" > /dev/null
