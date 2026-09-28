#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# 20404840  decommission.sh — take ONE node's public entry point back off the
#                             edge, and nothing else, ever.
#
# enroll.sh gives a node a hostname, a DNS record, an ingress rule, an Access
# app and (sometimes) a tunnel. Nothing has ever taken them away. So every box
# that gets rebuilt, renamed or thrown out leaves all five behind forever, and
# the zone slowly fills with names that answer 401 for a machine that no longer
# exists. That is not hypothetical here: fks-services is enrolled at the edge
# with NO ~/.flare/node.json, no zone recorded and no Cloudflare token on the
# box. Nothing on that machine knows what it published, so nothing on that
# machine could ever clean it up.
#
#   ./decommission.sh --zone flarevault.dev
#   ./decommission.sh --zone flarevault.dev --remove flareshub-fvn-3b8c1b.flarevault.dev
#
# DRY RUN IS THE DEFAULT AND THERE IS NO SHORT WAY PAST IT. Removing a node's
# entry point removes the way IN to that node. It is the most dangerous thing
# in this repo, so arming it takes the full hostname on the command line and
# that hostname must equal the one this run derived. `--remove` cannot be
# typed on the wrong box by accident, because the wrong box derives a different
# name and the run dies before it calls Cloudflare.
#
# WHY A SIBLING SCRIPT RATHER THAN `enroll.sh --decommission`
# -----------------------------------------------------------
# Two reasons, and the first is enough on its own.
#
#   1. A destructive verb must not be one mistyped flag away from the safe one.
#      `enroll.sh --decommission` is four characters from `--dry-run` on a line
#      an operator retypes from shell history at 1am. Separate files cannot be
#      confused by a typo.
#   2. enroll.sh's own banner says it is a STOPGAP, to be deleted the day
#      FlareVault ships provision_node(). Removal outlives provisioning: the
#      zone will still hold records for boxes that enrolled under the stopgap
#      long after the stopgap is gone. Welding the two together means deleting
#      the cleanup with the thing it cleans up after.
#
# Shared with enroll.sh by COPY, not by import: the server-id derivation and
# the cf() wrapper. enroll.sh is a single self-contained file on purpose —
# people curl it onto a fresh box — and a sourced common library would break
# that. The derivation is identical on purpose and is checked against
# hub/kernel/identity.py the same way enroll.sh's is.
#
# WHAT THIS DOES NOT TOUCH. The hub, its database, its containers, its data,
# cloudflared's service, the tunnel credential. This removes a node's PUBLIC
# PRESENCE. The box keeps working exactly as it did, reachable on the LAN and
# over Tailscale, which is how you get back in afterwards.
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
CYAN='\033[0;36m'; BOLD='\033[1m'; RESET='\033[0m'
ok(){   echo -e "  ${GREEN}✓${RESET} $*"; }
warn(){ echo -e "  ${YELLOW}!${RESET} $*"; }
die(){  echo -e "  ${RED}✗${RESET} $*" >&2; exit 1; }
step(){ echo -e "\n${BOLD}${CYAN}$*${RESET}"; }

ZONE=""; WANT_HOST=""; SERVER_ID_ARG=""; ARMED=0; CONFIRM_HOST=""
while [ $# -gt 0 ]; do
  case "$1" in
    --zone)      ZONE="$2";           shift 2;;
    --hostname)  WANT_HOST="$2";      shift 2;;
    --server-id) SERVER_ID_ARG="$2";  shift 2;;
    --remove)    ARMED=1; CONFIRM_HOST="${2:-}"; shift 2;;
    --dry-run)   shift;;   # accepted and ignored: dry run is the default
    -h|--help)
      sed -n '2,50p' "$0" | sed 's/^# \{0,1\}//'
      exit 0;;
    *) die "unknown argument: $1";;
  esac
done
[ -n "$ZONE" ] || die "--zone is required (e.g. --zone flarevault.dev)"

