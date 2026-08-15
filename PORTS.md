# Port Reference & Lane Definitions

> Central port registry for the full server stack.
> Ports are assigned to lanes — category-scoped ranges that prevent conflicts.
> When adding a new service, pick the next free port in its lane and document it here.

---

## Lanes

| Lane | Range | Category |
|------|-------|----------|
| **System** | 80, 443 | Public HTTP/HTTPS (handled by Nginx Proxy Manager) |
| **Hub** | 8765 | Server Hub control panel (reserved — never assign to a container) |
| **Infrastructure** | 3000–3099 | Dashboards, admin UIs, core tooling |
| **Monitoring** | 19000–19999 | Metrics, graphs, health checks |
| **Automation** | 5600–5699 | Workflow engines, job schedulers |
| **Database** | 5400–5499, 6300–6399 | SQL, NoSQL, key-value stores |
| **API/Services** | 8000–8099 | Admin UIs, API tools |
| **Notifications** | 8080–8089 | Push alerts, webhooks, notification servers |
| **Storage** | 9000–9099 | Object storage, file services |
| **Admin/Management** | 9400–9499 | Container managers, Linux admin panels |
| **AI** | 11000–11999 | Model engines, chat UIs |
| **Proxy/Tunnel** | 8200–8299 | Reverse proxy management |

---

## Example Assignments

The table below shows where common self-hosted services belong by lane.
Your actual assignments go in your server's own port registry (or fill this in after deploying).

### System
| Port | Service | Lane |
|------|---------|------|
| 80 | HTTP → Nginx Proxy Manager | System |
| 81 | NPM Admin UI | System |
| 443 | HTTPS → Nginx Proxy Manager | System |

### Hub
| Port | Service | Lane |
|------|---------|------|
| 8765 | Server Hub (systemd) | Hub |

### Infrastructure
| Port | Service | Lane |
|------|---------|------|
| 3000 | Homepage Dashboard | Infrastructure |
| 3001 | Uptime Kuma | Infrastructure |
| 3002 | Wiki.js | Infrastructure |
| 3004 | Open WebUI (AI chat) | Infrastructure |
| 3005 | OpenClaw | Infrastructure |

### Monitoring
| Port | Service | Lane |
|------|---------|------|
| 19999 | Netdata | Monitoring |
| 9090 | Cockpit (HTTPS) | Admin/Management |

### Automation
| Port | Service | Lane |
|------|---------|------|
| 5678 | n8n | Automation |

### Database
| Port | Service | Lane |
|------|---------|------|
| 5432 | PostgreSQL | Database |
| 6379 | Redis | Database |
| 8001 | SurrealDB | Database |

### API / Admin Tools
| Port | Service | Lane |
|------|---------|------|
| 8025 | Mailpit UI | API/Services |
| 8082 | Adminer (DB browser) | API/Services |
| 8090 | Dozzle (log viewer) | API/Services |

### Notifications
| Port | Service | Lane |
|------|---------|------|
| 8085 | ntfy | Notifications |

### Storage
| Port | Service | Lane |
|------|---------|------|
| 9000 | MinIO API | Storage |
| 9001 | MinIO Console | Storage |

### Admin / Management
| Port | Service | Lane |
|------|---------|------|
| 9443 | Portainer (HTTPS) | Admin/Management |

### AI
| Port | Service | Lane |
|------|---------|------|
| 11434 | Ollama | AI |

---

## Rules

1. **Pick the next free port in the lane** — don't use random ports
2. **Document here first** — before adding a service, claim its port here
3. **NPM routes public traffic** — LAN services stay on their lane port; NPM handles public domain routing
4. **No two services on the same port** — run `ss -tlnp` or `port-scan` to check for conflicts
5. **8765 is reserved for Hub** — never assign to a container

---

## Adding a New Service

1. Identify the lane (what category is this service?)
2. Find the next free port in that lane range
3. Add it to this file under the correct section
4. Update the docker-compose file to use that port
5. Verify no conflicts: `ss -tlnp | grep <port>`

---

## Port Scan (server CLI)

```bash
port-scan          # shows all open ports on the server
port-scan 3000     # check if a specific port is free
ss -tlnp           # raw socket view
```
