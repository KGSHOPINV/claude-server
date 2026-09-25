#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# 20404709  tools/reclaim.sh — stop build cache accumulating unwatched
#
# ksgcohub reached 40GB of Docker build cache on a 98GB OS disk, none of it in
# use, oldest entries two weeks old. The disk was at 66% and climbing. Nothing
# was broken -- nothing reclaimed, and nothing was looking.
#
# Keeps the last week so ordinary rebuilds stay fast, and drops the rest. The
# point is a ceiling, not an empty cache.
# ─────────────────────────────────────────────────────────────────────────────
set -uo pipefail

KEEP_HOURS="${RECLAIM_KEEP_HOURS:-168}"     # one week
BEFORE=$(df --output=avail -BG / | tail -1 | tr -dc '0-9')

echo "$(date +%F' '%T) reclaim: keeping cache newer than ${KEEP_HOURS}h"
docker builder prune -af --filter "until=${KEEP_HOURS}h" 2>&1 | tail -2

# Dangling images only. Never -a: that removes images no container is running
# right now, which includes anything stopped and waiting to start again.
docker image prune -f 2>&1 | tail -1

AFTER=$(df --output=avail -BG / | tail -1 | tr -dc '0-9')
echo "$(date +%F' '%T) reclaim: / free ${BEFORE}G -> ${AFTER}G"
