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

# Create db directory
mkdir -p "$HOME/db"

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
cat > "$HOME/db/.hub_config" <<EOF
SERVER_IP=${SERVER_IP}
HUB_PORT=8765
ADMIN_PW_HASH=${PW_HASH}
BOOTSTRAP_DATE=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
EOF
ok "Hub config written"

# Seed the database with admin user
python3 - <<PYEOF
import sqlite3, os
db = os.path.expanduser('~/db/server.db')
c = sqlite3.connect(db)
c.executescript("""
  CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY,
    username TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    created_at TEXT DEFAULT (datetime('now'))
  );
  CREATE TABLE IF NOT EXISTS hub_config (
    key TEXT PRIMARY KEY,
    value TEXT
  );
""")
c.execute("INSERT OR REPLACE INTO users (username, password_hash) VALUES ('admin', ?)", ("${PW_HASH}",))
c.execute("INSERT OR REPLACE INTO hub_config (key, value) VALUES ('server_ip', ?)", ("${SERVER_IP}",))
c.commit()
c.close()
print("  Database seeded")
PYEOF

# ── systemd service ───────────────────────────────────────────────────────────
step 5 "Starting hub service"
mkdir -p "$HOME/.config/systemd/user"

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
