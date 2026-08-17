# Services Reference

All services are available at `{{server.local_ip}}:<port>` on the local network, or `{{server.tailscale_ip}}:<port>` via Tailscale from anywhere.

## Infrastructure

| Service | Port | URL | Notes |
|---------|------|-----|-------|
| Nginx Proxy Manager | 81 | `http://{{server.local_ip}}:81` | Routes domains to containers |
| Portainer | 9443 | `https://{{server.local_ip}}:9443` | Visual Docker manager |
| Cockpit | 9090 | `https://{{server.local_ip}}:9090` | Linux admin panel |

## Monitoring

| Service | Port | URL | Notes |
|---------|------|-----|-------|
| Homepage | 3000 | `http://{{server.local_ip}}:3000` | Dashboard |
| Uptime Kuma | 3001 | `http://{{server.local_ip}}:3001` | Uptime alerts |
| Netdata | 19999 | `http://{{server.local_ip}}:19999` | Real-time metrics |
| Dozzle | 8090 | `http://{{server.local_ip}}:8090` | Container log viewer |
| ntfy | 8085 | `http://{{server.local_ip}}:8085` | Push notifications |

## Tools

| Service | Port | URL | Status |
|---------|------|-----|--------|
| n8n | 5678 | `http://{{server.local_ip}}:5678` | Workflow automation |
| SurrealDB | 8001 | `http://{{server.local_ip}}:8001` | Multi-model DB |
| Redis | 6379 | — | Cache (no UI) |
| Adminer | 8082 | `http://{{server.local_ip}}:8082` | Database browser |
| Mailpit | 8025 | `http://{{server.local_ip}}:8025` | Dev email catcher |
| Wiki.js | 3002 | `http://{{server.local_ip}}:3002` | Knowledge base |

## AI Stack (CPU-heavy — keep OFF without GPU)

| Service | Port | Notes |
|---------|------|-------|
| Ollama | 11434 | AI model engine |
| Open WebUI | 3004 | Chat interface |

Start when needed:
```bash
cd /srv/docker/ai && docker compose up -d
```

Stop when done:
```bash
cd /srv/docker/ai && docker compose down
```

## Hub

| Service | Port | URL |
|---------|------|-----|
| Server Hub | {{hub.port}} | `http://{{server.local_ip}}:{{hub.port}}` |

## See Also

- `docker.md` — managing containers and stacks
- `this-server.md` — live view of what's actually running right now
