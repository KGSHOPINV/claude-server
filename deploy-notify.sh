#!/usr/bin/env bash
# Deploy the notification unit to ksgcohub's live hub. Nothing else.
#
# Six files. Three are new and cannot affect anything that does not call them.
# Three are modified, and each was diffed against the LIVE file first:
#
#   kernel/router.py      +11 lines, exactly the three new routes and nothing
#                         else -- the project port band lives in collect.py,
#                         which this does not touch.
#   app.html              68 changed lines, every one of them notification.
#   handlers/identity.py  ONE hunk: serve_sw reads ui/sw.js instead of serving
#                         a one-line stub. Patched IN PLACE on the server from
#                         the live file, so the flarevault splash that sits in
#                         this branch's copy is NOT deployed. The patch refuses
#                         if the live file is not what was verified.
#
# Deliberately NOT a git checkout. The branch also carries the project port
# band move, which must not ship before the projects have been told.
#
# Usage:  bash deploy-notify.sh

set -euo pipefail
HOST=ksgco@100.107.234.9
DEST=/home/ksgco/hub/hub
HERE="$(cd "$(dirname "$0")" && pwd)"

echo "==> checkpoint"
ssh -n $HOST '
  if [ -s /tmp/notify-checkpoint.txt ] && [ -d "$(cat /tmp/notify-checkpoint.txt)" ]; then
    echo "  reusing $(cat /tmp/notify-checkpoint.txt)"
  else
    BK=/home/ksgco/hub-checkpoints/notify-$(date +%Y%m%d-%H%M%S)
    mkdir -p $BK/handlers $BK/kernel
    cd /home/ksgco/hub/hub
    cp app.html $BK/ && cp kernel/router.py $BK/kernel/ && cp handlers/identity.py $BK/handlers/
    echo $BK > /tmp/notify-checkpoint.txt
    echo "  created $BK"
  fi'

echo "==> copying five files"
scp -q "$HERE/hub/handlers/events_stream.py" $HOST:$DEST/handlers/events_stream.py
scp -q "$HERE/hub/ui/sw.js" "$HERE/hub/ui/notify.js"  $HOST:$DEST/ui/
scp -q "$HERE/hub/NOTIFY.md"                          $HOST:$DEST/NOTIFY.md
scp -q "$HERE/hub/kernel/router.py"                   $HOST:$DEST/kernel/router.py
scp -q "$HERE/hub/app.html"                           $HOST:$DEST/app.html

echo "==> patching handlers/identity.py in place (serve_sw only)"
ssh -n $HOST "python3 - <<'PYEOF'
import io
P = '/home/ksgco/hub/hub/handlers/identity.py'
t = io.open(P, encoding='utf-8', newline='').read().replace('\r\n', '\n')

if 'ui/sw.js' in t:
    print('  already patched, leaving alone'); raise SystemExit(0)

old = '''def serve_sw(handler, path, params):
    \"\"\"# 20301704  GET /sw.js\"\"\"
    sw = b\"self.addEventListener('fetch', () => {});\"
'''
new = '''def serve_sw(handler, path, params):
    \"\"\"# 20301704  GET /sw.js — served from ui/sw.js, at ROOT scope

    The file lives in ui/ but is served from / because a service worker can
    only control the paths at or below the URL it was served from. At /ui/sw.js
    it would control ui/ and nothing else, which is useless for both the install
    prompt and notifications.

    The previous body was one line -- an empty fetch listener -- and app.html
    never registered it. That is why \"Install app\" never appeared and why no
    notification could be shown: showNotification() requires a registration.

    The inline fallback keeps a hub with a missing ui/ serving something valid
    rather than a 500, because a broken service worker can wedge a PWA.
    \"\"\"
    try:
        with open(os.path.join(UI_DIR, 'sw.js'), 'rb') as f:
            sw = f.read()
    except Exception:
        sw = b\"self.addEventListener('fetch', () => {});\"
'''
if old not in t:
    # Refuse rather than guess. A half-applied edit to a live handler is worse
    # than no edit, and the checkpoint above is the way back either way.
    print('  REFUSED: live serve_sw is not what was verified. Nothing changed.')
    raise SystemExit(1)

io.open(P, 'w', encoding='utf-8', newline='\n').write(t.replace(old, new, 1))
print('  patched')
PYEOF"

echo "==> compiling before restart, so a syntax error never reaches the service"
ssh -n $HOST "cd $DEST && python3 -m py_compile handlers/identity.py handlers/events_stream.py kernel/router.py && echo '  compiles'"

echo "==> restarting hub.service"
ssh -n $HOST 'sudo systemctl restart hub.service && sleep 5 && systemctl is-active hub.service'

echo "==> verifying"
ssh -n $HOST '
  curl -s --max-time 10 http://127.0.0.1:8765/api/events/self \
    | python3 -c "import sys,json;d=json.load(sys.stdin);print(\"  self-check ok:\",d[\"ok\"],\"--\",d[\"verdict\"]);print(\"  holding:\",d[\"holding\"][\"rows\"],\"rows\")"
  echo "  --- 5 seconds on the live stream ---"
  timeout 5 curl -sN "http://127.0.0.1:8765/api/events/stream?level=info" | head -4
  echo "  --- what the hub already served must still serve ---"
  for p in / /api/status /sw.js /ui/notify.js /ui/registry.js; do
    printf "  %-18s %s\n" "$p" "$(curl -s -o /dev/null -w "%{http_code}" --max-time 8 http://127.0.0.1:8765$p)"
  done'

cat <<'ROLLBACK'

ROLLBACK, if anything looks wrong. Restores the three modified files from the
checkpoint and removes the new ones, which is a complete undo:

  ssh ksgco@100.107.234.9 'BK=$(cat /tmp/notify-checkpoint.txt); cd /home/ksgco/hub/hub \
    && cp $BK/app.html . \
    && cp $BK/kernel/router.py kernel/ \
    && cp $BK/handlers/identity.py handlers/ \
    && rm -f handlers/events_stream.py ui/sw.js ui/notify.js NOTIFY.md \
    && sudo systemctl restart hub.service'
ROLLBACK