# ─────────────────────────────────────────────────────────────────────────────
# 20404842  the ONE name this script may ever touch
#
# A node's hostname is flareshub-fvn-<6 hex>.<zone> and NOTHING ELSE IS A NODE.
# The zone also holds the apex, www, and dashboard.<zone> which belongs to
# FlareVault; on ksgcohub the live tunnel additionally serves babyhelp.ksgco.app,
# hub.ksgco.app and ntfy.ksgco.app, which are babyhelp's and are out of scope.
#
# So this is a HARD FAIL, not a warning. A warning on a destructive path is a
# thing an operator scrolls past. Every record, app and ingress rule this
# script touches is checked against the one derived name by exact string
# equality, and the name itself is checked against this pattern first.
# ─────────────────────────────────────────────────────────────────────────────
ZONE_RE=$(printf '%s' "$ZONE" | sed 's/[.[\*^$()+?{}|]/\\&/g')
NODE_HOST_RE="^flareshub-fvn-[0-9a-f]{6}\.${ZONE_RE}\$"

assert_mine() { # assert_mine WHAT NAME
  local what="$1" name="$2"
  echo "$name" | grep -qE "$NODE_HOST_RE" \
    || die "REFUSING: ${what} '${name}' is not a node hostname (flareshub-fvn-<6hex>.${ZONE})"
  [ "$name" = "$HOSTNAME_FQDN" ] \
    || die "REFUSING: ${what} '${name}' is not this node's hostname (${HOSTNAME_FQDN})"
}

# ─────────────────────────────────────────────────────────────────────────────
# 20404841  identity — what did THIS node publish?
#
# Four sources, best first. The local file is preferred because it records what
# enrolment actually did; machine-id is the fallback because the hostname is
# DERIVED from it and therefore reproducible without any file at all — which is
# the fks-services case, and the case that proves you cannot rely on the file.
# The flags exist for the case the whole point of this script is: the box is
# GONE, and you are cleaning its records up from somewhere else.
# ─────────────────────────────────────────────────────────────────────────────
step "1. Identity — what this node published"
SRC=""; MACHINE_ID=""; NODE_JSON="$HOME/.flare/node.json"; RECORDED_TUNNEL=""

if [ -n "$WANT_HOST" ]; then
  HOSTNAME_FQDN="$WANT_HOST"; SRC="--hostname on the command line"
elif [ -n "$SERVER_ID_ARG" ]; then
  HOSTNAME_FQDN="flareshub-$(printf '%s' "$SERVER_ID_ARG" | tr '_' '-').${ZONE}"
  SRC="--server-id on the command line"
