#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# bootstrap.sh — Server Kit minimal boot
# Gets the hub up at :8765 in under 5 minutes.
# Run the rest of the stack from inside the hub.
#
# Usage:
#   curl -fsSL https://raw.githubusercontent.com/KGSHOPINV/claude-server/master/bootstrap.sh | bash
#   — or —
#   git clone https://github.com/KGSHOPINV/claude-server ~/hub && bash ~/hub/bootstrap.sh
#
#   bash ~/hub/bootstrap.sh --check     is this node finished? changes nothing
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail

# ── colours ──────────────────────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
BLUE='\033[0;34m'; CYAN='\033[0;36m'; BOLD='\033[1m'; RESET='\033[0m'

ok()   { echo -e "${GREEN}✓${RESET}  $*"; }
info() { echo -e "${CYAN}→${RESET}  $*"; }
warn() { echo -e "${YELLOW}⚠${RESET}  $*"; }
die()  { echo -e "${RED}✗${RESET}  $*" >&2; exit 1; }
step() { echo -e "\n${BOLD}${BLUE}[$1/5]${RESET} ${BOLD}$2${RESET}"; }

# ── banner ────────────────────────────────────────────────────────────────────
echo -e "
${BOLD}${CYAN}  ╔══════════════════════════════════════╗
  ║       Server Kit — Bootstrap         ║
  ║   Hub will be live at :8765          ║
  ╚══════════════════════════════════════╝${RESET}
"

# ── --check: converge, do not install ────────────────────────────────────────
# An installer that can only run on a bare machine is a one-shot script. This
# one answers "is this node finished?" on any box, at any time, changing
# nothing -- so the gap between what was documented and what was done stops
# being invisible.
if [ "${1:-}" = "--check" ]; then
  HUB_DIR="${HUB_DIR:-$HOME/hub}"
  exec python3 "$HUB_DIR/hub/tools/install-preflight.py" "${2:---strict}"
fi

# ── interactive check ────────────────────────────────────────────────────────
# This script asks for a password with `read -rp`. Under `set -euo pipefail`
# and a piped stdin (curl | bash), that read hits EOF and the script dies --
# AFTER installing Docker and cloning the repo, leaving a half-built machine.
# Refuse up front instead, while nothing has been changed yet.
if [ ! -t 0 ]; then
  echo "bootstrap.sh needs an interactive terminal (it asks for an admin password)." >&2
  echo "  Download first, then run it:" >&2
  echo "    git clone https://github.com/KGSHOPINV/claude-server ~/hub && bash ~/hub/bootstrap.sh" >&2
  exit 1
fi

# ── root check ────────────────────────────────────────────────────────────────
[[ $EUID -eq 0 ]] && die "Don't run as root. Run as your normal user (with sudo access)."

# ── OS detection ─────────────────────────────────────────────────────────────
step 1 "Detecting OS"
if [ -f /etc/os-release ]; then
  . /etc/os-release
  OS_ID="${ID:-unknown}"
  OS_NAME="${PRETTY_NAME:-unknown}"
else
  die "Cannot read /etc/os-release — unsupported OS"
fi

case "$OS_ID" in
  ubuntu|debian|raspbian)
    PKG_UPDATE="sudo apt-get update -qq"
    PKG_INSTALL="sudo apt-get install -y -qq"
    ;;
  fedora|rhel|centos|rocky|almalinux)
    PKG_UPDATE="sudo dnf check-update -q || true"
    PKG_INSTALL="sudo dnf install -y -q"
    ;;
  arch|manjaro)
    PKG_UPDATE="sudo pacman -Sy --noconfirm"
    PKG_INSTALL="sudo pacman -S --noconfirm"
    ;;
  *)
    warn "Unrecognised OS: $OS_ID — attempting apt fallback"
    PKG_UPDATE="sudo apt-get update -qq"
    PKG_INSTALL="sudo apt-get install -y -qq"
    ;;
esac

ok "Detected: $OS_NAME"
info "Package manager set"

# ── system packages ───────────────────────────────────────────────────────────
step 2 "Installing system packages"
info "Updating package index..."
eval "$PKG_UPDATE"

PACKAGES="curl git python3 python3-pip ufw"
info "Installing: $PACKAGES"
eval "$PKG_INSTALL $PACKAGES"
ok "System packages ready"

# ── Docker ────────────────────────────────────────────────────────────────────
step 3 "Installing Docker"
if command -v docker &>/dev/null; then
  ok "Docker already installed ($(docker --version | cut -d' ' -f3 | tr -d ','))"
