#!/bin/bash
# 20404728  ntfy-lib.sh — one answer to "where do the alerts go", for every script
#
# WHY THIS FILE EXISTS. Five scripts each carried their own copy of the same
# eight lines: pick a URL, pick a topic, curl it. Every copy defaulted to
# http://localhost:8085/server-alerts. On fks-services ntfy listens on 7001
# with the topic fks-services and its ACL denies anonymous publish, and none of
# the hub-*.service units set any environment at all — so every copy was a POST
# to a closed port. Fixing one copy fixed one script. This is the block, once.
#
# WHAT READS IT. ~/.server-alerts.conf is where the true values already live:
# NTFY_URL, NTFY_TOPIC, NTFY_TOKEN, and on fks also ANTHROPIC_API_KEY. It is the
# same file hub/kernel/log.py parses. Sourcing it here means the machine's own
# answer wins over anything hardcoded in the repo.
#
# THE DEFAULTS BELOW ARE A GUESS AND ARE ANNOUNCED AS ONE. They are fks-services'
# values. ksgcohub runs ntfy on 8085 with the topic server-alerts and has no
# ~/.server-alerts.conf at all, so on that box these defaults are simply wrong.
# That is why falling through to them prints a warning instead of pretending.
#
# Usage:  . "path/to/ntfy-lib.sh"   then   ntfy_push TITLE PRIORITY TAGS BODY

# 20404729  resolve — env beats the conf file, the conf file beats the defaults
#
# HUB_NTFY_URL/HUB_NTFY_TOPIC are read BEFORE the conf is sourced, because
# sourcing overwrites plain NTFY_URL/NTFY_TOPIC. That ordering is deliberate:
# a unit that sets Environment=NTFY_URL=... (hub-maintenance.service does, with
# the wrong value) loses to the machine's conf, while an operator who exports
# HUB_NTFY_URL to redirect one run still wins over both.
_ntfy_env_url="${HUB_NTFY_URL:-}"
_ntfy_env_topic="${HUB_NTFY_TOPIC:-}"
_ntfy_conf="${SERVER_ALERTS_CONF:-$HOME/.server-alerts.conf}"

_ntfy_from_conf=0
if [ -f "$_ntfy_conf" ]; then
  # shellcheck disable=SC1090
  . "$_ntfy_conf"
  _ntfy_from_conf=1
fi

NTFY_URL="${_ntfy_env_url:-${NTFY_URL:-http://localhost:7001}}"
NTFY_TOPIC="${_ntfy_env_topic:-${NTFY_TOPIC:-fks-services}}"
NTFY_TOKEN="${NTFY_TOKEN:-}"

if [ "$_ntfy_from_conf" -eq 0 ] && [ -z "$_ntfy_env_url" ]; then
  echo "[ntfy] no $_ntfy_conf and no HUB_NTFY_URL — falling back to $NTFY_URL/$NTFY_TOPIC, which is a guess" >&2
fi

# 20404730  ntfy_ascii_header — an em dash in a title used to kill the whole push
#
# ntfy carries Title, Priority and Tags as HTTP headers, and a header value is
# not a UTF-8 field. The same fault in Python cost ksgcohub every alert it ever
# tried to send — 24 failed, 0 sent — which is what kernel/log.py's
# _ascii_header exists for; this is that function in bash. ntfy accepts RFC 2047
# encoded-words in any header, title included (docs.ntfy.sh/publish/#utf-8).
#
# Callers should still put emoji in Tags rather than Title: Tags is the field
# ntfy renders as emoji anyway, so the phone shows the same thing and the header
# never needs encoding. This is the net under them, not a licence.
ntfy_ascii_header() {
  if LC_ALL=C printf '%s' "${1:-}" | LC_ALL=C grep -q '[^ -~]'; then
    printf '=?UTF-8?B?%s?=' "$(printf '%s' "$1" | base64 -w0)"
  else
    printf '%s' "${1:-}"
  fi
}

# 20404731  ntfy_push — send one notification, and say so when it does not land
#
# Returns 0 only on a 2xx. Every other outcome prints one line to stderr, which
# under systemd means one line in the journal naming the URL that refused it.
# The whole reason this bug survived for months is that `curl -s ... >/dev/null`
# reports nothing: a closed port and a delivered alert looked identical.
ntfy_push() { # ntfy_push TITLE PRIORITY TAGS BODY
  local title priority tags body code
  local -a headers
  title="$(ntfy_ascii_header "${1:-Alert}")"
  priority="${2:-default}"
  tags="${3:-server}"
  body="${4:-}"

  headers=(-H "Title: $title" -H "Priority: $priority" -H "Tags: $tags")
  [ -n "${NTFY_TOKEN:-}" ] && headers+=(-H "Authorization: Bearer $NTFY_TOKEN")

  code="$(curl -s -o /dev/null -w '%{http_code}' --max-time 8 -X POST \
            "${headers[@]}" -d "$body" "$NTFY_URL/$NTFY_TOPIC" 2>/dev/null)" || code="000"

  case "$code" in
    2*) return 0 ;;
    401|403)
      if [ -n "${NTFY_TOKEN:-}" ]; then
        echo "[ntfy] HTTP $code — $NTFY_URL/$NTFY_TOPIC rejected the token" >&2
      else
        echo "[ntfy] HTTP $code — $NTFY_URL/$NTFY_TOPIC denies anonymous publish and no NTFY_TOKEN is set" >&2
      fi ;;
    000) echo "[ntfy] could not reach $NTFY_URL/$NTFY_TOPIC" >&2 ;;
    *)   echo "[ntfy] HTTP $code from $NTFY_URL/$NTFY_TOPIC" >&2 ;;
  esac
  return 1
}
