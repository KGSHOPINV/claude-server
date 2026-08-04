# Server Hub — Task Docket

> Live roadmap for the home server control panel project.
> Stack: Python hub server · React-style vanilla JS · SQLite · Docker · Ubuntu 24.04

---

## ✅ Done

| Task | Notes |
|------|-------|
| Nightly maintenance agent | Python agent + ntfy alerts — runs via systemd timer nightly |
| TOTP gate system | 2FA over all `/api/run` calls. Gate modal in desktop + mobile. 30-min sessions |
| Adminer / Mailpit / Wiki.js | All deployed and running (ports 8082, 8025, 3002) |
| Portainer fix | Fresh DB reset + Watchtower pinned to 1.7.1 with `DOCKER_API_VERSION=1.41` |
| Hub as systemd service | `hub.service` — auto-restarts, survives SSH disconnect |
| PWA + desktop shortcut | `manifest.json` served — Chrome/Edge installable. `.url` + `.bat` on desktop |
| Guide / Cribs page | `🏠 Guide` category in hub — feature cards, stack view, task docket, links |

---

## 🔵 Up Next

| Task | Notes |
|------|-------|
| **Service tokens** | Named long-lived tokens with role scope — separate AI/n8n identity from human TOTP sessions |
| **Update Hub button** | One-click `git pull` + hub restart from Settings view |
| **n8n health alert → ntfy** | n8n workflow that pings ntfy when any monitored service goes down |
| **Wire AI key into setup** | Install script prompts for API key, stores in `hub_config` — AI chat works out of the box |

---

## 💡 Ideas

| Task | Notes |
|------|-------|
| Supabase install | Full Postgres + auth + realtime. Large — spin up when needed |
| MinIO install | S3-compatible object storage — backups + AI assets |
| Tailscale deep integration | Show node map, peer list, MagicDNS in Infra Map |
| Mobile APK (TWA) | Wrap `mobile.html` as Trusted Web Activity APK for Android |
| Cert monitoring | Alert when any TLS cert is <14 days from expiry |
| Backup restore UI | One-click restore from backup list in Storage view |

---

## Hub Architecture

```
hub/
  server.py       # Python HTTP server (stdlib only) — all API routes
  app.html        # Desktop UI — multi-pane workspace, tabs, vault, TOTP
  mobile.html     # Mobile UI — swipe tabs, gate modal, ntfy
  maintenance.py  # Nightly maintenance agent

db/
  server.db       # SQLite — hub_config, users, journal, vault blob (gitignored)

notes/
  secrets.env     # Credentials (gitignored — never committed)

guides/           # Markdown guides served via /api/docs
issues/           # Per-service issue files served via /api/issues
```

## Key Ports

| Service | Port | URL |
|---------|------|-----|
| **Hub** | 8765 | http://192.168.1.229:8765 |
| NPM | 81 | http://192.168.1.229:81 |
| Portainer | 9443 | https://192.168.1.229:9443 |
| Homepage | 3000 | http://192.168.1.229:3000 |
| Uptime Kuma | 3001 | http://192.168.1.229:3001 |
| Netdata | 19999 | http://192.168.1.229:19999 |
| Dozzle | 8090 | http://192.168.1.229:8090 |
| n8n | 5678 | http://192.168.1.229:5678 |
| Adminer | 8082 | http://192.168.1.229:8082 |
| Mailpit | 8025 | http://192.168.1.229:8025 |
| Wiki.js | 3002 | http://192.168.1.229:3002 |

## Useful Commands

```bash
# Hub service
systemctl --user status hub
systemctl --user restart hub
journalctl --user -u hub -f

# All containers
docker ps --format "table {{.Names}}\t{{.Status}}"

# Quick health check
ssh admin1@192.168.1.229 "health-check"
```
