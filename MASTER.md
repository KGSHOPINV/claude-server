# MASTER — Complete System Reference

> This is the single source of truth for the entire server ecosystem.
> Every Claude session, every install, every planning conversation starts here.
> When anything changes — update this file first.

---

## 1. Servers in the Ecosystem

| Name | Role | LAN IP | Tailscale IP | SSH User | OS |
|------|------|--------|--------------|----------|----|
| fks-services | Main / HQ | 192.168.1.229 | 100.75.1.105 | admin1 | Ubuntu 24.04 |
| ksgcohub | Node 2 | 192.168.50.100 | 100.107.234.9 | ksgco | Ubuntu 24.04 |

**Hub on every server:** `~/hub/` — Python HTTP server, port **8765**, systemd user service.  
**Source:** https://github.com/KGSHOPINV/claude-server  
**Bootstrap:** https://github.com/KGSHOPINV/server-kit

---

## 2. Port Lanes — The Law

Ports are assigned by lane. Pick the next free port in the correct lane. Never use random ports.

| Lane | Range | Category |
|------|-------|----------|
| System | 80, 443 | Public HTTP/HTTPS — handled by NPM only |
| Hub | **8765** | Server Hub — reserved, never assign to a container |
| Infrastructure | 3000–3099 | Dashboards, admin UIs, core tooling |
| Monitoring | 19000–19999 | Metrics, graphs, health |
| Automation | 5600–5699 | Workflow engines, schedulers |
| Database | 5400–5499, 6300–6399 | SQL, NoSQL, key-value |
| API / Tools | 8000–8099 | Admin UIs, API tooling |
| Notifications | 8080–8089 | Push alerts, webhooks |
| Storage | 9000–9099 | Object storage, file services |
| Admin | 9400–9499 | Container managers, Linux admin |
| AI | 11000–11999 | Model engines, chat UIs |

### Full Port Registry

| Port | Service | Lane | Server |
|------|---------|------|--------|
| 80 | NPM — HTTP ingress | System | all |
| 81 | NPM Admin UI | System | all |
| 443 | NPM — HTTPS ingress | System | all |
| **8765** | **Server Hub** | **Hub** | **all** |
| 3000 | Homepage Dashboard | Infrastructure | all |
| 3001 | Uptime Kuma | Infrastructure | all |
| 3002 | Wiki.js | Infrastructure | optional |
| 3004 | Open WebUI (AI chat) | Infrastructure | AI servers |
| 3005 | OpenClaw | Infrastructure | AI servers |
| 19999 | Netdata | Monitoring | all |
| 9090 | Cockpit (HTTPS) | Admin | optional |
| 5678 | n8n | Automation | all |
| 5432 | PostgreSQL | Database | optional |
| 6379 | Redis | Database | all |
| 8001 | SurrealDB | Database | all |
| 8025 | Mailpit UI | API/Tools | dev servers |
| 8082 | Adminer | API/Tools | optional |
| 8085 | ntfy | Notifications | all |
| 8090 | Dozzle | API/Tools | all |
| 9000 | MinIO API | Storage | optional |
| 9001 | MinIO Console | Storage | optional |
| 9443 | Portainer (HTTPS) | Admin | all |
| 11434 | Ollama | AI | GPU servers only |

**Rules:**
- 8765 is Hub. Always. Never a container.
- ntfy is 8085. Always.
- If you add a new service, check this list first, pick the next free port in the lane, add it here.

---

## 3. Naming Convention — The Law

```
/srv/docker/
  SERVICE/              ← shared infrastructure
  PROJECTNAME-SERVICE/  ← project-specific (isolated)
```

**Folder name = container_name = stack name.** No exceptions, no Docker-generated names.

| Pattern | Example | Use case |
|---------|---------|----------|
| `redis` | `/srv/docker/redis/` → container `redis` | Shared utility |
| `keyknox-redis` | `/srv/docker/keyknox-redis/` → container `keyknox-redis` | Project-isolated |
| `metaforge-db` | `/srv/docker/metaforge-db/` → container `metaforge-db` | MetaForge's DB |
| `flarevault-api` | `/srv/docker/flarevault-api/` → container `flarevault-api` | FV service |

**Why:** Hub's dynamic discovery reads `docker ps` by name. CLI tools (`dklogs`, `dkrestart`) use the name. Portainer shows it as a named stack. Everything is findable without documentation.

---

## 4. Ecosystem Map

