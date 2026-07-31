# Server Installation Map
> What each server-kit script installed and what it left behind.
> Cross-referenced against live server state as of 2026-07-31.

---

## Script 01 — System Setup
**Status: INSTALLED**
- Packages: curl, wget, git, htop, net-tools, unzip, jq, tmux, tree, ufw, fail2ban
- Created: `/srv/docker/`, `/srv/backups/`
- UFW rules opened for all planned service ports
- SSH hardened (backup at `/etc/ssh/sshd_config.bak`)

## Script 02 — Docker
**Status: INSTALLED**
- Docker Engine + Docker Compose (via official install script)
- `proxy` Docker network created

## Script 03 — Nginx Proxy Manager
**Status: INSTALLED | Container: `npm` UP**
- Reverse proxy + SSL termination
- Ports: 80, 443, 81 (admin)
- Compose: `/srv/docker/npm/`

## Script 04 — Cloudflare Tunnel
**Status: UNKNOWN — not running, no folder in /srv/docker/**
- Would create container `cloudflared`
- Outbound-only tunnel — no inbound ports
- **Action needed:** Check if this was skipped or if folder is elsewhere

## Script 05 — Portainer
**Status: INSTALLED | Container: `portainer` UP**
- Docker management web UI
- Port: 9443 (HTTPS)
- Compose: `/srv/docker/portainer/`
- Note: Portainer has an initial-setup timeout — restart if locked out

## Script 06 — Monitoring
**Status: INSTALLED | Containers: `uptime-kuma` UP, `netdata` UP**
- Uptime Kuma: port 3001
- Netdata: port 19999
- Compose: `/srv/docker/uptime-kuma/`, `/srv/docker/netdata/`

## Script 07 — Claude CLI
**Status: INSTALLED**
- Node.js 22 LTS installed system-wide
- Claude Code CLI: `npm install -g @anthropic-ai/claude-code`
- MCP config: `~/.claude/mcp-config.json`
  - filesystem MCP: access to /srv/docker, /srv/backups, /home
  - fetch MCP: HTTP requests
- Access via: `ssh homeserver "claude -p 'your prompt'"` or server-menu option 15

## Script 08 — Extras (Optional Services)
**Status: PARTIALLY INSTALLED**
- Homepage: INSTALLED, UP (port 3000)
- Dozzle: INSTALLED but NOT RUNNING (port 8090)
- **All other extras were NOT selected during setup:**
  - Supabase, PostgreSQL, Redis, MinIO, n8n, SurrealDB
  - Adminer, Grafana, Mailpit, Wiki.js, LanguageTool, Watchtower
- These can be installed anytime by re-running `~/server-kit/08-extras-setup.sh`

## Script 09 — Backup
**Status: INSTALLED**
- CLI tool: `server-backup` at `/usr/local/bin/server-backup`
- Cron: daily at 3:00 AM → `/var/log/server-backup.log`
- Backup dir: `/srv/backups/`
- rclone: may or may not have been installed (optional during setup)

## Script 10 — Linux Helpers
**Status: INSTALLED**
- CLI tools in `/usr/local/bin/`:
  `server-menu`, `port-scan`, `add-project`, `health-check`, `cheatsheet`,
  `kit-update`, `whats-next`, `howdo`, `essentials`, `server-register`,
  `kit-servers`, `kit-sync`
- Bash aliases (in `~/.bashrc`): `menu`, `ports`, `health`, `cheat`,
  `dps`, `dlogs`, `dcu`, `dcd`, `dcr`, `dcp`, `update-kit`
- Note: aliases only work in interactive SSH sessions, not non-interactive commands

## Script 11 — Hardware Monitor
**Status: INSTALLED**
- Packages: lm-sensors, smartmontools, powertop, s-tui, stress
- CLI tool: `hw-monitor` at `/usr/local/bin/hw-monitor`
- Alias: `hw`

## Script 12 — Security
**Status: INSTALLED**
- Packages: rkhunter, lynis, iftop, nethogs, nmap, auditd, unattended-upgrades
- CrowdSec: INSTALLED but currently INACTIVE (check `sudo systemctl start crowdsec`)
- Fail2Ban: ACTIVE — SSH jail: 3 failures = 24h ban; recidive = 1 week ban
- Docker Bench: cloned to `/srv/docker/docker-bench/`
- CLI tool: `security-check`
- Audit rules: `/etc/audit/rules.d/server-kit.rules`
- Auto security updates: enabled

## Script 13 — GitHub Deploy
**Status: UNKNOWN**
- Would install: `gh` CLI, webhook receiver container, `deploy-project` tool
- Check: `which gh` on server to confirm
- Webhook container (port 9000): unknown if deployed

## Script 14 — Terminal Setup
**Status: INSTALLED**
- Packages: tmux, figlet, fastfetch/neofetch
- Login MOTD: `/etc/update-motd.d/99-server-kit` (the banner you see on login)
- tmux config: `~/.tmux.conf`
- CLI tool: `dashboard` (4-pane tmux layout)
- Alias: `dash`

## Script 15 — Server Console
**Status: PARTIALLY INSTALLED**
- ntfy: INSTALLED, UP (port 8085) — push notifications
- Cockpit: port 9090 is listening but browser access was inconsistent
- CLI tools: `server-alert`, `auto-alert`
- Auto-alerts cron: every 15 minutes (checks containers, disk, memory)
- Alert config: `~/.server-alerts.conf`

## Script 16 — AI Stack
**Status: INSTALLED but STOPPED**
- Containers: `ollama`, `open-webui` (NOT running — correct, no GPU)
- Compose: `/srv/docker/ai/`
- CLI tool: `ai-models`
- Ports: 11434 (Ollama), 3004 (Open WebUI)
- Keep OFF until GPU added or small model testing needed

---

## What's NOT Installed (skipped during setup)

These were optional in script 08 and were not selected:

| Service | Port | How to install |
|---------|------|----------------|
| Supabase | 8000 | Re-run `~/server-kit/08-extras-setup.sh` |
| PostgreSQL | 5432 | Included with Supabase |
| SurrealDB | 8181 | Re-run `~/server-kit/08-extras-setup.sh` |
| Redis | 6379 | Re-run `~/server-kit/08-extras-setup.sh` |
| MinIO | 9000/9001 | Re-run `~/server-kit/08-extras-setup.sh` |
| n8n | 5678 | Re-run `~/server-kit/08-extras-setup.sh` |
| Wiki.js | 3003 | Re-run `~/server-kit/08-extras-setup.sh` |
| Grafana | 3002 | Re-run `~/server-kit/08-extras-setup.sh` |
| Adminer | 8083 | Re-run `~/server-kit/08-extras-setup.sh` |
| Mailpit | 8025 | Re-run `~/server-kit/08-extras-setup.sh` |
| LanguageTool | 8084 | Re-run `~/server-kit/08-extras-setup.sh` |
| Watchtower | — | Re-run `~/server-kit/08-extras-setup.sh` |

---

## Open Questions (as of 2026-07-31)

- Port 8080 has an unknown process — not mapped to any Docker container
- Cloudflare tunnel status unknown
- GitHub deploy script (13) — `gh` CLI install status unknown
- CrowdSec is installed but inactive — intentional?
