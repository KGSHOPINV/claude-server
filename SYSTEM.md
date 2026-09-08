# ServerHub -- System Map

> Read this first. Everything you need to reason about this project is here.

---

## What ServerHub Is

A self-hosted server control panel. One Python file (`hub/server.py`) runs as a systemd service on a Linux server. It exposes a JSON API and a browser UI that gives you full visibility and control over Docker containers, disk, RAM, CPU, ports, logs, credentials, and AI -- all from any browser on your network.

**No external dependencies.** Python stdlib only. No npm, no frameworks, no build step.

**Port:** `:7000` (was previously `:8765` -- some old docs may say that)

---

## Two Repos -- Know the Split

| Repo | What it is | Lives on server at |
|------|-----------|-------------------|
| `KGSHOPINV/claude-server` | **The hub app** -- all code, UI, API, docs | `~/hub` |
| `KGSHOPINV/server-kit` | **Bootstrap installer** -- gets a blank Ubuntu server ready | `~/server-kit` |

**Rule:** Hub app code goes in `claude-server`. Docker compose files, install scripts, CLI tools go in `server-kit`. Never cross them.

**Third repo** (private): `KGSHOPINV/FV-MF-SH-integrations` -- federation meeting room for Metaforge/FlareVault/ServerHub contracts. On server at `~/FV-MF-SH-integrations`.

---

## Installing on a Fresh Server

```bash
git clone https://github.com/KGSHOPINV/server-kit
cd server-kit
bash install.sh
```

`install.sh` asks 4 questions (IP, SSH user, timezone, admin password), then:
- Runs numbered setup scripts `01-system-setup.sh` through `16-ai-setup.sh`
- Deploys all Docker services under `/srv/docker/`
- Clones `claude-server` into `~/hub`
- Writes and starts `hub.service` (systemd user service)
- Hub is live at `http://SERVER_IP:7000`

**After install, update hub independently (no full reinstall needed):**
```bash
cd ~/hub && git pull && systemctl --user restart hub
```

---

## SSH Access

```bash
ssh YOUR_USER@YOUR_SERVER_IP        # local network
ssh YOUR_USER@YOUR_TAILSCALE_IP     # Tailscale (remote)
```

Server spec (this instance): Ubuntu 24.04 LTS | 216GB RAM | 1TB OS + 4TB data (`/backup`) | No GPU

---

## Full API Surface

All routes served by `hub/server.py`. Base URL: `http://YOUR_SERVER_IP:7000`

| Route | Method | What it returns |
|-------|--------|----------------|
| `/api/status` | GET | uptime, RAM, disk, load, containers, power_watts, all mounted volumes, unattached drives |
| `/api/ports` | GET | all bound ports with service, lane, protocol, state, assigned_by (FV-BI-SH schema) |
| `/api/context` | GET | MF handoff payload -- hostname, OS, CPU, RAM, disk, docker_version, running_containers, network_interfaces |
| `/api/receipt` | GET | full point-in-time server snapshot |
| `/api/containers` | GET | all running containers with name, image, ports, status, health |
| `/api/activity` | GET | event log, filterable by source/type/time |
| `/api/activity` | POST | any system writes an event (FV, MF, n8n, etc.) |
| `/api/manifest` | GET | full system snapshot as downloadable JSON |
| `/api/run` | POST | TOTP-gated command execution |
| `/api/docs` | GET | markdown guides from `guides/` |
| `/api/issues` | GET | issue files from `issues/` |
| `/api/config` | GET/POST | hub_config key-value store (SQLite) |
| `/api/vault` | GET/POST | encrypted credential blob |
| `/api/ai` | POST | AI chat (requires API key in hub_config) |

---

## Port Map (7xxx space)

| Port | Service | Owner |
|------|---------|-------|
| 7000 | ServerHub | SH |
| 7001 | ntfy (self-hosted) | SH |
| 7002 | n8n | SH |
| 7003 | Redis (planned) | SH |
| 7777 | flarevault-node | FV |
| 7779 | companion-app | FV |
| 7780 | flarevault-mcp | FV |
| 7781 | node-console | FV |
| 7782-7799 | FV system management | FV |

**Other services (non-7xxx):**

| Port | Service |
|------|---------|
| 81 | Nginx Proxy Manager |
| 3000 | Homepage dashboard |
| 3001 | Uptime Kuma |
| 3002 | Wiki.js |
| 5678 | n8n |
| 8025 | Mailpit |
| 8082 | Adminer |
| 8090 | Dozzle |
| 9090 | Cockpit |
| 9443 | Portainer |
| 19999 | Netdata |

---

## File Structure

```
claude-server/              <- this repo, cloned to ~/hub on server
  hub/
    server.py               <- entire backend -- stdlib Python, all API routes
    app.html                <- desktop UI -- multi-pane, tabs, vault, TOTP
    mobile.html             <- mobile UI -- swipe tabs
    maintenance.py          <- nightly maintenance agent

  db/
    server.db               <- SQLite (gitignored) -- hub_config, journal, vault

  notes/
    secrets.env             <- credentials (gitignored -- never committed)

  guides/                   <- markdown guides served via /api/docs
  issues/                   <- per-service issue files served via /api/issues

  SYSTEM.md                 <- this file
  REPOS.md                  <- two-repo architecture detail
  TASKS.md                  <- live task docket / roadmap
  CLAUDE.md                 <- gitignored -- local IPs, SSH, session rules for Claude
```