else
  info "Fetching Docker install script..."
  curl -fsSL https://get.docker.com | sudo sh
  sudo usermod -aG docker "$USER"
  ok "Docker installed"
  warn "You may need to log out and back in for Docker group to take effect"
  warn "If docker commands fail, run: newgrp docker"
fi

# Ensure Docker is running
sudo systemctl enable docker --quiet
sudo systemctl start docker
ok "Docker is running"

# ── Clone / update hub ────────────────────────────────────────────────────────
step 4 "Setting up the hub"
HUB_DIR="$HOME/hub"

if [ -d "$HUB_DIR/.git" ]; then
  info "Hub already cloned — pulling latest..."
  git -C "$HUB_DIR" pull --quiet
  ok "Hub updated"
else
  info "Cloning hub from GitHub..."
  git clone --quiet https://github.com/KGSHOPINV/claude-server "$HUB_DIR"
  ok "Hub cloned to $HUB_DIR"
fi

# Python dependencies
if [ -f "$HUB_DIR/hub/requirements.txt" ]; then
  info "Installing Python dependencies..."
  pip3 install -q -r "$HUB_DIR/hub/requirements.txt"
  ok "Python deps installed"
fi

# The database directory the HUB ACTUALLY OPENS.
# kernel/db.py:15 resolves DB_PATH as <repo>/db/server.db. This used to create
# $HOME/db, one level too high, so the admin password seeded below went into a
# file nothing ever read and every bootstrapped node silently stood on the
# default credentials instead. Asserted now by tools/install-preflight.py.
mkdir -p "$HUB_DIR/db"

# ── Hub prompt ────────────────────────────────────────────────────────────────
echo ""
echo -e "${BOLD}Quick setup:${RESET}"

# Get server IP
SERVER_IP=$(hostname -I | awk '{print $1}')
read -rp "  Server IP address [${SERVER_IP}]: " INPUT_IP
SERVER_IP="${INPUT_IP:-$SERVER_IP}"

# Admin password
while true; do
  read -rsp "  Hub admin password: " HUB_PASSWORD
  echo ""
  read -rsp "  Confirm password: " HUB_PASSWORD2
  echo ""
  [ "$HUB_PASSWORD" = "$HUB_PASSWORD2" ] && break
  warn "Passwords don't match — try again"
done

# Hash the password in Python (no external deps)
PW_HASH=$(python3 -c "import hashlib; print(hashlib.sha256('${HUB_PASSWORD}'.encode()).hexdigest())")

# Write hub config
cat > "$HUB_DIR/db/.hub_config" <<EOF
SERVER_IP=${SERVER_IP}
HUB_PORT=8765
ADMIN_PW_HASH=${PW_HASH}
BOOTSTRAP_DATE=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
EOF
ok "Hub config written"

# Seed the admin user THROUGH kernel.db, so the schema is defined in exactly
# one place. This script used to CREATE its own users table with different
# columns (id/username/password_hash/created_at) than the one db.py inserts
# into (username/display/password_hash/role/created) -- two schemas for one
# table, in a file the hub never opened anyway.
PW_HASH="$PW_HASH" SERVER_IP="$SERVER_IP" python3 - "$HUB_DIR" <<'PYEOF'
import os, sqlite3, sys
sys.path.insert(0, os.path.join(sys.argv[1], 'hub'))
from kernel.db import DB_PATH, db_ensure_tables

db_ensure_tables()                       # the one schema definition
conn = sqlite3.connect(DB_PATH)
conn.execute("UPDATE users SET password_hash = ? WHERE username = 'admin'",
             (os.environ['PW_HASH'],))
if conn.total_changes == 0:
    conn.execute("INSERT INTO users (username, display, password_hash, role, created) "
                 "VALUES ('admin','Administrator',?,'admin',datetime('now'))",
                 (os.environ['PW_HASH'],))
conn.commit()
conn.close()
print("  Database seeded at %s" % DB_PATH)
PYEOF

# ── systemd service ───────────────────────────────────────────────────────────
step 5 "Starting hub service"
mkdir -p "$HOME/.config/systemd/user" "$HOME/.local/bin"

cat > "$HOME/.config/systemd/user/hub.service" <<EOF
[Unit]
Description=Server Hub
After=network.target

[Service]
Type=simple
WorkingDirectory=${HUB_DIR}/hub
ExecStart=/usr/bin/python3 ${HUB_DIR}/hub/server.py
Restart=on-failure
RestartSec=5
Environment=HUB_LOCAL=1
Environment=HUB_PORT=8765

