#!/bin/bash
# 20404721  alert-startup.sh — one push when the hub comes up, with TRUE values
#
# THE PROBLEM THIS EXISTS FOR, AND WHAT IT GOT WRONG. It fires once from
# hub.service's ExecStartPost and tells the phone where the hub is. Every alert
# it has ever sent from fks-services read:
#
#     🚀 Hub started — fks-services
#     IP: 1000 | Port: 7000 | Uptime: 3d 8h 4m
#
# Both numbers were wrong, and both were wrong in the worst possible way — they
# were plausible. Nobody doubts a four-digit port.
#
#   IP: 1000     `ip route get 1.1.1.1 | awk '/src/{print $NF}'` printed the LAST
#                field of the line, and iproute2 on this kernel ends that line
#                with `uid 1000`:
#                    1.1.1.1 via 192.168.1.1 dev eno1 src 192.168.1.229 uid 1000
#                So the alert reported the invoking user's uid as an IP address.
#                `$NF` is the src address only on a kernel that appends nothing
#                after it, and `$7` is right only until a route gains a field.
#
#   Port: 7000   the unit passes the true port — Environment=HUB_PORT=8765, the
#                same variable server.py reads — and this script then sourced
#                ~/.server-alerts.conf straight OVER it, where a stale
#                HUB_PORT=7000 has sat since 21 August. The fallback default on
#                the next line was 7000 as well, so there was no path through
#                this file by which the real port could ever be printed.
#
# THE RULE, THEREFORE. Read every field by NAME, never by position. Let the
# environment the service was actually started with beat a config file that
# cannot know. Confirm the port against what is listening. And print `unknown`
# where a value cannot be established: an alert that admits a hole stays worth
# reading, while one that fills the hole with 1000 teaches you to stop reading
# alerts — which costs you the next one, the real one.

# Captured BEFORE the config file is sourced, because sourcing overwrites it,
# and that overwrite is half of the bug above.
HUB_PORT_ENV="${HUB_PORT:-}"

[ -f "$HOME/.server-alerts.conf" ] && . "$HOME/.server-alerts.conf"

NTFY_URL="${NTFY_URL:-http://localhost:7001}"
NTFY_TOPIC="${NTFY_TOPIC:-fks-services}"


# 20404722  lan_ip — the src address, read by name because position lies
lan_ip() {
  local addr
  # Walk the fields and take the one AFTER the literal `src`. This is the whole
  # fix for `IP: 1000`: the token names the value, the column does not.
  addr=$(ip route get 1.1.1.1 2>/dev/null \
         | awk '{for (i = 1; i < NF; i++) if ($i == "src") { print $(i + 1); exit }}')
  # A value that is not an address is reported as NO value. This is the guard
  # that would have caught 1000 on the first send instead of the thousandth.
  case "$addr" in
    *.*.*.*|*:*:*) printf '%s' "$addr" ;;
    *)             printf '' ;;
  esac
}


# 20404723  hub_port — the port the hub is ON, confirmed, or nothing
hub_port() {
  # The environment wins. 8765 as a last resort is not a guess: it is the same
  # default handlers/node.py applies when HUB_PORT is unset, so this agrees with
  # the hub by construction rather than by coincidence. The config file is
  # deliberately not consulted — it is a file on one box that nothing keeps in
  # step with the unit, which is how 7000 survived a port change.
  local port="${HUB_PORT_ENV:-8765}"
  case "$port" in ''|*[!0-9]*) printf ''; return 0 ;; esac

  # Confirmed before it is printed. ExecStartPost can run before the socket is
  # bound, and a port nobody is listening on is exactly the kind of number this
  # script used to send with confidence.
  if ! command -v ss >/dev/null 2>&1; then
    # Say which half is missing. "unconfirmed" is a different claim from both
    # "8765" and "unknown", and flattening it into either one loses the fact
    # that nothing here checked.
    printf '%s (unconfirmed — no ss)' "$port"
    return 0
  fi
  local i
  for i in 1 2 3 4 5; do
    if ss -ltn 2>/dev/null | grep -q ":${port}[[:space:]]"; then
      printf '%s' "$port"
      return 0
    fi
    sleep 1
  done
  printf ''
}


HOST=$(hostname 2>/dev/null || echo "server")
LAN_IP=$(lan_ip)
PORT=$(hub_port)
# Labelled `Host up` and not `Uptime`, because /proc/uptime is how long the
# MACHINE has been up. Under a title that says "Hub started" it read as the
# hub's age, which made a hub that had crash-looped all morning look like one
# that had been steady for three days. Same class of defect as the other two:
# a true number in a slot that renames it into a false one.
HOST_UP=$(awk '{s=int($1); printf "%dd %dh %dm", s/86400, (s%86400)/3600, (s%3600)/60}' /proc/uptime 2>/dev/null)

TITLE="🚀 Hub started — $HOST"
BODY="IP: ${LAN_IP:-unknown} | Port: ${PORT:-unknown — nothing listening yet} | Host up: ${HOST_UP:-unknown}"

HEADERS=(-H "Title: $TITLE" -H "Priority: default" -H "Tags: rocket,server")
[ -n "$NTFY_TOKEN" ] && HEADERS+=(-H "Authorization: Bearer $NTFY_TOKEN")

curl -s -o /dev/null --max-time 5 "${HEADERS[@]}" -d "$BODY" "$NTFY_URL/$NTFY_TOPIC" 2>/dev/null || true
