#!/bin/bash
# alert-ai-explain.sh — Ask Claude to explain an alert in plain English → ntfy
# Usage: echo "alert text" | bash alert-ai-explain.sh
#        bash alert-ai-explain.sh "alert text"
# Requires: ANTHROPIC_API_KEY set in environment
NTFY="${HUB_NTFY_URL:-http://localhost:8085}/server-alerts"
MODEL="claude-haiku-4-5-20251001"

# ai_explain() — send alert text to Claude and return a plain-English explanation
# Call this with the raw alert string; it prints the explanation to stdout.
ai_explain() {
  local alert_text="$1"

  if [ -z "$ANTHROPIC_API_KEY" ]; then
    echo "[ai_explain] ANTHROPIC_API_KEY not set — skipping AI explanation" >&2
    return 1
  fi

  local response
  response=$(curl -s -X POST "https://api.anthropic.com/v1/messages" \
    -H "x-api-key: $ANTHROPIC_API_KEY" \
    -H "anthropic-version: 2023-06-01" \
    -H "content-type: application/json" \
    -d "{
      \"model\": \"$MODEL\",
      \"max_tokens\": 256,
      \"messages\": [{
        \"role\": \"user\",
        \"content\": \"You are a home server monitoring assistant. Explain this alert in 1-2 plain sentences, say what it means and what the admin should check. Alert: $alert_text\"
      }]
    }")

  echo "$response" | grep -oP '"text"\s*:\s*"\K[^"]+' | head -1
}

# Read alert text from argument or stdin
if [ -n "$1" ]; then
  ALERT_TEXT="$1"
else
  ALERT_TEXT=$(cat)
fi

if [ -z "$ALERT_TEXT" ]; then
  echo "Usage: $0 \"alert text\"  OR  echo \"alert text\" | $0" >&2
  exit 1
fi

# Get AI explanation and forward to ntfy
EXPLANATION=$(ai_explain "$ALERT_TEXT")

if [ -n "$EXPLANATION" ]; then
  curl -s -X POST "$NTFY" \
    -H "Title: 🤖 AI Explains: Alert" \
    -H "Priority: default" \
    -H "Tags: robot_face,server" \
    -d "$EXPLANATION" > /dev/null
else
  echo "[alert-ai-explain] No explanation returned from AI." >&2
fi
