# Port Reference & Lane Definitions

> Central port registry for the full server stack.
> All service ports are assigned to lanes — category-scoped ranges that prevent conflicts.
> When adding a new service, pick the next free port in its lane.

---

## Lanes

| Lane | Range | Category |
|------|-------|----------|
| **System** | 80, 443 | Public HTTP/HTTPS (Nginx Proxy Manager) |
| **Hub** | 8765 | Server Hub control panel |
| **Infrastructure** | 3000–3099 | Dashboards, admin UIs |
| **Monitoring** | 19000–19999 | Metrics, graphs, health |
| **Automation** | 5600–5699 | Workflow engines |
| **Database** | 5400–5499, 6300–6399 | SQL, Redis, key-value |
| **API/Services** | 8000–8099 | Admin tools, API UIs |
| **Notifications** | 8080–8089 | Push, alerts, webhooks |
| **Storage** | 9000–9099 | Object storage, file services |
| **Admin/Management** | 9400–9499 | Container managers, Linux admin |
| **AI** | 11000–11999 | Model engines, chat UIs |
| **Proxy/Tunnel** | 8200–8299 | Reverse proxy management |

---

## Current Port Assignments

### System
| Port | Service | Container | Lane |
|------|---------|-----------|------|
| 80 | HTTP → NPM | npm | System |
| 81 | NPM Admin UI | npm | System |
| 443 | HTTPS → NPM | npm | System |

### Hub
| Port | Service | Container | Lane |
|------|---------|-----------|------|
| 8765 | Server Hub | hub (systemd) | Hub |

### Infrastructure
| Port | Service | Container | Lane |
|------|---------|-----------|------|
| 3000 | Homepage Dashboard | homepage | Infrastructure |
| 3001 | Uptime Kuma | uptime-kuma | Infrastructure |
| 3002 | Wiki.js | wikijs | Infrastructure |
| 3004 | Open WebUI (AI chat) | openwebui | Infrastructure |
| 3005 | OpenClaw | openclaw | Infrastructure |

### Monitoring
| Port | Service | Container | Lane |
|------|---------|-----------|------|
| 19999 | Netdata | netdata | Monitoring |
| 9090 | Cockpit (HTTPS) | cockpit | Monitoring |

### Automation
| Port | Service | Container | Lane |
|------|---------|-----------|------|
| 5678 | n8n | n8n | Automation |

### Database
| Port | Service | Container | Lane |
|------|---------|-----------|------|
| 5432 | PostgreSQL (Supabase) | mf-supabase-db | Database |
| 5450 | PostgreSQL (external) | mf-supabase-db | Database |
| 6379 | Redis | redis | Database |
| 8001 | SurrealDB | surrealdb | Database |

### API / Admin Tools
| Port | Service | Container | Lane |
|------|---------|-----------|------|
| 8025 | Mailpit UI | mailpit | API/Services |
| 1025 | Mailpit SMTP | mailpit | API/Services |
| 8082 | Adminer (DB UI) | adminer | API/Services |
| 8090 | Dozzle (log viewer) | dozzle | API/Services |

### Notifications
| Port | Service | Container | Lane |
|------|---------|-----------|------|
| 8085 | ntfy | ntfy | Notifications |

### Storage
| Port | Service | Container | Lane |
|------|---------|-----------|------|
| 9000 | MinIO API | minio | Storage |
| 9001 | MinIO Console | minio | Storage |

### Admin / Management
| Port | Service | Container | Lane |
|------|---------|-----------|------|
| 9443 | Portainer (HTTPS) | portainer | Admin/Management |

### AI
| Port | Service | Container | Lane |
|------|---------|-----------|------|
| 11434 | Ollama | ollama | AI |

### Supabase Stack (Metaforge)
| Port | Service | Container | Lane |
|------|---------|-----------|------|
| 8210 | Supabase Kong API | mf-supabase-kong | API/Services |
| 8211 | Supabase Kong HTTPS | mf-supabase-kong | API/Services |
| 3110 | Supabase Studio UI | mf-supabase-studio | Infrastructure |

---

## Rules

1. **Pick the next free port in the lane** — don't use random ports
2. **Document here first** — before adding a service, add its port here
3. **NPM routes public traffic** — LAN services stay on their lane port, NPM handles public domain routing
4. **No two services on the same port** — `port-scan` CLI tool checks for conflicts
5. **8765 is reserved for Hub** — never assign to a container

---

## Adding a New Service

1. Identify the lane (what category is this service?)
2. Find the next free port in that lane range
3. Add to this file under the correct section
4. Update the docker-compose file to use that port
5. Run `port-scan` on the server to verify no conflicts

---

## Port Scan

```bash
port-scan          # shows all open ports on the server
port-scan 3000     # check if a specific port is free
```
