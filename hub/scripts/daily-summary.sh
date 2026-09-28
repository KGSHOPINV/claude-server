#!/bin/bash
# 20404732  daily-summary.sh — 7am morning server brief → ntfy
#
# Systemd timer: hub-daily.timer, via ~/.config/systemd/user/hub-daily.service.
#
# NOTE THE DEPLOY PATH. hub-daily.service runs
# /home/admin1/hub/scripts/daily-summary.sh, and /home/admin1/hub is a checkout
# of THIS REPO's root — so the file that unit actually runs is the repo's
# scripts/daily-summary.sh, not this one. Both are kept correct and both source
# the same helper; see scripts/daily-summary.sh for the full note.
#
# WHERE THE BRIEF WAS GOING: NOWHERE, LOUDLY. It defaulted to
# http://localhost:8085/server-alerts. ntfy on fks-services listens on 7001 with
# the topic fks-services, hub-daily.service sets no environment at all, and
# curl's exit 7 was the script's exit status — so the unit has recorded
# "Failed with result 'exit-code'" every single morning. Config now comes from
# ~/.server-alerts.conf via ntfy-lib.sh, which also names the endpoint in the
# journal when a push does not land.
set -uo pipefail

_d="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
for _l in "$_d/ntfy-lib.sh" "$_d/../hub/scripts/ntfy-lib.sh" "$_d/hub/scripts/ntfy-lib.sh"; do
  [ -f "$_l" ] && { . "$_l"; break; }
done
command -v ntfy_push >/dev/null || { echo "[daily-summary] ntfy-lib.sh not found — cannot send" >&2; exit 1; }

running=$(docker ps -q 2>/dev/null | wc -l)
total=$(docker ps -aq 2>/dev/null | wc -l)
stopped=$(docker ps --filter status=exited --format '{{.Names}}' 2>/dev/null | tr '\n' ' ' | xargs)

disk_pct=$(df -h / | tail -1 | awk '{print $5}')
disk_used=$(df -h / | tail -1 | awk '{print $3}')
disk_size=$(df -h / | tail -1 | awk '{print $2}')
mem_used=$(free -h | grep ^Mem | awk '{print $3}')
mem_total=$(free -h | grep ^Mem | awk '{print $2}')
load=$(uptime | grep -oP 'load average: \K[\d.]+')
cores=$(nproc 2>/dev/null || echo '?')

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
⚡ Load: $load ($cores cores)"

# Title is plain ASCII and the sun lives in Tags, which is the field ntfy renders
# as emoji anyway. The body is a normal UTF-8 payload and keeps its icons.
ntfy_push "Morning server brief" "$priority" "$tag,sunny,calendar" "$body"
