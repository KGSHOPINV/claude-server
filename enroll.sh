#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# STOPGAP — will be replaced by FlareVault provision_node().
# Provisions Cloudflare from the node, which means the node holds the CF token
# during the run. Wrong shape long term: FlareVault should provision on the
# node's behalf against a one-time join token. Use until provision_node() ships.
# enroll.sh — admit this node to the fleet and give it one public entry point.
#
# bootstrap.sh gets the hub running on :8765. This gives the node an identity
# and a Cloudflare front door, so it is reachable from anywhere without
# depending on which private network you happen to be on.
#
#   ./enroll.sh --node fks --zone ksgdev.com
#   ./enroll.sh --node fks --zone ksgdev.com --dry-run
#
# The Cloudflare API token is read from (first found):
#   $CF_API_TOKEN   ~/.cf-token   /etc/flare/token
# It is used during this run and NEVER written into the hub or its database.
# ServerHub doctrine: credentials are never stored here, pointers only.
# Only cloudflared keeps a credential, and that one is scoped to this tunnel.
#
# Idempotent: re-running finds what already exists instead of duplicating it.
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
CYAN='\033[0;36m'; BOLD='\033[1m'; RESET='\033[0m'
ok(){   echo -e "  ${GREEN}✓${RESET} $*"; }
warn(){ echo -e "  ${YELLOW}!${RESET} $*"; }
die(){  echo -e "  ${RED}✗${RESET} $*" >&2; exit 1; }
step(){ echo -e "\n${BOLD}${CYAN}$*${RESET}"; }

NODE_NAME=""; ZONE=""; DRY_RUN=0; HUB_PORT="${HUB_PORT:-8765}"
while [ $# -gt 0 ]; do
  case "$1" in
    --node)    NODE_NAME="$2"; shift 2;;
    --zone)    ZONE="$2";      shift 2;;
    --port)    HUB_PORT="$2";  shift 2;;
    --dry-run) DRY_RUN=1;      shift;;
    *) die "unknown argument: $1";;
  esac
done

# ── 1. identity ──────────────────────────────────────────────────────────────
# machine-id is the stable node identity. It survives hostname changes, IP
# changes and re-enrollment — which is exactly why peers are keyed by it
# rather than by URL.
step "1. Identity"
[ -r /etc/machine-id ] || die "/etc/machine-id unreadable — cannot identify this node"
MACHINE_ID=$(cat /etc/machine-id)
[ -n "$MACHINE_ID" ] || die "/etc/machine-id is empty"
[ -n "$NODE_NAME" ] || NODE_NAME=$(hostname -s)
# hostname label rules: lowercase alnum + hyphen
echo "$NODE_NAME" | grep -qE '^[a-z0-9][a-z0-9-]{0,30}[a-z0-9]$' \
  || die "--node '$NODE_NAME' is not a valid hostname label (lowercase, alnum, hyphen)"
ok "machine-id : $MACHINE_ID"
ok "node       : $NODE_NAME"

# ── 2. preflight ─────────────────────────────────────────────────────────────
step "2. Preflight"
command -v curl    >/dev/null || die "curl not installed"
command -v python3 >/dev/null || die "python3 not installed"
[ -n "$ZONE" ] || die "--zone is required (e.g. --zone ksgdev.com)"
HOSTNAME_FQDN="hub-${NODE_NAME}.${ZONE}"
ok "target     : https://${HOSTNAME_FQDN} -> http://localhost:${HUB_PORT}"

# the hub must actually be running, or we would publish a dead endpoint
HUB_CODE=$(curl -s -m 8 -o /dev/null -w '%{http_code}' "http://127.0.0.1:${HUB_PORT}/api/my-ip" || echo 000)
[ "$HUB_CODE" = "200" ] || die "hub not answering on :${HUB_PORT} (got ${HUB_CODE}) — run bootstrap.sh first"
ok "hub        : responding on :${HUB_PORT}"

# ── 3. credentials ───────────────────────────────────────────────────────────
step "3. Cloudflare credentials"
TOKEN="${CF_API_TOKEN:-}"
for f in "$HOME/.cf-token" /etc/flare/token; do
  [ -n "$TOKEN" ] && break
  [ -r "$f" ] || continue
  # accept either a bare token or KEY=value
  TOKEN=$(grep -oE '[A-Za-z0-9_-]{30,}' "$f" | head -1 || true)
  [ -n "$TOKEN" ] && ok "token from : $f"
done
[ -n "$TOKEN" ] || die "no Cloudflare token found (set CF_API_TOKEN or write ~/.cf-token, chmod 600)"

