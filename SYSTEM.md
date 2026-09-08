# ServerHub -- System Map

> Read this first. One file, full picture.

---

## The Premise

ServerHub is a control plane for a Linux server running Docker.

One Python file (`hub/server.py`) runs as a systemd service. It gives you a browser UI and JSON API over everything happening on the server -- containers, disk, RAM, ports, logs, credentials, and AI.

**Hard requirements:** Docker + Python 3. That is all.

Everything else -- Portainer, Netdata, n8n, Uptime Kuma, all of it -- are **optional services** that ServerHub manages. Hub does not depend on any of them. Hub watches them, reports on them, lets you control them from the browser, and alerts you when they go wrong.

No npm. No frameworks. No build step. Pure Python stdlib.

**Port:** `:8765`

---

## How a New Server Gets Set Up

**server-kit is the entry point.** It bootstraps a blank Ubuntu server into a full running stack:

```bash
git clone https://github.com/KGSHOPINV/server-kit
cd server-kit
bash install.sh
```

`install.sh` asks which optional services you want, then:
- Sets up Docker and system dependencies
- Deploys the services you selected under `/srv/docker/`
- Clones `claude-server` into `~/hub`
- Writes `hub.service` and starts ServerHub on port 7000

After that: `http://SERVER_IP:7000` -- you are live.

**That is the only install path. server-kit owns it.**

---

## Two Repos -- Know the Split

| Repo | What it is | On server at |
|------|-----------|--------------|
| `KGSHOPINV/claude-server` | Hub app -- all code, UI, API | `~/hub` |
| `KGSHOPINV/server-kit` | Bootstrap installer + Docker stack | `~/server-kit` |

Hub app code goes in `claude-server`. Docker compose files and install scripts go in `server-kit`. Never cross them.

Third repo (private): `KGSHOPINV/FV-MF-SH-integrations` -- federation contracts between ServerHub, FlareVault, and Metaforge. On server at `~/FV-MF-SH-integrations`.

Update hub independently at any time -- no reinstall needed:
```bash
cd ~/hub && git pull && systemctl --user restart hub
```

---

## Optional Services (managed by ServerHub)

These are installed by server-kit. None are required for hub to function.
Hub monitors and controls all of them from the browser.

**Infrastructure**
| Service | Port | What it does |
|---------|------|-------------|
| Nginx Proxy Manager | 81 | Routes domains to containers |
| Portainer | 9443 | Visual container manager |
| Watchtower | -- | Auto-updates containers |

**Monitoring**
| Service | Port | What it does |
|---------|------|-------------|
| Homepage | 3000 | Dashboard showing all services |
| Uptime Kuma | 3001 | Uptime monitoring + alerts |
| Netdata | 19999 | Real-time CPU/RAM/disk graphs |
| Dozzle | 8090 | Live container log viewer |
| Cockpit | 9090 | Linux admin panel |

**Tools**
| Service | Port | What it does |
|---------|------|-------------|
| Supabase | 8000 | Postgres platform |
| PostgreSQL | 5432 | SQL database |
| Redis | 6379 | Cache / key-value store |
| SurrealDB | 8001 | Multi-model database |
| MinIO | 9000/9001 | Object storage (S3-compatible) |
| n8n | 5678 | Workflow automation |
| Adminer | 8082 | Database browser |
| Mailpit | 8025 | Dev email catcher |
| Wiki.js | 3002 | Knowledge base |
| LanguageTool | 8081 | Grammar checker API |

**AI (keep OFF -- CPU-only, no GPU)**
| Service | Port | What it does |
|---------|------|-------------|
| Ollama | 11434 | AI model engine |
| Open WebUI | 3004 | Chat interface |

---

## What ServerHub Does For These Services

- Shows every container's status in real time (running / stopped / unhealthy)
- Lets you restart, stop, or start any container from the browser
- Alerts via ntfy when a container dies or recovers
- Logs all events to the activity feed
- Exposes container state, port landscape, and server metrics via API
- Pushes that data to FlareVault and Metaforge when federation is active

Hub does not care which services are installed. It reads what Docker has running and works with whatever is there.

---

## Full API Surface

Base URL: `http://YOUR_SERVER_IP:8765`

| Route | Method | What it returns |
|-------|--------|----------------|
| `/api/status` | GET | uptime, RAM, disk, load, containers, power_watts, all volumes |
| `/api/ports` | GET | all bound ports with service, lane, protocol, state, assigned_by |
| `/api/context` | GET | structured server snapshot for Metaforge handoff |
| `/api/receipt` | GET | full point-in-time server snapshot |
| `/api/containers` | GET | all running containers with name, ports, status, health |
| `/api/activity` | GET | event log, filterable |
| `/api/activity` | POST | write an event (any system -- FV, MF, n8n, etc.) |
| `/api/manifest` | GET | full system snapshot download |
| `/api/run` | POST | TOTP-gated command execution |
| `/api/docs` | GET | markdown guides from `guides/` |
| `/api/issues` | GET | issue files from `issues/` |
| `/api/config` | GET/POST | hub config key-value store (SQLite) |
| `/api/vault` | GET/POST | encrypted credential blob |
| `/api/ai` | POST | AI chat (requires API key in hub_config) |

---

## Port Map

