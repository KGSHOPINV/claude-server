#!/usr/bin/env bash
# Update hub from GitHub — run this instead of git pull
set -e
cd ~/hub
git pull
cp hub/server.py ./server.py
cp hub/app.html ./app.html
cp hub/mobile.html ./mobile.html
# Restart: try systemd first, fall back to kill+nohup
if systemctl is-active --quiet hub 2>/dev/null; then
  echo "Restarting via systemd..."
  echo '1234qwerR' | sudo -S systemctl restart hub 2>/dev/null || kill $(pgrep -f 'python3.*server.py') 2>/dev/null
else
  PID=$(pgrep -f 'python3.*server.py' | head -1)
  [ -n "$PID" ] && kill "$PID" && sleep 1
  HUB_LOCAL=1 HUB_PORT=8765 nohup python3 ~/hub/server.py > /tmp/hub.log 2>&1 &
  echo "Hub restarted (PID $!)"
fi
echo "Update complete."
