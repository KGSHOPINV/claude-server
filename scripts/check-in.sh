#!/bin/bash
# ============================================================
# SERVER CHECK-IN
# Run this at the start of every session via:
#   ssh homeserver "bash ~/server-kit/scripts/check-in.sh"
# Or from Claude's Bash tool via SSH.
# ============================================================

echo ""
echo "=========================================="
echo "  SERVER CHECK-IN — $(date '+%Y-%m-%d %H:%M')"
echo "=========================================="

# --- SYSTEM ---
echo ""
echo "  SYSTEM"
echo "  ──────────────────────────────────────"
echo "  Host:    $(hostname)"
echo "  Uptime:  $(uptime -p)"
echo "  Load:    $(cut -d' ' -f1-3 /proc/loadavg)"
echo "  Memory:  $(free -h | awk '/Mem:/ {printf "%s used / %s total", $3, $2}')"
echo "  Disk /:  $(df -h / | awk 'NR==2 {printf "%s used / %s total (%s)", $3, $2, $5}')"

# --- CONTAINERS ---
echo ""
echo "  CONTAINERS"
echo "  ──────────────────────────────────────"
docker ps -a --format "  {{.Names}}\t{{.Status}}" | column -t

# --- RECENT ERRORS (last 12h) ---
echo ""
echo "  RECENT ERRORS (last 12h)"
echo "  ──────────────────────────────────────"
errors=$(journalctl --since "12 hours ago" -p err --no-pager 2>/dev/null | grep -v "motd-news\|networkd-wait-online\|veth" | tail -5)
if [ -z "$errors" ]; then
  echo "  None"
else
  echo "$errors" | sed 's/^/  /'
fi

# --- SECURITY ---
echo ""
echo "  SECURITY"
echo "  ──────────────────────────────────────"
banned=$(sudo ufw status | grep "REJECT" | wc -l 2>/dev/null)
echo "  UFW REJECT rules active: $banned"
crowdsec_status=$(systemctl is-active crowdsec 2>/dev/null || echo "not running")
echo "  CrowdSec: $crowdsec_status"

# --- PORTS IN USE ---
echo ""
echo "  LISTENING PORTS (non-internal)"
echo "  ──────────────────────────────────────"
ss -tlnp | grep LISTEN | awk '{print $4}' | grep -v '127.0.0.1\|::1' | sort -t: -k2 -n | sed 's/^/  /'

echo ""
echo "=========================================="
echo ""