| Port | Service | Owner |
|------|---------|-------|
| 8765 | ServerHub | SH |
| 8085 | ntfy (self-hosted) | SH |
| 7777 | flarevault-node | FV |
| 7779 | companion-app | FV |
| 7780 | flarevault-mcp | FV |
| 7781 | node-console | FV |
| 7782-7799 | FV system management | FV |

> Note: hub port 8765 and ntfy 8085 are the actual deployed ports.
> The 7xxx block is reserved for federation services only.

---

## File Structure

```
claude-server/              <- hub app repo, cloned to ~/hub on server
  hub/
    server.py               <- entire backend, all routes, stdlib only
    app.html                <- desktop UI
    mobile.html             <- mobile UI
    maintenance.py          <- nightly maintenance agent

  db/server.db              <- SQLite, gitignored
  notes/secrets.env         <- credentials, gitignored, never committed

  guides/                   <- markdown docs served at /api/docs
  issues/                   <- per-service issues served at /api/issues

  SYSTEM.md                 <- this file
  REPOS.md                  <- two-repo split explained
  TASKS.md                  <- roadmap / task docket
  CLAUDE.md                 <- gitignored -- local IPs, SSH, Claude session rules
```

```
server-kit/                 <- bootstrap repo, cloned to ~/server-kit on server
  install.sh                <- one-command full server setup
  01-system-setup.sh ...    <- numbered setup scripts run by install.sh
  docker-compose/           <- compose files for every optional service
  tools/                    <- CLI tools installed to /usr/local/bin/
  integrations/
    flarevault/             <- SPEC, STATUS, INTERFACE (SH->FV build state)
    metaforge/              <- SPEC, STATUS, INTERFACE (SH->MF build state)
```

---

## CLI Tools (`/usr/local/bin/` -- installed by server-kit)

| Command | What it does |
|---------|-------------|
| `server-menu` | Interactive menu for everything |
| `health-check` | Full service + port status report |
| `server-backup` | Run backup now |
| `server-update` | Update all containers + system |
| `dkps` | Docker ps -- running containers |
| `dklogs [name]` | Docker logs for a container |
| `dkrestart [name]` | Restart a container |
| `dkstop / dkstart [name]` | Stop / start a container |

---

## Systemd Units

| Unit | What it does |
|------|-------------|
| `hub.service` | Runs server.py on port 7000, auto-restarts |
| `hub-alert.timer` | Every 15 min -- state-change ntfy alerts |
| `hub-daily.timer` | 7am -- morning brief via ntfy |

```bash
systemctl --user status hub
systemctl --user restart hub
journalctl --user -u hub -f
```

Docker services live under `/srv/docker/SERVICE/` -- `docker compose up -d` to start any of them.

---

## Federation DAG

ServerHub, FlareVault, and Metaforge are three sovereign systems. Each has a doctrine. They communicate only through agreed API endpoints.

```
Boot order:  SH -> FV -> MF    (SH is always first -- it installs before anything else)

          +-----------------------------------------------+
          |               ServerHub (SH)                  |
          |  - installs first on any server               |
          |  - control plane over Docker                  |
          |  - exposes port landscape, capacity, events   |
          |  - NEVER modifies MF containers               |
          |  - defers all credentials to FV               |
          +------------------+----------------+-----------+
                             |                |
                             |                |
          +------------------v--+    +--------v-----------+
          |   FlareVault (FV)   |    |   Metaforge (MF)   |
          |  - credentials      |<-->|  - entity ledger   |
          |  - Cloudflare layer |    |  - fuse colors     |
          |  - deploys services |    |  - tenant registry |
          +---------------------+    +--------------------+
```

**SH -> FV:** port landscape before any deploy, capacity check, container health events, external watch on FV node (FV cannot see itself go down from inside Docker).

**SH -> MF:** `/api/context` primary handoff, container feed, activity log, port landscape for drift detection.

---

## Federation Build State (SH side -- what is live vs what is next)

| Feature | Status | Blocked on |
|---------|--------|-----------|
| `GET /api/context` | LIVE | -- |
| `GET /api/status` | LIVE | -- |
| `GET /api/receipt` | LIVE | -- |
| `GET /api/containers` | LIVE | -- |
| `GET /api/activity` (read + write) | LIVE | -- |
| `GET /api/ports` | LIVE | -- |
| Push container events to FV | NOT BUILT | FV callback URL |
| Push container events to MF | NOT BUILT | MF callback URL |
| Server registration handshake | NOT BUILT | MF |
| Drift detection | NOT BUILT | MF expected manifest |

---

## New Session Quickstart

1. Read this file
2. Read `TASKS.md` for what is next
3. SSH in: `ssh YOUR_USER@YOUR_SERVER_IP`
4. Check hub: `curl -s http://localhost:8765/api/status | python3 -m json.tool`
5. Check containers: `dkps`

Done. You are oriented.

---

## Troubleshooting

```bash
# Hub won't start
journalctl --user -u hub -n 50 --no-pager

# Container down
dklogs CONTAINER_NAME

# Full health dump
health-check

# After power outage -- find anything not running
docker ps --format "table {{.Names}}\t{{.Status}}" | grep -v " Up "
```

**ntfy note:** self-hosted ntfy at `:7001`. Phone only receives alerts if on Tailscale or exposed via Cloudflare Tunnel. Fix is pending.

**AI stack:** keep OFF unless actively using. No GPU -- full CPU load if models run.
