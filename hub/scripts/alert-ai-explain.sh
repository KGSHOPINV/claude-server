#!/bin/bash
# 20404734  alert-ai-explain.sh — ask Claude to explain an alert → ntfy
#
# Usage: echo "alert text" | bash alert-ai-explain.sh
#        bash alert-ai-explain.sh "alert text"
#
# NOTHING INVOKES THIS SCRIPT TODAY. No unit on either box calls it and no
# sibling pipes into it; it is a tool waiting for a caller. Fixed here for the
# same reason as alert-load.sh: it carried the closed-port default, so the first
# thing it ever did would have been to fail.
#
# THE API KEY COMES FROM THE SAME FILE AS THE NTFY CONFIG. This script used to
# require ANTHROPIC_API_KEY in the environment, and the hub-*.service units set
# no environment at all — so even wired up it would have refused on every run.
# ~/.server-alerts.conf on fks-services already carries ANTHROPIC_API_KEY next
# to NTFY_URL/NTFY_TOPIC/NTFY_TOKEN, and ntfy-lib.sh sources that file, so
# sourcing the helper supplies the key too. An exported key still wins.
set -uo pipefail

_d="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
_env_key="${ANTHROPIC_API_KEY:-}"
for _l in "$_d/ntfy-lib.sh" "$_d/../hub/scripts/ntfy-lib.sh" "$_d/hub/scripts/ntfy-lib.sh"; do
  [ -f "$_l" ] && { . "$_l"; break; }
done
command -v ntfy_push >/dev/null || { echo "[alert-ai-explain] ntfy-lib.sh not found — cannot send" >&2; exit 1; }
ANTHROPIC_API_KEY="${_env_key:-${ANTHROPIC_API_KEY:-}}"

MODEL="${AI_EXPLAIN_MODEL:-claude-haiku-4-5-20251001}"

# ai_explain — send alert text to Claude, print the explanation to stdout.
#
# The request body is built by python3 and the reply parsed by it, because both
# ends are JSON: the old version pasted the alert straight into a hand-written
# JSON string (any quote in an alert produced a malformed request) and read the
# reply back with grep -oP '"text":"\K[^"]+', which stops at the first escaped
# quote and prints \n literally. python3 is present on both boxes — it is what
# runs the hub itself.
ai_explain() {
  local alert_text="$1" payload response

  if [ -z "${ANTHROPIC_API_KEY:-}" ]; then
    echo "[ai_explain] ANTHROPIC_API_KEY not set and not in $HOME/.server-alerts.conf — skipping" >&2
    return 1
  fi

  payload=$(ALERT="$alert_text" MODEL="$MODEL" python3 -c '
import json, os
print(json.dumps({
    "model": os.environ["MODEL"],
    "max_tokens": 256,
    "messages": [{"role": "user", "content":
        "You are a home server monitoring assistant. Explain this alert in 1-2 "
        "plain sentences, say what it means and what the admin should check. "
        "Alert: " + os.environ["ALERT"]}],
}))') || { echo "[ai_explain] could not build request" >&2; return 1; }

  response=$(curl -s --max-time 30 -X POST "https://api.anthropic.com/v1/messages" \
    -H "x-api-key: $ANTHROPIC_API_KEY" \
    -H "anthropic-version: 2023-06-01" \
    -H "content-type: application/json" \
    -d "$payload") || { echo "[ai_explain] request failed" >&2; return 1; }

  RESP="$response" python3 -c '
import json, os, sys
try:
    d = json.loads(os.environ["RESP"])
except ValueError:
    sys.exit(1)
if "error" in d:
    sys.stderr.write("[ai_explain] API error: %s\n" % d["error"].get("message", "unknown"))
    sys.exit(1)
print("".join(b.get("text", "") for b in d.get("content", [])).strip())'
}

if [ -n "${1:-}" ]; then
  ALERT_TEXT="$1"
else
  ALERT_TEXT=$(cat)
fi

if [ -z "$ALERT_TEXT" ]; then
  echo "Usage: $0 \"alert text\"  OR  echo \"alert text\" | $0" >&2
  exit 1
fi

EXPLANATION=$(ai_explain "$ALERT_TEXT")

if [ -n "$EXPLANATION" ]; then
  ntfy_push "AI explains: alert" "default" "robot_face,server" "$EXPLANATION"
else
  echo "[alert-ai-explain] No explanation returned from AI." >&2
  exit 1
fi
