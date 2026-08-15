# Claude Server — Workspace Session Config
> Copy this file to `CLAUDE.md` and fill in your actual values.
> `CLAUDE.md` is gitignored — your real IPs and SSH details stay local only.

---

## Connection

| Key | Value |
|-----|-------|
| Server IP (local) | `<SERVER_LOCAL_IP>` e.g. 192.168.1.x |
| Server IP (Tailscale) | `<SERVER_TAILSCALE_IP>` e.g. 100.x.x.x |
| SSH User | `<SSH_USER>` |
| SSH Command (local) | `ssh <SSH_USER>@<SERVER_LOCAL_IP>` |
| SSH Command (remote) | `ssh <SSH_USER>@<SERVER_TAILSCALE_IP>` |
| Tailscale name | `<TAILSCALE_HOSTNAME>` |
| OS | Ubuntu 24.04 LTS |
| RAM | `<RAM>` |
| GPU | None (CPU only) |
| Storage | `<STORAGE>` |

## How to Run Server Commands

Use Bash tool with SSH:
```bash
ssh <SSH_USER>@<SERVER_LOCAL_IP> "COMMAND_HERE"
```

For multi-command or interactive:
```bash
ssh <SSH_USER>@<SERVER_LOCAL_IP> "command1 && command2"
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
| Hub | http://<SERVER_LOCAL_IP>:8765 |
| Homepage | http://<SERVER_LOCAL_IP>:3000 |
| NPM Admin | http://<SERVER_LOCAL_IP>:81 |
| Portainer | https://<SERVER_LOCAL_IP>:9443 |
| Uptime Kuma | http://<SERVER_LOCAL_IP>:3001 |
| Netdata | http://<SERVER_LOCAL_IP>:19999 |
| Dozzle | http://<SERVER_LOCAL_IP>:8090 |
| Cockpit | https://<SERVER_LOCAL_IP>:9090 |

---

## GitHub Repo

Server kit source: https://github.com/<YOUR_GITHUB_ORG>/server-kit
Docs site: https://<YOUR_DOCS_SITE>
Control panel: https://<YOUR_DOCS_SITE>/panel/

---

## Known Issues

See `issues/` folder for tracked problems.

## Reference

See `reference/` folder for guides and learning material.

---

## Session Rules

- SSH commands run on the server — always prefix with `ssh <SSH_USER>@<SERVER_LOCAL_IP> "..."`
- Reads of server files: `ssh <SSH_USER>@<SERVER_LOCAL_IP> "cat /path/to/file"`
- LOCAL file edits (in this folder) = no SSH needed
- Always confirm before restarting or stopping services
- AI stack should stay OFF unless user asks for it
