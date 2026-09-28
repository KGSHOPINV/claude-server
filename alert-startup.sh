#!/bin/bash
# 20404738  alert-startup.sh — fires once on hub start, tells the phone it is up
#
# This was the fifth copy of the ntfy block, and the only one that already read
# ~/.server-alerts.conf — it is where the other four got the pattern from. It
# now sources ntfy-lib.sh instead of carrying its own copy, so there is one
# place left where "which URL, which topic, which token" is decided.
#
# Its title used to be "🚀 Hub started — <host>": a rocket AND an em dash in an
# HTTP header. Both are gone from the title and the rocket is in Tags, where
# ntfy renders it as an emoji anyway. ntfy-lib.sh would now RFC 2047-encode such
# a title rather than lose it, but a plain title needs no rescuing.
set -uo pipefail

_d="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
for _l in "$_d/ntfy-lib.sh" "$_d/../hub/scripts/ntfy-lib.sh" "$_d/hub/scripts/ntfy-lib.sh"; do
  [ -f "$_l" ] && { . "$_l"; break; }
done
command -v ntfy_push >/dev/null || { echo "[alert-startup] ntfy-lib.sh not found — cannot send" >&2; exit 1; }

HUB_PORT="${HUB_PORT:-7000}"
HOST=$(hostname 2>/dev/null || echo "server")
LAN_IP=$(ip route get 1.1.1.1 2>/dev/null | awk '/src/{print $NF;exit}')
UPTIME=$(awk '{s=int($1); printf "%dd %dh %dm", s/86400, (s%86400)/3600, (s%3600)/60}' /proc/uptime)

ntfy_push "Hub started: $HOST" "default" "rocket,server" \
  "IP: ${LAN_IP:-unknown} | Port: $HUB_PORT | Uptime: $UPTIME"
