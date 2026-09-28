#!/bin/bash
# 20404735  daily-summary.sh — 7am morning server brief → ntfy
#
# THIS IS THE COPY THAT RUNS. Read this before "tidying up" either copy.
#
#   scripts/daily-summary.sh      this file. ~/.config/systemd/user/
#   (repo root)                   hub-daily.service runs
#                                 /home/admin1/hub/scripts/daily-summary.sh
#                                 every morning via hub-daily.timer.
#   hub/scripts/daily-summary.sh  no unit on either box invokes it.
#
# THE PATH IS THE TRAP. /home/admin1/hub is a git checkout of this repo's ROOT
# (it holds AGENTS.md, alert-startup.sh, db/ …), so "hub/scripts/…" in a unit
# file means the repo's scripts/ directory, not the repo's hub/scripts/. The
# two read identically and are one directory apart. Verified 2026-09-28 by
# md5sum: the file on fks-services is byte-for-byte this one, `git -C ~/hub
# status` is clean, and ~/hub/hub/scripts/ holds the other family untouched.
#
# The same trap sits under hub-alert.service (scripts/alert-check.sh) and
# hub-maintenance.service (maintenance.py at the root, not hub/maintenance.py).
#
# WHERE THE BRIEF WAS GOING: NOWHERE, AND SYSTEMD SAID SO. NTFY was hardcoded to
# http://localhost:8085/server-alerts. ntfy on fks-services listens on 7001 with
# the topic fks-services and denies anonymous publish, and hub-daily.service
# sets no Environment= lines. curl exited 7 and, being the last command, made
# that the script's status — `journalctl --user -u hub-daily.service` shows
# "Failed with result 'exit-code'" every morning it has ever run. Config now
# comes from ~/.server-alerts.conf via ntfy-lib.sh.
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
