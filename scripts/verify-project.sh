#!/bin/bash
# ============================================================
# VERIFY NEW DOCKER PROJECT
# Run before installing any new docker-compose project.
# Usage: bash verify-project.sh /path/to/docker-compose.yml
# ============================================================

COMPOSE_FILE="${1:-docker-compose.yml}"

if [ ! -f "$COMPOSE_FILE" ]; then
  echo "Usage: verify-project.sh /path/to/docker-compose.yml"
  exit 1
fi

echo ""
echo "=========================================="
echo "  PROJECT VERIFICATION"
echo "  File: $COMPOSE_FILE"
echo "=========================================="

PASS=0
WARN=0
FAIL=0

flag_ok()   { echo "  [OK]   $1"; ((PASS++)); }
flag_warn() { echo "  [WARN] $1"; ((WARN++)); }
flag_fail() { echo "  [FAIL] $1"; ((FAIL++)); }

# --- Extract ports from compose file ---
echo ""
echo "  PORT CONFLICTS"
echo "  ──────────────────────────────────────"
ports=$(grep -E '^\s+- "[0-9]+:[0-9]+"' "$COMPOSE_FILE" | grep -oE '[0-9]+:[0-9]+' | cut -d: -f1)
if [ -z "$ports" ]; then
  ports=$(grep -E '^\s+- [0-9]+:[0-9]+' "$COMPOSE_FILE" | grep -oE '[0-9]+:[0-9]+' | cut -d: -f1)
fi

if [ -z "$ports" ]; then
  flag_warn "No host ports found — container may be internal only"
else
  for port in $ports; do
    if ss -tlnp | grep -q ":${port} "; then
      process=$(ss -tlnp | grep ":${port} " | grep -oP 'users:\(\("\K[^"]+')
      flag_fail "Port $port already in use by: $process"
    else
      flag_ok "Port $port is free"
    fi
  done
fi

# --- Container name conflicts ---
echo ""
echo "  CONTAINER NAME CONFLICTS"
echo "  ──────────────────────────────────────"
container_names=$(grep -E '^    container_name:' "$COMPOSE_FILE" | awk '{print $2}')
for name in $container_names; do
  if docker ps -a --format '{{.Names}}' | grep -qx "$name"; then
    flag_fail "Container name '$name' already exists"
  else
    flag_ok "Container name '$name' is free"
  fi
done

# --- Proxy network check ---
echo ""
echo "  NETWORK"
echo "  ──────────────────────────────────────"
if grep -q "proxy" "$COMPOSE_FILE"; then
  if docker network ls | grep -q "proxy"; then
    flag_ok "Uses 'proxy' network — exists on this server"
  else
    flag_fail "Uses 'proxy' network — NOT found, create it first: docker network create proxy"
  fi
else
  flag_warn "Does not use 'proxy' network — won't be routable through NPM"
fi

# --- Volume conflicts ---
echo ""
echo "  VOLUMES"
echo "  ──────────────────────────────────────"
volumes=$(grep -E '^  [a-z].*:$' "$COMPOSE_FILE" | awk '{print $1}' | tr -d ':')
project_dir=$(dirname "$COMPOSE_FILE")
project_name=$(basename "$project_dir")
for vol in $volumes; do
  full_name="${project_name}_${vol}"
  if docker volume ls | grep -q "$full_name"; then
    flag_warn "Volume '$full_name' already exists — data will persist from previous install"
  else
    flag_ok "Volume '$vol' is new"
  fi
done

# --- Environment variables ---
echo ""
echo "  ENVIRONMENT / SECRETS"
echo "  ──────────────────────────────────────"
env_file="$(dirname "$COMPOSE_FILE")/.env"
if grep -q "env_file\|\.env" "$COMPOSE_FILE"; then
  if [ -f "$env_file" ]; then
    flag_ok ".env file found"
  else
    flag_fail ".env file referenced but missing at $env_file"
  fi
else
  flag_ok "No .env file required"
fi

# --- Summary ---
echo ""
echo "  ──────────────────────────────────────"
echo "  Results: $PASS OK  |  $WARN WARN  |  $FAIL FAIL"
if [ "$FAIL" -gt 0 ]; then
  echo "  Status: FIX ISSUES BEFORE INSTALLING"
elif [ "$WARN" -gt 0 ]; then
  echo "  Status: REVIEW WARNINGS THEN INSTALL"
else
  echo "  Status: CLEAR TO INSTALL"
fi
echo "=========================================="
echo ""