elif [ -r "$NODE_JSON" ]; then
  HOSTNAME_FQDN=$(python3 -c '
import json,sys
d=json.load(open(sys.argv[1]))
print(d.get("hostname",""))' "$NODE_JSON" 2>/dev/null || true)
  RECORDED_TUNNEL=$(python3 -c '
import json,sys
d=json.load(open(sys.argv[1]))
print(d.get("tunnel_id",""))' "$NODE_JSON" 2>/dev/null || true)
  RECORDED_ZONE=$(python3 -c '
import json,sys
d=json.load(open(sys.argv[1]))
print(d.get("zone",""))' "$NODE_JSON" 2>/dev/null || true)
  SRC="~/.flare/node.json"
  [ -z "$RECORDED_ZONE" ] || [ "$RECORDED_ZONE" = "$ZONE" ] \
    || die "node.json records zone '${RECORDED_ZONE}' but --zone says '${ZONE}' — name the right one"
elif [ -r /etc/machine-id ]; then
  MACHINE_ID=$(cat /etc/machine-id)
  # Same algorithm as enroll.sh and hub/kernel/identity.py. If these three ever
  # disagree, this script would address a name the node does not answer to.
  SERVER_ID=$(printf '%s' "$MACHINE_ID" | python3 -c '
import sys, hashlib
print("fvn_" + hashlib.sha256(sys.stdin.read().strip().encode()).hexdigest()[:6])')
  HOSTNAME_FQDN="flareshub-$(printf '%s' "$SERVER_ID" | tr '_' '-').${ZONE}"
  SRC="/etc/machine-id (no ~/.flare/node.json on this box)"
else
  HOSTNAME_FQDN=""
fi

if [ -n "$HOSTNAME_FQDN" ]; then
  ok "hostname   : ${HOSTNAME_FQDN}"
  ok "derived from: ${SRC}"
  [ -r "$NODE_JSON" ] || warn "no ~/.flare/node.json — this node's edge presence is recorded nowhere on the box"
  echo "$HOSTNAME_FQDN" | grep -qE "$NODE_HOST_RE" \
    || die "REFUSING: '${HOSTNAME_FQDN}' is not a node hostname (flareshub-fvn-<6hex>.${ZONE})"
else
  warn "this box cannot say what it published — no node.json, no machine-id, no flag"
  warn "listing the zone's node records below; re-run naming one with --hostname"
fi

# ── 2. credentials ───────────────────────────────────────────────────────────
# Same three places enroll.sh looks, in the same order. The VALUE never leaves
# this process: nothing below echoes it, and the only thing printed about it is
# which SOURCE it came from.
step "2. Cloudflare credentials"
TOKEN="${CF_API_TOKEN:-}"
[ -n "$TOKEN" ] && ok "token from : \$CF_API_TOKEN"
for f in "$HOME/.cf-token" /etc/flare/token; do
  [ -n "$TOKEN" ] && break
  [ -r "$f" ] || continue
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

ZONE_ID=$(cf GET "/zones?name=${ZONE}" | jq_py 'r=d.get("result") or [];print(r[0]["id"] if r else "")')
[ -n "$ZONE_ID" ] || die "zone '${ZONE}' not visible to this token — check the token's zone scope"
ACCOUNT_ID=$(cf GET "/zones/${ZONE_ID}" | jq_py 'print((d.get("result") or {}).get("account",{}).get("id",""))')
[ -n "$ACCOUNT_ID" ] || die "could not resolve account id for zone ${ZONE}"
ok "zone       : ${ZONE} (${ZONE_ID:0:8}…)"

# ─────────────────────────────────────────────────────────────────────────────
# 20404845  the zone as the register — who exists, when the box cannot say
#
# kernel/fleet.py already establishes that listing flareshub-* on the zone
# ENUMERATES THE FLEET, with no heartbeat and no central box. That is exactly
# what a cleanup needs when the machine is gone: the record of what it
# published outlived it, on purpose.
# ─────────────────────────────────────────────────────────────────────────────
ALL_DNS=$(cf GET "/zones/${ZONE_ID}/dns_records?per_page=200")
if [ -z "$HOSTNAME_FQDN" ]; then
  step "Node records in ${ZONE}"
  echo "$ALL_DNS" | ZONE="$ZONE" python3 -c '
import json, os, re, sys
z = os.environ["ZONE"]
pat = re.compile(r"^flareshub-fvn-[0-9a-f]{6}\.%s$" % re.escape(z))
rs = (json.load(sys.stdin).get("result") or [])
nodes = [r for r in rs if pat.match((r.get("name") or "").lower())]
other = [r for r in rs if not pat.match((r.get("name") or "").lower())]
for r in nodes:
    print("  node        %-44s -> %s" % (r["name"], (r.get("content") or "")[:44]))
print()
print("  %d record(s) in this zone are NOT nodes and are out of scope:" % len(other))
for r in other:
    print("    %-8s %s" % (r.get("type",""), r.get("name","")))
'
  echo
  die "name one with --hostname (dry run is still the default when you do)"
fi

step "3. What ${HOSTNAME_FQDN} holds at the edge"

# ── DNS ──────────────────────────────────────────────────────────────────────
DNS_ID=$(echo "$ALL_DNS" | HOSTNAME_FQDN="$HOSTNAME_FQDN" python3 -c '
import json, os, sys
h = os.environ["HOSTNAME_FQDN"].lower()
for r in (json.load(sys.stdin).get("result") or []):
    if (r.get("name") or "").lower() == h:
        print(r["id"]); break
')
DNS_CONTENT=""; DNS_TYPE=""
if [ -n "$DNS_ID" ]; then
  DNS_JSON=$(cf GET "/zones/${ZONE_ID}/dns_records/${DNS_ID}")
  DNS_NAME=$(echo "$DNS_JSON" | jq_py 'print((d.get("result") or {}).get("name",""))')
  DNS_TYPE=$(echo "$DNS_JSON" | jq_py 'print((d.get("result") or {}).get("type",""))')
  DNS_CONTENT=$(echo "$DNS_JSON" | jq_py 'print((d.get("result") or {}).get("content",""))')
  assert_mine "dns record" "$DNS_NAME"
  echo "  dns         : ${DNS_NAME}  ${DNS_TYPE} -> ${DNS_CONTENT}"
else
  echo "  dns         : no record for ${HOSTNAME_FQDN} (already gone, or never made)"
fi

# ── tunnel: three ways to find it, because the box may know none of them ─────
# node.json is best. Then the token cloudflared is actually running — which on
# fks-services lives at ~/.cloudflared/token under a USER service, not at
# /etc/cloudflared/token under a system one, so BOTH are read. Last, the DNS
# record itself: a proxied node CNAME points at <tunnel-uuid>.cfargotunnel.com,
# which is the tunnel id in plain sight and survives the machine entirely.
TUNNEL_ID=""; TUNNEL_SRC=""
if [ -n "$RECORDED_TUNNEL" ]; then
  TUNNEL_ID="$RECORDED_TUNNEL"; TUNNEL_SRC="~/.flare/node.json"
fi
if [ -z "$TUNNEL_ID" ]; then
  for tf in /etc/cloudflared/token "$HOME/.cloudflared/token"; do
    [ -n "$TUNNEL_ID" ] && break
    RAW=""
    if [ -r "$tf" ]; then RAW=$(cat "$tf" 2>/dev/null || true)
    elif [ -e "$tf" ]; then RAW=$(sudo -n cat "$tf" 2>/dev/null || true); fi
    [ -n "$RAW" ] || continue
    TUNNEL_ID=$(printf '%s' "$RAW" | python3 -c '
import sys, json, base64
t = sys.stdin.read().strip()
try:
    print(json.loads(base64.b64decode(t + "=" * (-len(t) % 4))).get("t",""))
except Exception:
    print("")' 2>/dev/null || true)
    [ -n "$TUNNEL_ID" ] && TUNNEL_SRC="$tf (running tunnel on this host)"
  done
fi
if [ -z "$TUNNEL_ID" ] && [ -n "$DNS_CONTENT" ]; then
  case "$DNS_CONTENT" in
    *.cfargotunnel.com)
      TUNNEL_ID="${DNS_CONTENT%%.cfargotunnel.com}"
      TUNNEL_SRC="the DNS record's CNAME target";;
  esac
fi

# The CNAME is the edge's own answer to "which tunnel serves this name". If a
# recorded or locally-discovered id disagrees with it, the local record is
# stale — it is the state ksgcohub was already found in once, a DNS name
# pointing at a tunnel nothing runs — and acting on the stale one would edit
# the ingress of a tunnel that is not the one serving this hostname.
case "$DNS_CONTENT" in
  *.cfargotunnel.com)
    CNAME_TUNNEL="${DNS_CONTENT%%.cfargotunnel.com}"
    if [ -n "$TUNNEL_ID" ] && [ "$TUNNEL_ID" != "$CNAME_TUNNEL" ]; then
      warn "tunnel      : ${TUNNEL_SRC} says ${TUNNEL_ID:0:8}… but DNS points at ${CNAME_TUNNEL:0:8}…"
      warn "              trusting DNS — it is what the edge actually routes on"
      TUNNEL_ID="$CNAME_TUNNEL"; TUNNEL_SRC="the DNS record's CNAME target (local record was stale)"
    fi;;
esac

TUNNEL_NAME=""
if [ -n "$TUNNEL_ID" ]; then
  TUNNEL_NAME=$(cf GET "/accounts/${ACCOUNT_ID}/cfd_tunnel/${TUNNEL_ID}" \
    | jq_py 'print((d.get("result") or {}).get("name",""))')
  echo "  tunnel      : ${TUNNEL_NAME:-<unnamed>} (${TUNNEL_ID:0:8}…)  via ${TUNNEL_SRC}"
else
  echo "  tunnel      : could not be identified — no node.json, no local token, no CNAME"
fi

# ── Access app ───────────────────────────────────────────────────────────────
APP_ID=$(cf GET "/accounts/${ACCOUNT_ID}/access/apps?per_page=200" \
  | HOSTNAME_FQDN="$HOSTNAME_FQDN" python3 -c '
import json, os, sys
h = os.environ["HOSTNAME_FQDN"].lower()
for a in (json.load(sys.stdin).get("result") or []):
    if (a.get("domain") or "").lower().rstrip("/") == h:
        print("%s\t%s" % (a["id"], a.get("domain",""))); break
')
APP_DOMAIN=""
if [ -n "$APP_ID" ]; then
  APP_DOMAIN=$(printf '%s' "$APP_ID" | cut -f2)
  APP_ID=$(printf '%s' "$APP_ID" | cut -f1)
  assert_mine "access app domain" "$APP_DOMAIN"
  echo "  access      : app ${APP_ID:0:8}… on ${APP_DOMAIN}"
else
  echo "  access      : no app on ${HOSTNAME_FQDN}"
fi

# ─────────────────────────────────────────────────────────────────────────────
# 20404843  ingress — REMOVE ONE RULE, and refuse if anything else would vanish
#
# The exact mirror of enroll.sh's merge. The API takes the WHOLE array, so a
# naive PUT deletes every rule it does not mention; enroll.sh adds one rule and
# refuses the write if a hostname would be lost, and removal has to hold itself
# to the same standard in the other direction: exactly one hostname may
# disappear, and it must be ours.
#
# An ingress we cannot READ is not an empty ingress. A tunnel whose config_src
# is "local" keeps its rules in a file on the host and the API returns nothing
# for it. Treating that as "serves no hostnames" would delete a live tunnel, so
# an unreadable config is UNKNOWN and every write below is refused.
# ─────────────────────────────────────────────────────────────────────────────
INGRESS_STATE="unknown"; NEW_INGRESS=""; INGRESS_REPORT=""
if [ -n "$TUNNEL_ID" ]; then
  CUR=$(cf GET "/accounts/${ACCOUNT_ID}/cfd_tunnel/${TUNNEL_ID}/configurations")
  PLAN=$(echo "$CUR" | HOSTNAME_FQDN="$HOSTNAME_FQDN" python3 -c '
import json, os, sys
mine = os.environ["HOSTNAME_FQDN"].lower()
try:
    res = json.load(sys.stdin).get("result")
except Exception:
    res = None
if not isinstance(res, dict) or not isinstance(res.get("config"), dict) \
        or "ingress" not in res["config"]:
    print(json.dumps({"state": "unreadable"}))
    sys.exit(0)
cur    = res["config"]["ingress"] or []
named  = [r for r in cur if r.get("hostname")]
before = [r["hostname"] for r in named]
keep   = [r for r in named if (r.get("hostname") or "").lower() != mine]
after  = [r["hostname"] for r in keep]
lost   = [h for h in before if h not in after]
if [h for h in lost if h.lower() != mine]:
    print(json.dumps({"state": "refuse", "lost": lost}))
    sys.exit(0)
body = {"config": {"ingress": keep + [{"service": "http_status:404"}]}}
print(json.dumps({"state": "ok", "present": mine in [h.lower() for h in before],
                  "keep": after, "body": body}))
')
  INGRESS_STATE=$(echo "$PLAN" | jq_py 'print(d.get("state","unknown"))')
  case "$INGRESS_STATE" in
    unreadable)
      warn "ingress     : this tunnel's config is not readable over the API (config_src=local?)"
      warn "              an ingress we cannot read is NOT an empty ingress — no write will be attempted";;
    refuse)
      LOST=$(echo "$PLAN" | jq_py 'print(", ".join(d.get("lost") or []))')
      die "REFUSING: removing ${HOSTNAME_FQDN} would also drop ${LOST}";;
    ok)
      PRESENT=$(echo "$PLAN" | jq_py 'print(d.get("present"))')
      KEEPN=$(echo "$PLAN" | jq_py 'print(len(d.get("keep") or []))')
      NEW_INGRESS=$(echo "$PLAN" | python3 -c 'import sys,json;print(json.dumps(json.load(sys.stdin)["body"]))')
      INGRESS_REPORT=$(echo "$PLAN" | python3 -c '
import sys, json
d = json.load(sys.stdin)
for h in d.get("keep") or []:
    print("                  keep    %s" % h)
')
      if [ "$PRESENT" = "True" ]; then
        echo "  ingress     : 1 rule removed (${HOSTNAME_FQDN}), ${KEEPN} hostname(s) kept"
      else
        echo "  ingress     : ${HOSTNAME_FQDN} has no rule on this tunnel; ${KEEPN} hostname(s) kept"
        NEW_INGRESS=""
      fi
      [ -n "$INGRESS_REPORT" ] && echo "$INGRESS_REPORT";;
  esac
fi

# ─────────────────────────────────────────────────────────────────────────────
# 20404844  the tunnel's fate — an orphan is deleted, a shared one never is
#
# ONE BOX, ONE TUNNEL, MANY HOSTNAMES is enroll.sh's rule, and it is the reason
# this is the most careful decision here. babyhelp's tunnel on ksgcohub serves
# babyhelp.ksgco.app, hub.ksgco.app and ntfy.ksgco.app ALONGSIDE the node
# hostname; those are in a different zone, but they are in the SAME ingress
# array, which is why the ingress — not the zone — is what gets asked.
#
# Delete only when nothing is left on it at all. Anything else is reported as
# "could not remove, and why", which is the honest answer.
# ─────────────────────────────────────────────────────────────────────────────
TUNNEL_FATE="keep"; TUNNEL_WHY=""
if [ -z "$TUNNEL_ID" ]; then
  TUNNEL_FATE="keep"; TUNNEL_WHY="no tunnel identified"
elif [ "$INGRESS_STATE" != "ok" ]; then
  TUNNEL_FATE="keep"; TUNNEL_WHY="ingress could not be read, so 'serves nothing else' cannot be established"
else
  REMAIN=$(echo "$PLAN" | jq_py 'print(len(d.get("keep") or []))')
  if [ "${REMAIN:-1}" = "0" ]; then
    TUNNEL_FATE="delete"; TUNNEL_WHY="no hostname remains on it once ours is gone"
  else
    TUNNEL_WHY="still serves ${REMAIN} other hostname(s) — shared, so it stays"
  fi
fi
echo "  tunnel fate : ${TUNNEL_FATE} — ${TUNNEL_WHY}"

# ── the plan, then either stop or do it ──────────────────────────────────────
step "4. Plan"
echo "  These, and only these, would be removed:"
[ -n "$DNS_ID" ]  && echo "    DNS      ${HOSTNAME_FQDN}  (${DNS_TYPE} -> ${DNS_CONTENT})" \
                  || echo "    DNS      nothing to remove"
[ -n "$NEW_INGRESS" ] && echo "    ingress  one rule on tunnel ${TUNNEL_ID:0:8}… for ${HOSTNAME_FQDN}" \
                      || echo "    ingress  nothing to remove"
[ -n "$APP_ID" ]  && echo "    access   app ${APP_ID:0:8}… on ${HOSTNAME_FQDN}" \
                  || echo "    access   nothing to remove"
[ "$TUNNEL_FATE" = "delete" ] && echo "    tunnel   ${TUNNEL_NAME} (${TUNNEL_ID:0:8}…) — ${TUNNEL_WHY}" \
                              || echo "    tunnel   KEPT — ${TUNNEL_WHY}"
# node.json is the only thing on the box that says what it published, so it is
# moved aside ONLY when there is nothing left to come back and finish. If the
# ingress could not be read or a call failed, the file is what a second run
# needs; throwing it away would recreate the fks-services situation on purpose.
if [ ! -r "$NODE_JSON" ]; then
  echo "    local    nothing — this box holds no node.json"
elif [ "$INGRESS_STATE" = "ok" ] || [ -z "$TUNNEL_ID" ]; then
  echo "    local    ${NODE_JSON} moved aside (a record of a presence that no longer exists)"
else
  echo "    local    ${NODE_JSON} KEPT — the edge would not be fully cleared, and this is the only record of it"
fi
echo
echo "  NOT TOUCHED, whatever happens: the hub, its database, its containers,"
echo "  its data, cloudflared's service, and every name in ${ZONE} that is not"
echo "  ${HOSTNAME_FQDN}."

if [ "$ARMED" != "1" ]; then
  step "DRY RUN — nothing above was changed"
  echo "  To do it for real, name the hostname on the command line:"
  echo "    $0 --zone ${ZONE} --remove ${HOSTNAME_FQDN}"
  exit 0
fi

[ "$CONFIRM_HOST" = "$HOSTNAME_FQDN" ] \
  || die "--remove '${CONFIRM_HOST}' does not match the hostname this run derived (${HOSTNAME_FQDN})"

# ─────────────────────────────────────────────────────────────────────────────
# ORDER MATTERS. DNS first.
#
# Removing the Access app first would leave a name that still resolves and
# still reaches the hub, with no gate in front of it — the exact four-minute
# window enroll.sh's ALIAS_FQDN comment exists to describe. Removing DNS first
# makes the name stop resolving, and everything after it is tidying.
# ─────────────────────────────────────────────────────────────────────────────
step "5. Removing"
FAILED=""

if [ -n "$DNS_ID" ]; then
  R=$(cf DELETE "/zones/${ZONE_ID}/dns_records/${DNS_ID}")
  echo "$R" | jq_py 'print(d.get("success"))' | grep -q True \
    && ok "dns        : ${HOSTNAME_FQDN} removed" \
    || { warn "dns        : delete did not report success"; FAILED="${FAILED}dns "; }
fi

if [ -n "$NEW_INGRESS" ]; then
  R=$(cf PUT "/accounts/${ACCOUNT_ID}/cfd_tunnel/${TUNNEL_ID}/configurations" "$NEW_INGRESS")
  echo "$R" | jq_py 'print(d.get("success"))' | grep -q True \
    && ok "ingress    : rule removed, every other hostname kept" \
    || { warn "ingress    : PUT did not report success"; FAILED="${FAILED}ingress "; }
fi

if [ -n "$APP_ID" ]; then
  R=$(cf DELETE "/accounts/${ACCOUNT_ID}/access/apps/${APP_ID}")
  echo "$R" | jq_py 'print(d.get("success"))' | grep -q True \
    && ok "access     : app removed" \
    || { warn "access     : delete did not report success"; FAILED="${FAILED}access "; }
fi

if [ "$TUNNEL_FATE" = "delete" ]; then
  R=$(cf DELETE "/accounts/${ACCOUNT_ID}/cfd_tunnel/${TUNNEL_ID}")
  if echo "$R" | jq_py 'print(d.get("success"))' | grep -q True; then
    ok "tunnel     : ${TUNNEL_NAME} deleted (it served nothing else)"
  else
    # Cloudflare refuses to delete a tunnel with a live connector. That is a
    # correct refusal, not a bug here: stop cloudflared on the box, then re-run.
    warn "tunnel     : not deleted — $(echo "$R" | jq_py 'e=(d.get("errors") or [{}])[0];print(e.get("message","no reason given"))')"
    FAILED="${FAILED}tunnel "
  fi
else
  warn "tunnel     : left alone — ${TUNNEL_WHY}"
fi

if [ -r "$NODE_JSON" ]; then
  if [ -z "$FAILED" ] && { [ "$INGRESS_STATE" = "ok" ] || [ -z "$TUNNEL_ID" ]; }; then
    mv "$NODE_JSON" "${NODE_JSON}.decommissioned.$(date -u +%Y%m%dT%H%M%SZ)"
    ok "local      : node.json moved aside (not deleted — it is the only record of what was here)"
  else
    warn "local      : node.json KEPT — something is still at the edge and this file is how you find it"
  fi
fi

step "Done"
if [ -n "$FAILED" ]; then
  echo "  COULD NOT REMOVE: ${FAILED}"
  echo "  Everything else is gone. Re-run to retry what is left; it is idempotent."
else
  echo "  ${HOSTNAME_FQDN} no longer exists at the edge."
fi
echo "  The box itself is untouched — reach it on the LAN or over Tailscale."
