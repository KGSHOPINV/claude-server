#!/usr/bin/env bash
# Option A: give the hub the ntfy token it has never had.
#
# ntfy has been up for two weeks, routed at ntfy.ksgco.app, correctly running
# with --auth-default-access deny-all, and has published exactly ZERO messages.
# Nothing was misconfigured. The hub simply never held a credential for it, and
# _ntfy_send swallowed the 403 every time, so a path delivering nothing looked
# identical to one that worked.
#
# NO CODE CHANGE. kernel/log.py already reads ~/.server-alerts.conf for
# NTFY_URL / NTFY_TOPIC / NTFY_TOKEN. The file has never existed. That is the
# entire defect.
#
# A DEDICATED ACCOUNT, NOT THE ADMIN. There is already a ksgadmin with
# read-write on every topic, and minting its token would be one line shorter.
# But that token then sits in a plaintext file on the same box as everything
# else, and it would let anything that reads the file publish to, subscribe to
# and administer every topic on the server. The hub needs to publish to one
# topic. It gets exactly that.
#
# THE PASSWORD IS NEVER PRINTED AND NEVER STORED. It is generated here, used
# once to create the account, and discarded -- the hub authenticates with the
# token, not the password. Nobody, including the operator, needs to know it.
# If the account ever needs a human login, delete it and run this again.
#
# Usage:  bash enable-ntfy.sh

set -euo pipefail
HOST=ksgco@100.107.234.9
TOPIC=server-alerts
NTFY_USER=hub

ssh -n $HOST "
set -euo pipefail
X='docker exec -e NTFY_AUTH_FILE=/var/cache/ntfy/auth.db ntfy ntfy'

if \$X user list 2>/dev/null | grep -q '^user $NTFY_USER '; then
  echo '==> user $NTFY_USER already exists, leaving it alone'
else
  echo '==> creating $NTFY_USER (non-admin)'
  PW=\$(head -c 32 /dev/urandom | base64 | tr -d '=+/' | head -c 24)
  docker exec -i -e NTFY_AUTH_FILE=/var/cache/ntfy/auth.db ntfy \\
      ntfy user add $NTFY_USER >/dev/null <<EOPW
\$PW
\$PW
EOPW
  unset PW
  echo '   created; password discarded'
fi

echo '==> scoping it to $TOPIC only'
\$X access $NTFY_USER $TOPIC rw
\$X access $NTFY_USER | sed 's/^/   /'

echo '==> minting a token'
TOKEN=\$(\$X token add $NTFY_USER 2>/dev/null | grep -oE 'tk_[A-Za-z0-9]+' | head -1)
if [ -z \"\$TOKEN\" ]; then echo '   FAILED to mint a token, nothing written'; exit 1; fi

echo '==> writing ~/.server-alerts.conf (0600)'
umask 077
cat > ~/.server-alerts.conf <<EOC
# Read by hub/kernel/log.py:_ntfy_send. Created $(date -Iseconds).
# Scoped to the $TOPIC topic only -- not an admin token.
NTFY_URL=http://localhost:8085
NTFY_TOPIC=$TOPIC
NTFY_TOKEN=\$TOKEN
EOC
chmod 600 ~/.server-alerts.conf
ls -l ~/.server-alerts.conf | sed 's/^/   /'

echo '==> proving it publishes BEFORE restarting the hub'
CODE=\$(curl -s -o /dev/null -w '%{http_code}' --max-time 8 \\
  -H \"Authorization: Bearer \$TOKEN\" -H 'Title: hub token test' \\
  -d 'If you can read this, the hub can finally publish.' \\
  http://127.0.0.1:8085/$TOPIC)
unset TOKEN
echo \"   publish: HTTP \$CODE\"
[ \"\$CODE\" = '200' ] || { echo '   NOT restarting the hub on a failed publish'; exit 1; }

echo '==> restarting hub.service so it picks up the conf'
sudo systemctl restart hub.service && sleep 5 && systemctl is-active hub.service

echo '==> ntfy message count (was 0 for two weeks)'
curl -s --max-time 6 http://127.0.0.1:8085/v1/stats
echo
"

cat <<'NEXT'

SUBSCRIBE ON YOUR PHONE
  Install the ntfy app, add server https://ntfy.ksgco.app, topic server-alerts.
  Subscribing needs a credential too, since the server is deny-all. Use the
  ksgadmin account that already exists -- do NOT reuse the hub token, which is
  deliberately scoped to publishing to this one topic.

ROLLBACK
  ssh ksgco@100.107.234.9 'rm -f ~/.server-alerts.conf && sudo systemctl restart hub.service'
  and, to remove the account entirely:
  ssh ksgco@100.107.234.9 'docker exec -e NTFY_AUTH_FILE=/var/cache/ntfy/auth.db ntfy ntfy user del hub'
NEXT
