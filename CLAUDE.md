# Claude Server — Work PC Session
> This workspace connects directly to the home server via SSH.
> Claude can run commands on the server from this machine.

---

## Connection

| Key | Value |
|-----|-------|
| Server IP (local) | 192.168.1.229 |
| Server IP (Tailscale) | 100.75.1.105 |
| SSH User | admin1 |
| SSH Command (local) | `ssh admin1@192.168.1.229` |
| SSH Command (remote) | `ssh admin1@100.75.1.105` |
| Tailscale name | fks-services |
| OS | Ubuntu 24.04 LTS |
| RAM | 216 GB |
| GPU | None (CPU only) |
| Storage | 1TB OS + 4TB data |

## How to Run Server Commands

Use Bash tool with SSH:
```bash
ssh admin1@192.168.1.229 "COMMAND_HERE"
```

For multi-command or interactive:
```bash
ssh admin1@192.168.1.229 "command1 && command2"
```

---

## Server Stack — What's Installed

### TIER 1 — Foundation (everything depends on these)
| Service | Port | What it does |
|---------|------|-------------|
| Docker | — | Runs all services as containers |
| Nginx Proxy Manager | 81 | Routes domains to containers |
| Portainer | 9443 (https) | Visual container manager |
| Watchtower | — | Auto-updates containers |

### TIER 2 — Monitoring (eyes and ears)
| Service | Port | What it does |
|---------|------|-------------|
| Homepage | 3000 | Dashboard — shows all services + status |
| Uptime Kuma | 3001 | Uptime monitoring + alerts |
| Netdata | 19999 | Real-time CPU/RAM/disk graphs |
| Dozzle | 8090 | Live container log viewer |
| Cockpit | 9090 (https) | Linux admin panel in browser |

### TIER 3 — Tools (what you build with)
| Service | Port | What it does |
|---------|------|-------------|
| Supabase | 8000 | Database platform (Postgres under hood) |
| PostgreSQL | 5432 | SQL database |
| Redis | 6379 | Cache / fast key-value store |
| SurrealDB | 8001 | Multi-model database |
| MinIO | 9000/9001 | Object storage (like S3) |
| n8n | 5678 | Workflow automation |
| Adminer | 8082 | Database browser |
| Mailpit | 8025 | Dev email catcher |
| Wiki.js | 3002 | Knowledge base |
| LanguageTool | 8081 | Grammar checker API |

### TIER 4 — AI (optional, CPU-heavy without GPU)
| Service | Port | What it does |
|---------|------|-------------|
| Ollama | 11434 | AI model engine |
| Open WebUI | 3004 | Chat interface for AI |
| OpenClaw | 3005 | AI playground |

**AI WARNING**: No GPU installed. Running AI models uses 100% CPU and is very slow. Keep AI stack OFF unless actively using it.

---

## Server CLI Tools

All installed at `/usr/local/bin/`:

| Command | What it does |
|---------|-------------|
| `server-menu` | Interactive menu for everything |
| `health-check` | Full service + port status report |
| `server-backup` | Run backup now |
| `server-update` | Update all containers + system |
| `sec` | Security check |
| `ai-models` | Manage Ollama AI models |
| `dkps` | Docker ps (running containers) |
| `dklogs [name]` | Docker logs for a container |
| `dkrestart [name]` | Restart a container |
| `dkstop [name]` | Stop a container |
| `dkstart [name]` | Start a container |

---

## Docker Compose Locations

All services live under `/srv/docker/`:
```
/srv/docker/
  npm/              # Nginx Proxy Manager
  portainer/        # Portainer
  watchtower/       # Watchtower
  homepage/         # Homepage dashboard
  uptime-kuma/      # Uptime Kuma
  netdata/          # Netdata
  dozzle/           # Dozzle (port 8090)
  cockpit/          # Cockpit
  supabase/         # Supabase
  surrealdb/        # SurrealDB
  redis/            # Redis
  minio/            # MinIO
  n8n/              # n8n
  adminer/          # Adminer
  mailpit/          # Mailpit
  wikijs/           # Wiki.js
  languagetool/     # LanguageTool
  ai/               # Ollama + Open WebUI + OpenClaw
```

To manage a service:
```bash
cd /srv/docker/SERVICE_NAME && docker compose up -d    # start
cd /srv/docker/SERVICE_NAME && docker compose down      # stop
cd /srv/docker/SERVICE_NAME && docker compose logs -f   # watch logs
```

---

## Browser Access (from work PC)

| Service | URL |
|---------|-----|
| Homepage | http://192.168.1.229:3000 |
| NPM Admin | http://192.168.1.229:81 |
| Portainer | https://192.168.1.229:9443 |
| Uptime Kuma | http://192.168.1.229:3001 |
| Netdata | http://192.168.1.229:19999 |
| Dozzle | http://192.168.1.229:8090 |
| Cockpit | https://192.168.1.229:9090 |
| Open WebUI | http://192.168.1.229:3004 |
| OpenClaw | http://192.168.1.229:3005 |

---

## GitHub Repo

Server kit source: https://github.com/KGSHOPINV/server-kit
Docs site: https://server-kit-docs.netlify.app
Control panel: https://server-kit-docs.netlify.app/panel/

---

## Known Issues

See `issues/` folder for tracked problems.

## Reference

See `reference/` folder for guides and learning material.

---

## Session Rules

- SSH commands run on the server — always prefix with `ssh admin1@192.168.1.229 "..."`
- Reads of server files: `ssh admin1@192.168.1.229 "cat /path/to/file"`
- LOCAL file edits (in this folder) = no SSH needed
- Always confirm before restarting or stopping services
- AI stack should stay OFF unless user asks for it
