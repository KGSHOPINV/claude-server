#!/usr/bin/env bash
# Update hub from GitHub -- run this instead of git pull.
set -e
cd ~/hub
git pull

# The app lives in hub/. There are no root-level copies any more: the old
# `cp hub/server.py ./server.py` produced a copy that could not resolve the
# kernel package and crashed on import.
cd ~/hub/hub

# Restart. No password is ever embedded here.
if systemctl --user is-enabled --quiet hub 2>/dev/null; then
  systemctl --user restart hub
  echo "Restarted (user service)."
elif sudo -n systemctl restart hub 2>/dev/null; then
  echo "Restarted (system service)."
else
  PID=$(pgrep -f 'python3 .*hub/server\.py' | head -1)
  [ -n "$PID" ] && kill "$PID" && sleep 1
  HUB_LOCAL=1 HUB_PORT=8765 setsid nohup python3 server.py > /tmp/hub.log 2>&1 &
  echo "Restarted manually (PID $!). Note: systemd is not managing the hub."
fi
echo "Update complete."