```
server-kit/                 <- bootstrap repo, cloned to ~/server-kit on server
  install.sh                <- one-command server bootstrap
  01-system-setup.sh ...    <- numbered setup scripts
  docker-compose/           <- compose files for every service
  tools/                    <- CLI tools deployed to /usr/local/bin/
  integrations/
    flarevault/             <- SPEC.md, STATUS.md, INTERFACE.md (SH->FV build state)
    metaforge/              <- SPEC.md, STATUS.md, INTERFACE.md (SH->MF build state)
  mcp/                      <- Claude MCP config for server awareness
```

---

## CLI Tools on Server (`/usr/local/bin/`)

| Command | What it does |
|---------|-------------|
| `server-menu` | Interactive menu for everything |
| `health-check` | Full service + port status report |
| `server-backup` | Run backup now |
| `server-update` | Update all containers + system |
| `dkps` | Docker ps -- running containers |
| `dklogs [name]` | Docker logs for a container |
| `dkrestart [name]` | Restart a container |
| `dkstop [name]` | Stop a container |
| `dkstart [name]` | Start a container |

---

## Systemd Services (user-level, runs as the SSH user)

| Unit | What it does |
|------|-------------|
| `hub.service` | Runs `server.py` on port 7000, auto-restarts |
| `hub-alert.timer` | Every 15 min -- state-change alerts via ntfy |
| `hub-daily.timer` | 7am -- morning brief via ntfy |

```bash
systemctl --user status hub
systemctl --user restart hub
journalctl --user -u hub -f
```

---

## Docker Compose Locations

All services under `/srv/docker/`:

```bash
cd /srv/docker/SERVICE && docker compose up -d    # start
cd /srv/docker/SERVICE && docker compose down      # stop
cd /srv/docker/SERVICE && docker compose logs -f   # watch
```

Services: `npm`, `portainer`, `watchtower`, `homepage`, `uptime-kuma`, `netdata`,
`dozzle`, `cockpit`, `supabase`, `surrealdb`, `redis`, `minio`, `n8n`, `adminer`,
`mailpit`, `wikijs`, `languagetool`, `ai` (Ollama + Open WebUI -- keep OFF, no GPU)

---

## Federation DAG

Three systems. Each sovereign. Communication through agreed endpoints only.

```
Boot order (enforced):  SH -> FV -> MF

              +------------------------------------------+
              |            ServerHub (SH)                |
              |  - boots first -- installed on bare server|
              |  - watches Docker, reports what runs     |
              |  - never modifies MF containers          |
              |  - defers credentials to FV              |
              +-------------+----------------+-----------+
                            |                |
         SH -> FV           |                |   SH -> MF
         port landscape     |                |   container feed
         capacity check     |                |   server registration
         container events   |                |   drift detection
                            |                |
         +------------------v--+    +--------v-----------+
         |   FlareVault (FV)   |    |   Metaforge (MF)   |
         |  - credentials      |<-->|  - entity ledger   |
         |  - Cloudflare proto |    |  - fuse colors     |
         |  - USB root trust   |    |  - tenant registry |
         |  - deploys services |    |  - toroidal clock  |
         +---------------------+    +--------------------+
```

**What SH gives FV:** port landscape before deploy, capacity, container health events, runtime confirmation after deploy, external watcher for FV node (FV can't see itself go down from inside Docker).

**What SH gives MF:** `/api/context` (primary handoff), container feed, activity log, port landscape for drift detection.

**Hard boundary:** SH monitors MF containers. SH NEVER restarts, reconfigures, or modifies them.

---

## Federation Build State (SH side)

| Endpoint / Feature | Status | Needed by |
|-------------------|--------|-----------|
| `GET /api/context` | LIVE | MF |
| `GET /api/status` | LIVE | FV + MF |
| `GET /api/receipt` | LIVE | FV + MF |
| `GET /api/containers` | LIVE | MF |
| `GET /api/activity` (read + write) | LIVE | FV + MF |
| `GET /api/ports` | LIVE | FV + MF |
| Push container events to FV | NOT BUILT | FV callback URL needed |
| Push container events to MF | NOT BUILT | MF callback URL needed |
| Server registration handshake | NOT BUILT | MF |
| Drift detection | NOT BUILT | MF expected manifest needed |

---

## Known Issues / Watch Items

- **ntfy notifications** -- self-hosted ntfy at `:7001`. Phone can't receive unless on Tailscale or via Cloudflare Tunnel. Fix pending: expose via Cloudflare Tunnel.
- **AI stack** -- Ollama + Open WebUI installed but kept OFF. No GPU -- runs at 100% CPU if enabled.
- **Power draw** -- ACPI power meter read from `/sys/class/hwmon/*/power1_average` (scans for `power_meter` chip). Hub displays live in header as power_watts. Idles around 180W on this instance.
- **UPS** -- no UPS on this server. Power outage = hard cut. All services have `restart: always` and auto-recover on boot. `/backup` auto-mounts via fstab with `nofail`.

---

## If You Are Starting a New Session

1. Read this file -- you now know the full picture
2. Read `TASKS.md` -- you know what is next
3. Read `server-kit/integrations/flarevault/STATUS.md` + `metaforge/STATUS.md` -- you know federation state
4. SSH in and check hub is up:
   ```bash
   curl -s http://localhost:7000/api/status | python3 -m json.tool
   ```
5. Check containers: `dkps`

You are oriented. Start working.

---

## Troubleshooting

```bash
# Hub won't start
journalctl --user -u hub -n 50 --no-pager

# Container down
dklogs CONTAINER_NAME

# Full health dump
health-check

# Disk check
df -h && lsblk

# After power outage (all containers should auto-start via restart:always)
docker ps --format "table {{.Names}}\t{{.Status}}" | grep -v Up
# ^ shows anything NOT running
```