cf() { # cf METHOD PATH [JSON_BODY]
  local method="$1" path="$2" body="${3:-}"
  if [ -n "$body" ]; then
    curl -s -m 30 -X "$method" "https://api.cloudflare.com/client/v4${path}" \
      -H "Authorization: Bearer ${TOKEN}" -H "Content-Type: application/json" -d "$body"
  else
    curl -s -m 30 -X "$method" "https://api.cloudflare.com/client/v4${path}" \
      -H "Authorization: Bearer ${TOKEN}"
  fi
}
jq_py() { python3 -c "import sys,json;d=json.load(sys.stdin);$1" 2>/dev/null || true; }

VERIFY=$(cf GET /user/tokens/verify | jq_py 'print(d.get("success"))')
[ "$VERIFY" = "True" ] || die "token rejected by Cloudflare (Invalid API Token). Create one with: Zone>DNS>Edit, Account>Cloudflare Tunnel>Edit, Account>Access Apps>Edit"
ok "token      : valid"

ZONE_ID=$(cf GET "/zones?name=${ZONE}" | jq_py 'r=d.get("result") or [];print(r[0]["id"] if r else "")')
[ -n "$ZONE_ID" ] || die "zone '${ZONE}' not visible to this token — check the token's zone scope"
ACCOUNT_ID=$(cf GET "/zones/${ZONE_ID}" | jq_py 'print((d.get("result") or {}).get("account",{}).get("id",""))')
[ -n "$ACCOUNT_ID" ] || die "could not resolve account id for zone ${ZONE}"
ok "zone       : ${ZONE} (${ZONE_ID:0:8}…)"

if [ "$DRY_RUN" = "1" ]; then
  step "DRY RUN — stopping before any change"
  echo "  would create tunnel   : hub-${NODE_NAME}"
  echo "  would create DNS      : ${HOSTNAME_FQDN}"
  echo "  would create Access   : ${HOSTNAME_FQDN}"
  echo "  would install service : cloudflared (host systemd)"
  exit 0
fi

# ── 4. tunnel (idempotent) ───────────────────────────────────────────────────
step "4. Tunnel"
TUNNEL_NAME="hub-${NODE_NAME}"
TUNNEL_ID=$(cf GET "/accounts/${ACCOUNT_ID}/cfd_tunnel?name=${TUNNEL_NAME}&is_deleted=false" \
  | jq_py 'r=d.get("result") or [];print(r[0]["id"] if r else "")')

if [ -n "$TUNNEL_ID" ]; then
  warn "tunnel '${TUNNEL_NAME}' already exists — reusing (${TUNNEL_ID:0:8}…)"
else
  RESP=$(cf POST "/accounts/${ACCOUNT_ID}/cfd_tunnel" \
    "{\"name\":\"${TUNNEL_NAME}\",\"config_src\":\"cloudflare\"}")
  TUNNEL_ID=$(echo "$RESP" | jq_py 'print((d.get("result") or {}).get("id",""))')
  [ -n "$TUNNEL_ID" ] || die "tunnel create failed: $(echo "$RESP" | head -c 300)"
  ok "tunnel     : created ${TUNNEL_ID:0:8}…"
fi

TUNNEL_TOKEN=$(cf GET "/accounts/${ACCOUNT_ID}/cfd_tunnel/${TUNNEL_ID}/token" | jq_py 'print(d.get("result",""))')
[ -n "$TUNNEL_TOKEN" ] || die "could not fetch tunnel token"

# ingress: this hostname -> the local hub. catch-all 404 so nothing else leaks.
cf PUT "/accounts/${ACCOUNT_ID}/cfd_tunnel/${TUNNEL_ID}/configurations" "$(cat <<JSON
{"config":{"ingress":[
  {"hostname":"${HOSTNAME_FQDN}","service":"http://localhost:${HUB_PORT}"},
  {"service":"http_status:404"}
]}}
JSON
)" >/dev/null
ok "ingress    : ${HOSTNAME_FQDN} -> http://localhost:${HUB_PORT}"

# ── 5. DNS (idempotent) ──────────────────────────────────────────────────────
step "5. DNS"
CNAME_TARGET="${TUNNEL_ID}.cfargotunnel.com"
REC_ID=$(cf GET "/zones/${ZONE_ID}/dns_records?name=${HOSTNAME_FQDN}" \
  | jq_py 'r=d.get("result") or [];print(r[0]["id"] if r else "")')
