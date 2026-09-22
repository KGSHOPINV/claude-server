#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# flare-mode.sh — flip a node between NODE and CENTRAL, and tell a node where
# home is. Same codebase either way; server.identity.json is the only switch.
#
#   ./flare-mode.sh --show
#   ./flare-mode.sh --central
#   ./flare-mode.sh --node --central-tailscale http://100.107.234.9:8765
#   ./flare-mode.sh --node --central-url https://dashboard.flarevault.app \
#                          --central-tailscale http://100.107.234.9:8765 \
#                          --central-lan http://192.168.50.100:8765
#
# Edits ~/.flare/server.identity.json in place, preserving every field it does
# not own — so a FlareVault-provisioned server_id and jwt_secret survive a mode
# change untouched. Restart the hub afterwards to pick it up.
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail

IDENTITY="${HUB_IDENTITY_FILE:-$HOME/.flare/server.identity.json}"
GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; BOLD='\033[1m'; RESET='\033[0m'

ROLE=""; CU=""; CT=""; CL=""; SHOW=0
while [ $# -gt 0 ]; do
  case "$1" in
    --show)              SHOW=1; shift;;
    --central)           ROLE="central"; shift;;
    --node)              ROLE="node"; shift;;
    --central-url)       CU="$2"; shift 2;;
    --central-tailscale) CT="$2"; shift 2;;
    --central-lan)       CL="$2"; shift 2;;
    *) echo -e "${RED}unknown argument: $1${RESET}" >&2; exit 1;;
  esac
done

[ -f "$IDENTITY" ] || { echo -e "${RED}no identity file at $IDENTITY${RESET}"; \
  echo "  Start the hub once — it writes a self-issued identity at boot."; exit 1; }

show() {
  python3 - "$IDENTITY" <<'PY'
import json, sys
d = json.load(open(sys.argv[1]))
print(f"  server_id         {d.get('server_id','')}")
print(f"  name              {d.get('name','')}")
print(f"  machine_id        {d.get('machine_id','')}")
print(f"  role              {d.get('role','node').upper()}")
print(f"  jwt_issuer        {d.get('jwt_issuer','self')}")
print(f"  jwt_secret        {'set' if d.get('jwt_secret') else 'MISSING'}")
for k in ('central_url','central_tailscale','central_lan'):
    print(f"  {k:17} {d.get(k) or '-'}")
PY
}

if [ "$SHOW" = "1" ] || [ -z "$ROLE$CU$CT$CL" ]; then
  echo -e "${BOLD}Current identity${RESET}  ($IDENTITY)"; show; exit 0
fi

cp "$IDENTITY" "${IDENTITY}.bak"

ROLE="$ROLE" CU="$CU" CT="$CT" CL="$CL" python3 - "$IDENTITY" <<'PY'
import json, os, sys
p = sys.argv[1]
d = json.load(open(p))
role = os.environ.get('ROLE') or ''
if role:
    d['role'] = role
for env, key in (('CU','central_url'), ('CT','central_tailscale'), ('CL','central_lan')):
    v = os.environ.get(env) or ''
    if v:
        d[key] = v.rstrip('/')
# A central does not heartbeat to itself. Clear stale addresses so a box that
# used to be a node does not keep trying to phone a former home.
if d.get('role') == 'central':
    for key in ('central_url', 'central_tailscale', 'central_lan'):
        d[key] = ''
json.dump(d, open(p, 'w'), indent=2)
PY
chmod 600 "$IDENTITY"

echo -e "${GREEN}updated${RESET}  (backup: ${IDENTITY}.bak)"; show
echo ""
if command -v systemctl >/dev/null && systemctl --user is-enabled hub >/dev/null 2>&1; then
  echo -e "${YELLOW}restart to apply:${RESET}  systemctl --user restart hub"
else
  echo -e "${YELLOW}restart the hub to apply.${RESET}"
fi
