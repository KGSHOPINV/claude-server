#!/usr/bin/env bash
# boot-health-check.sh — runs at boot via systemd, POSTs result to ntfy
# Install to: /usr/local/bin/boot-health-check.sh

set -euo pipefail

NTFY_URL="http://localhost:8085/alerts"
NTFY_TOKEN="tk_7dw44frhryfbx5tf0euzj88299xb3"

FAILED=()

# ── Checks ────────────────────────────────────────────────────────────────────

if ! ip route | grep -q default; then
    FAILED+=("No default route")
fi

if ! ping -c1 -W3 1.1.1.1 &>/dev/null; then
    FAILED+=("Internet unreachable (1.1.1.1)")
fi

if ! getent hosts google.com &>/dev/null; then
    FAILED+=("DNS resolution failed (google.com)")
fi

if ! systemctl is-active --quiet docker; then
    FAILED+=("Docker not running")
fi

if ! ss -tlnp | grep -q 8765; then
    FAILED+=("Hub port 8765 not listening")
fi

# ── Report ────────────────────────────────────────────────────────────────────

_ntfy_post() {
    local title="$1"
    local msg="$2"
    local priority="$3"
    curl -s -o /dev/null \
        -H "Authorization: Bearer ${NTFY_TOKEN}" \
        -H "Title: ${title}" \
        -H "Priority: ${priority}" \
        -d "${msg}" \
        "${NTFY_URL}" || true
}

if [ ${#FAILED[@]} -gt 0 ]; then
    body="Boot health check FAILED on $(hostname) at $(date -Iseconds):"$'\n'
    for item in "${FAILED[@]}"; do
        body+="  - ${item}"$'\n'
    done
    _ntfy_post "Boot Health Fail" "${body}" "high"
    echo "BOOT-HEALTH: FAILED — ${FAILED[*]}"
    exit 1
else
    _ntfy_post "Boot OK" "All checks passed on $(hostname) at $(date -Iseconds)." "default"
    echo "BOOT-HEALTH: OK"
    exit 0
fi