BODY="{\"type\":\"CNAME\",\"name\":\"${HOSTNAME_FQDN}\",\"content\":\"${CNAME_TARGET}\",\"proxied\":true}"
if [ -n "$REC_ID" ]; then
  cf PUT "/zones/${ZONE_ID}/dns_records/${REC_ID}" "$BODY" >/dev/null
  warn "dns        : record existed — updated to ${CNAME_TARGET:0:16}…"
else
  cf POST "/zones/${ZONE_ID}/dns_records" "$BODY" >/dev/null
  ok "dns        : ${HOSTNAME_FQDN} -> ${CNAME_TARGET:0:16}…"
fi

# ── 6. Access (idempotent) ───────────────────────────────────────────────────
# Nothing public is created without a gate in front of it.
step "6. Access"
APP_ID=$(cf GET "/accounts/${ACCOUNT_ID}/access/apps" \
  | jq_py "r=d.get('result') or [];print(next((a['id'] for a in r if a.get('domain')=='${HOSTNAME_FQDN}'),''))")
if [ -n "$APP_ID" ]; then
  warn "access     : app already exists for ${HOSTNAME_FQDN}"
else
  APP_ID=$(cf POST "/accounts/${ACCOUNT_ID}/access/apps" "$(cat <<JSON
{"name":"Hub ${NODE_NAME}","domain":"${HOSTNAME_FQDN}","type":"self_hosted","session_duration":"24h"}
JSON
)" | jq_py 'print((d.get("result") or {}).get("id",""))')
  [ -n "$APP_ID" ] || die "Access app create failed — check the token has Access>Apps>Edit"
  ok "access     : app created"
  warn "no policy attached yet — add an allow policy for your Google address in"
  warn "Zero Trust > Access > Applications, or the app denies everyone by default"
fi

# ── 7. cloudflared as a HOST service ─────────────────────────────────────────
# Deliberately not a container: if Docker dies, the way in must survive. A
# containerised tunnel disappears exactly when you need it to diagnose the box.
step "7. cloudflared (host service)"
if ! command -v cloudflared >/dev/null; then
  ARCH=$(dpkg --print-architecture 2>/dev/null || echo amd64)
  curl -fsSL -o /tmp/cloudflared.deb \
    "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-${ARCH}.deb"
  sudo dpkg -i /tmp/cloudflared.deb >/dev/null 2>&1 || sudo apt-get -f install -y >/dev/null
  rm -f /tmp/cloudflared.deb
  ok "cloudflared: installed"
else
  ok "cloudflared: already present ($(cloudflared --version 2>&1 | head -1))"
fi
sudo cloudflared service install "$TUNNEL_TOKEN" >/dev/null 2>&1 \
  || warn "service install returned non-zero — may already be installed"
sudo systemctl enable --now cloudflared >/dev/null 2>&1 || true
sleep 3
systemctl is-active --quiet cloudflared && ok "cloudflared: running" || warn "cloudflared not active — check: journalctl -u cloudflared -n 40"

# ── 8. record identity locally ───────────────────────────────────────────────
# Written as plain facts the hub can read and report. No credentials.
step "8. Node identity"
mkdir -p "$HOME/.flare"
cat > "$HOME/.flare/node.json" <<JSON
{
  "machine_id": "${MACHINE_ID}",
  "node": "${NODE_NAME}",
  "hostname": "${HOSTNAME_FQDN}",
  "hub_port": ${HUB_PORT},
  "zone": "${ZONE}",
  "tunnel_id": "${TUNNEL_ID}",
  "enrolled": "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
}
JSON
chmod 600 "$HOME/.flare/node.json"
ok "written    : ~/.flare/node.json"

# ── 9. verify ────────────────────────────────────────────────────────────────
step "9. Verify"
echo "  waiting for edge propagation…"
for i in $(seq 1 12); do
  CODE=$(curl -s -m 10 -o /dev/null -w '%{http_code}' "https://${HOSTNAME_FQDN}" || echo 000)
  case "$CODE" in
    302|200) ok "https://${HOSTNAME_FQDN} -> ${CODE} (302 = Access login, correct)"; break;;
    000)     [ "$i" = "12" ] && warn "no response yet — DNS can take a few minutes";;
    *)       ok "https://${HOSTNAME_FQDN} -> ${CODE}"; break;;
  esac
  sleep 5
done

step "Done"
echo "  node       ${NODE_NAME}  (${MACHINE_ID})"
echo "  entry      https://${HOSTNAME_FQDN}"
echo ""
echo "  The Cloudflare API token was not stored. cloudflared holds a tunnel-scoped"
echo "  credential only. Add the Access policy if this run created the app."