[Install]
WantedBy=default.target
EOF

# Enable lingering so service survives logout
sudo loginctl enable-linger "$USER" 2>/dev/null || true

systemctl --user daemon-reload
systemctl --user enable hub --quiet
systemctl --user restart hub
sleep 2

# Verify it started
if systemctl --user is-active hub --quiet; then
  ok "Hub service is running"
else
  warn "Hub may have failed to start — check: journalctl --user -u hub -n 30"
fi

# ── Storage, backups, reclamation ─────────────────────────────────────────────
# These three were MASTER.md steps 6-8 and were never implemented. Commit
# fdc4276 -- titled "the two steps bootstrap.sh never had" -- added the scripts
# and did not touch this file, so a fresh node still received neither. Wiring
# them here is the actual fix; the scripts were only ever half of it.

step 6 "Checking storage"
if python3 "$HUB_DIR/hub/tools/storage-preflight.py" 2>/dev/null; then
  :
else
  warn "storage preflight could not run (older checkout?) — continuing"
fi

step 7 "Installing backups"
# The destination is DERIVED by the script from this machine's disks: it must
# be a different physical device from the one holding the data, or a single
# disk failure takes both. Nothing is hardcoded here on purpose.
install -m 755 "$HUB_DIR/hub/tools/backup.sh"  "$HOME/.local/bin/hub-backup.sh"  2>/dev/null || true
install -m 755 "$HUB_DIR/hub/tools/reclaim.sh" "$HOME/.local/bin/hub-reclaim.sh" 2>/dev/null || true

cat > "$HOME/.config/systemd/user/hub-backup.service" <<EOF
[Unit]
Description=ServerHub backup to a device that does not hold the data
[Service]
Type=oneshot
ExecStart=%h/.local/bin/hub-backup.sh
Nice=10
IOSchedulingClass=idle
EOF
cat > "$HOME/.config/systemd/user/hub-backup.timer" <<EOF
[Unit]
Description=Daily ServerHub backup
[Timer]
OnCalendar=*-*-* 03:00:00
RandomizedDelaySec=900
Persistent=true
[Install]
WantedBy=timers.target
EOF

step 8 "Installing cache reclamation"
cat > "$HOME/.config/systemd/user/hub-reclaim.service" <<EOF
[Unit]
Description=Reclaim Docker build cache older than a week
[Service]
Type=oneshot
ExecStart=%h/.local/bin/hub-reclaim.sh
Nice=15
IOSchedulingClass=idle
EOF
cat > "$HOME/.config/systemd/user/hub-reclaim.timer" <<EOF
[Unit]
Description=Weekly Docker cache reclamation
[Timer]
OnCalendar=Sun *-*-* 04:00:00
RandomizedDelaySec=1800
Persistent=true
[Install]
WantedBy=timers.target
EOF

systemctl --user daemon-reload 2>/dev/null || true
systemctl --user enable --now hub-backup.timer hub-reclaim.timer 2>/dev/null   && ok "backup (daily 03:00) and reclamation (Sun 04:00) scheduled"   || warn "timers written but not enabled — run: systemctl --user enable --now hub-backup.timer hub-reclaim.timer"

# ── Finished? ─────────────────────────────────────────────────────────────────
# The installer does not get to declare itself done. It asks.
echo ""
python3 "$HUB_DIR/hub/tools/install-preflight.py" 2>/dev/null || true

# ── UFW ───────────────────────────────────────────────────────────────────────
if command -v ufw &>/dev/null; then
  sudo ufw allow 22/tcp   &>/dev/null  # SSH
  sudo ufw allow 8765/tcp &>/dev/null  # Hub
  sudo ufw --force enable &>/dev/null
  ok "Firewall: 22 (SSH) + 8765 (Hub) open"
fi

# ── Done ─────────────────────────────────────────────────────────────────────
echo -e "
${BOLD}${GREEN}  ══════════════════════════════════════════${RESET}
${BOLD}${GREEN}  ✓  Hub is live${RESET}

  ${BOLD}Open in your browser:${RESET}
  ${CYAN}  http://${SERVER_IP}:8765${RESET}

  ${BOLD}Login:${RESET}
    Username:  admin
    Password:  (what you just set)

  ${BOLD}Next steps — from inside the hub:${RESET}
    → Run the full stack installer (scripts 01–16)
    → Configure port lanes
    → Set up alerts

  ${BOLD}SSH command log:${RESET}
    journalctl --user -u hub -f

${BOLD}${GREEN}  ══════════════════════════════════════════${RESET}
"
