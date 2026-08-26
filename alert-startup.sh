#!/bin/bash
# Fires once on hub start — sends ntfy push notification
[ -f "$HOME/.server-alerts.conf" ] && source "$HOME/.server-alerts.conf"

NTFY_URL="${NTFY_URL:-http://localhost:7001}"
NTFY_TOPIC="${NTFY_TOPIC:-fks-services}"
HUB_PORT="${HUB_PORT:-7000}"

HOST=$(hostname 2>/dev/null || echo "server")
LAN_IP=$(ip route get 1.1.1.1 2>/dev/null | awk '/src/{print $NF;exit}')
UPTIME=$(awk '{s=int($1); printf "%dd %dh %dm", s/86400, (s%86400)/3600, (s%3600)/60}' /proc/uptime)

TITLE="🚀 Hub started — $HOST"
BODY="IP: ${LAN_IP:-unknown} | Port: $HUB_PORT | Uptime: $UPTIME"

HEADERS=(-H "Title: $TITLE" -H "Priority: default" -H "Tags: rocket,server")
[ -n "$NTFY_TOKEN" ] && HEADERS+=(-H "Authorization: Bearer $NTFY_TOKEN")

curl -s -o /dev/null --max-time 5 "${HEADERS[@]}" -d "$BODY" "$NTFY_URL/$NTFY_TOPIC" 2>/dev/null || true
