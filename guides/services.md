# Services Reference

## Infrastructure

### Nginx Proxy Manager (port 81)
Routes domain names to containers. Handles SSL certificates.
- Admin: `http://192.168.1.229:81`
- Compose: `/srv/docker/npm/`

### Portainer (port 9443)
Visual Docker management — start/stop/inspect containers, view logs, manage volumes.
- URL: `https://192.168.1.229:9443`
- Compose: `/srv/docker/portainer/`
- Note: has an initial-setup timeout. If locked out: `sudo docker restart portainer`

### Cockpit (port 9090)
Linux admin panel in the browser — system metrics, services, terminal, networking.
- URL: `https://192.168.1.229:9090`

## Monitoring

### Homepage (port 3000)
Dashboard showing all services with live status from Docker socket.
- URL: `http://192.168.1.229:3000`
- Config: `/srv/docker/homepage/` (services.yaml, widgets.yaml, etc.)

### Uptime Kuma (port 3001)
Uptime monitoring with alerts. Sends push notifications via ntfy.
- URL: `http://192.168.1.229:3001`

### Netdata (port 19999)
Real-time CPU, RAM, disk, network graphs. No configuration needed.
- URL: `http://192.168.1.229:19999`

### Dozzle (port 8090)
Live log viewer for all Docker containers in the browser.
- URL: `http://192.168.1.229:8090`

## Notifications

### ntfy (port 8085)
Self-hosted push notifications. Used by Uptime Kuma for alerts and server auto-alerts.
- URL: `http://192.168.1.229:8085`
- Auto-alert cron runs every 15 min: checks containers, disk, memory

## Not Yet Installed (run 08-extras-setup.sh to install)

| Service | Port | Purpose |
|---------|------|---------|
| n8n | 5678 | Workflow automation |
| Supabase | 8000 | Database platform (Postgres) |
| Redis | 6379 | Cache / key-value store |
| MinIO | 9001 | Object storage (S3-compatible) |
| Adminer | 8082 | Database browser |
| Mailpit | 8025 | Dev email catcher |
| Wiki.js | 3002 | Knowledge base |

## AI Stack (CPU-heavy — keep OFF without GPU)

| Service | Port | Status |
|---------|------|--------|
| Ollama | 11434 | Installed, stopped |
| Open WebUI | 3004 | Installed, stopped |

Start when needed:
```bash
cd /srv/docker/ai && docker compose up -d
```

Stop when done:
```bash
cd /srv/docker/ai && docker compose down
```
