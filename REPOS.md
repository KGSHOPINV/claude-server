# Two-Repo Architecture

This project exists across two GitHub repositories with a clear split of responsibility.

---

## Repositories

| Repo | Purpose | Audience |
|------|---------|----------|
| `KGSHOPINV/claude-server` | Hub app — the control panel | Hub developers, iterators |
| `KGSHOPINV/server-kit` | Bootstrap installer — gets a server ready | New server installs |

---

## claude-server (this repo)

**What it is:** The Server Hub — a Python HTTP server + single-page app that gives you a browser-based control panel over a Linux server.

**What it owns:**
- `hub/server.py` — API server, SSH proxy, SQLite, all routes
- `hub/app.html` — full desktop hub application
- `hub/mobile.html` — mobile-optimized view
- `guides/` — markdown docs loaded into the hub
- `notes/` — local scratch (gitignored)
- `db/` — SQLite data (gitignored)

**What it does NOT contain:**
- Docker compose files for any service (those live in server-kit or directly on the server)
- Bootstrap/install scripts for getting a fresh server ready
- Any hardcoded server credentials

**How it gets to the server:**
```bash
# server-kit's install.sh does this automatically:
git clone https://github.com/KGSHOPINV/claude-server ~/hub
```
Then `hub.service` runs `server.py` on the server as a systemd unit with `HUB_LOCAL=1`.

**Independent update cycle:**
```bash
# On the server — update hub without touching Docker stack:
cd ~/hub && git pull && sudo systemctl restart hub
```

---

## server-kit (separate repo)

**What it is:** A complete, USB-ready bootstrap kit for standing up a fresh Linux server with this full Docker stack.

**What it owns:**
- Numbered setup scripts (`01-system-setup.sh` → `16-ai-setup.sh`)
- Docker compose files for every service in `/docker-compose/`
- `tools/` — CLI tools deployed to `/usr/local/bin/`
- `mcp/` — Claude CLI MCP config for server awareness
- `claude/CLAUDE.md` — full server context for Claude sessions
- `install.sh` — one-command installer (asks 4 questions, sets everything up)
- `docs/` and `docs-site/` — documentation

**What it does NOT contain:**
- Hub application code (delegates to claude-server via git clone)
- Any live server state or secrets

**Reference to this repo:**
server-kit's `install.sh` clones `claude-server` at install time:
```bash
git clone https://github.com/KGSHOPINV/claude-server ~/hub
```

---

## Exclusion Rules

| Thing | Goes in | NOT in |
|-------|---------|--------|
| Hub app code | claude-server | server-kit |
| Docker compose files | server-kit | claude-server |
| Bootstrap scripts | server-kit | claude-server |
| Claude MCP config | server-kit | claude-server |
| Secrets / credentials | **neither** (local only, gitignored) | both |
| guides/*.md | claude-server | server-kit |
| CLI tools (/usr/local/bin/) | server-kit | claude-server |

---

## The Lifecycle

```
1. Download server-kit (git clone or zip download)
2. Run: bash install.sh
   → asks: server IP, SSH user, timezone, admin password
   → runs 01-16 setup scripts
   → clones claude-server → ~/hub
   → writes hub.service → starts hub on :8765
3. Browse to http://SERVER_IP:8765
4. Update hub independently: cd ~/hub && git pull && sudo systemctl restart hub
5. Update stack independently: cd ~/server-kit && git pull && bash self-update.sh
```

---

## Manifest / System Pulse

The hub exposes a live snapshot at `/api/manifest` — all services, container states, health, server info, disk — as a single JSON download.

From the hub UI: Settings → "Download System Snapshot"
Direct URL: `http://SERVER_IP:8765/api/manifest?download=1`