```
┌─────────────────────────────────────────────────────────┐
│                    SERVER HUB (8765)                    │
│         Native Python — runs on every server            │
│  /api/status  /api/containers  /api/ports  /api/storage │
│  /api/identity  /api/peer/register  /api/federation     │
└──────────┬──────────────────────────┬───────────────────┘
           │                          │
    pushes health/ports        pushes container
    events + port landscape    feed + activity
           │                          │
    ┌──────▼──────┐           ┌───────▼──────┐
    │  FlareVault  │           │  MetaForge   │
    │  (FV)        │           │  (MF)        │
    │  Cloudflare  │           │  Project     │
    │  management  │           │  orchestrator│
    └─────────────┘           └──────────────┘
           │                          │
           └──────────┬───────────────┘
                      │
              ┌───────▼────────┐
              │  Peer Mesh     │
              │  /api/identity │
              │  /api/peer/    │
              │  register      │
              └────────────────┘
```

### What Hub feeds FV:
- Port landscape (all bound ports + federation fields)
- Health events via ntfy

### What Hub feeds MF:
- `/api/context` — server snapshot
- Container feed (all running containers with names)
- Activity log

### Peer mesh:
- Every hub exposes `/api/identity` → hostname, hub_url, local_ip, tailscale_ip
- `POST /api/peer/register {hub_url, echo:true}` → bidirectional handshake, both hubs register each other
- Peers visible in federation panel

---

## 5. What's on Each Server

### fks-services (192.168.1.229) — Main Server
| Service | Port | Status |
|---------|------|--------|
| Server Hub | 8765 | ✅ |
| NPM | 80/81/443 | ✅ |
| Homepage | 3000 | ✅ |
| Uptime Kuma | 3001 | ✅ |
| Netdata | 19999 | ✅ |
| Dozzle | 8090 | ✅ |
| Portainer | 9443 | ✅ |
| ntfy | 8085 | ✅ |
| n8n | 5678 | ✅ |
| Redis | 6379 | ✅ |
| SurrealDB | 8001 | ✅ |
| Supabase | 8000 | ✅ |
| MinIO | 9000/9001 | ✅ |
| Adminer | 8082 | ✅ |
| Mailpit | 8025 | ✅ |
| Wiki.js | 3002 | ✅ |

### ksgcohub (192.168.50.100) — Node 2
| Service | Port | Status |
|---------|------|--------|
| Server Hub | 8765 | ✅ |
| NPM | 80/81/443 | ✅ |
| Homepage | 3000 | ✅ |
| Uptime Kuma | 3001 | ✅ |
| Netdata | 19999 | ✅ |
| Portainer | 9443 | ✅ |
| Nextcloud (snap) | 8181 | ✅ (moved from 80) |
| ntfy | 8085 | ⬜ pending |
| n8n | 5678 | ⬜ pending |
| Redis | 6379 | ⬜ pending |
| SurrealDB | 8001 | ⬜ pending |
| Dozzle | 8090 | ⬜ pending |
| /srv/data (sdb) | 458G | ✅ mounted |

---

## 6. Install Order — Why This Order

1. **System** — apt updates, UFW, Fail2Ban, timezone, static IP
2. **Docker** — everything else depends on this
3. **Hub** — clone `~/hub`, systemd user service, port 8765. Runs immediately so you have a dashboard while the rest installs.
4. **NPM** — creates the `proxy` Docker network. Must run before any other Docker service.
5. **Portainer** — Docker GUI
6. **Monitoring** — Homepage, Uptime Kuma, Netdata, Dozzle
7. **Backup** — set up before adding data
8. **Security** — Fail2Ban rules, SSH hardening
9. **CLI Tools** — helper scripts at `/usr/local/bin/`
10. **Extras** — n8n, Redis, SurrealDB, MinIO, etc. (user selects)
11. **Peer registration** — asks for existing hub URL, bidirectional handshake

**Critical:** NPM must start before any service that joins the `proxy` network.  
**Critical:** Hub installs right after Docker so you have visibility from minute 3 onward.

---

## 7. Adding a New Service — The Workflow

```bash
new-service add CATEGORY NAME [project-prefix]
```

Examples:
```bash
new-service add database surrealdb           # → /srv/docker/surrealdb/ port 8001
new-service add database redis keyknox       # → /srv/docker/keyknox-redis/ port 6380
new-service add automation n8n               # → /srv/docker/n8n/ port 5678
```

What it does automatically:
1. Identifies the lane from the category
2. Finds next free port in that lane
3. Creates `/srv/docker/NAME/docker-compose.yml` from template
4. Sets `container_name: NAME` in compose
5. Adds UFW rule for the port
6. Runs `docker compose up -d`
7. Hub discovers it on next refresh (dynamic — reads `docker ps`)
8. Logs to activity feed

---

## 8. Mesh — What Servers Know About Each Other

Each hub exposes:
- `GET /api/identity` — hostname, hub_url, LAN IP, Tailscale IP, server name
- `GET /api/status` — RAM, disk, uptime, load
- `GET /api/containers` — all running containers
- `GET /api/ports` — all bound ports
- `POST /api/peer/register` — bidirectional registration

**Current peers:**
- fks-services hub: `http://100.75.1.105:8765`
- ksgcohub hub: `http://100.107.234.9:8765`

**What the mesh is for:**
- Cross-server health monitoring (peer goes offline → ntfy alert)
- See what's running on another server from your hub
- One-command pairing at install time
- Foundation for: remote deploy, shared activity feed, HQ/node architecture

**What it is NOT yet:**
- Automatic failover
- Shared config sync
- Central deploy target (planned — HQ/node pairing)

---

## 9. Access Flavors

| Flavor | How | Use case |
|--------|-----|----------|
| LAN direct | `http://192.168.x.x:PORT` | At home, fastest |
| Tailscale | `http://100.x.x.x:PORT` | Remote, any device, encrypted |
| Cloudflare Tunnel | `https://hub.yourdomain.com` | Public URL, no port forwarding |
| CF + Access | Email OTP gate on CF URL | Secure public access |
| CF SSH proxy | `ssh user@ssh.yourdomain.com` | SSH over HTTPS, mobile-friendly |
| Two Tailscale accounts | Device on both accounts | Two separate orgs, one machine |
| Tailscale mesh | Multiple servers, one tailnet | All servers see each other |

---

## 10. Hub API Surface

| Endpoint | Method | What |
|----------|--------|------|
| `/api/status` | GET | RAM, disk, uptime, load, containers |
| `/api/storage` | GET | All mounts, disk tree, docker volumes |
| `/api/containers` | GET | All Docker containers, state, ports |
| `/api/ports` | GET | All bound ports + federation fields |
| `/api/activity` | GET | Event log |
| `/api/receipt` | GET | Full server snapshot |
| `/api/identity` | GET | Hostname, hub_url, IPs — peer beacon |
| `/api/federation` | GET/POST | FV/MF/peer config |
| `/api/peer/register` | POST | Bidirectional peer handshake |
| `/api/vault` | GET/POST | Encrypted notes (TOTP gated) |
| `/api/run` | POST | Shell command execution (TOTP gated) |
| `/api/ai/chat` | POST | AI chat with server context |
| `/api/journal` | POST | Manual activity log entry |
| `/api/sitemap` | GET | All available endpoints (**planned**) |

---

## 11. Planned Builds — In Order

| Priority | What | Why now |
|----------|------|---------|
| 1 | Deploy missing services on ksgcohub | Node 2 not fully running |
| 2 | Route registry + `/api/sitemap` | Unlocks MCP server |
| 3 | MCP server | Claude tool access to hub |
| 4 | HQ/node pairing UI | Multi-server management |
| 5 | Cloudflare Tunnel + Access | Public access without VPN |
| 6 | TOTP gate | Security layer |
| 7 | Service tokens | AI vs human identity |
| 8 | ntfy bidirectional | Phone → server commands |
| 9 | Agentic loop | AI with tool execution |

---

## 12. CLI Tools (at /usr/local/bin/)

| Command | What |
|---------|------|
| `server-menu` | Interactive menu for everything |
| `health-check` | Full service + port status |
| `server-backup` | Run backup now |
| `server-update` | Update all containers + apt |
| `dkps` | Docker ps (running containers) |
| `dklogs [name]` | Docker logs for container |
| `dkrestart [name]` | Restart a container |
| `dkstop [name]` | Stop a container |
| `dkstart [name]` | Start a container |
| `deploy-project` | Deploy a project stack |
| `network-check` | Check connectivity |
| `new-service` | Add a new service (**planned**) |
| `port-scan` | Show all open ports |

---

## 13. Key Decisions (Why We Did It This Way)

| Decision | Reason |
|----------|--------|
| Hub on 8765, not a container | Hub must survive Docker being down |
| Hub as user systemd service | Runs without root, auto-restarts |
| All services under /srv/docker/ | One place, consistent, backupable |
| Folder = container name | Makes CLI tools, Portainer, hub discovery all work with one name |
| Proxy network created by NPM | NPM must start first — it owns the network |
| ntfy on 8085 | Notifications lane, below 8090 (Dozzle) |
| Static IP at install | Server must always be at the same address |
| Tailscale SSH (--ssh flag) | Bypasses UFW, works with Tailscale identity |
| Dynamic container discovery | Hub reads docker ps — shows Nextcloud, anything else added manually |
| Bidirectional peer handshake | One POST registers both sides — no manual config on each server |

---

## 14. Repos

| Repo | URL | What |
|------|-----|------|
| claude-server | https://github.com/KGSHOPINV/claude-server | Hub app, API, dashboard |
| server-kit | https://github.com/KGSHOPINV/server-kit | Bootstrap installer, compose files |

**Rule:** Every code change commits and pushes immediately. No batching.

---

## 15. Never Do

- Never commit passwords, IPs, or secrets to GitHub
- Never run AI stack (Ollama/OpenWebUI) without a GPU
- Never restart/stop services without confirming
- Never assign port 8765 to a container
- Never use random container names — folder = name = law
- Never skip the port registry when adding a service
