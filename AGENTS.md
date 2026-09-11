# AGENTS.md — AI Session Entry Point

> Read this first. Every AI session touching this repo should orient here before doing anything.

---

## What this repo is

Two servers, one codebase. A Python stdlib HTTP server (`hub/server.py`) runs on each node.
It handles status, federation, auth, Docker info, logging, AI chat, and incidents.
The frontend is a single HTML file (`hub/app.html`) with an embedded workspace/pane UI.

**No longer a monolith.** `hub/server.py` is a 122-line bootstrap. Routes live in
`hub/kernel/router.py` (dispatch table), request handling in `hub/handlers/` (one
file per domain), shared machinery in `hub/kernel/`. Dependencies flow one way:
server -> router -> handlers -> kernel. No handler imports server.py.

The frontend is still a single 6,518-line file. That is Phase 3.
See `docs/refactor-plan.md`.

---

## Servers

| Name | Role | Notes |
|------|------|-------|
| fks-services | Work server, primary | 216GB RAM, 34 containers, FlareVault node |
| ksgcohub | Home server | 12 containers, CF tunnel active |

**Real IPs, Tailscale IPs, SSH users, and UUIDs are in `notes/secrets.env` and `knowledge/servers.json` — gitignored, never committed.**
Connection details for this work PC session are in `CLAUDE.md` (also gitignored).

---

## Repo layout

```
claude-server/
  hub/
    server.py          — 122 lines. Bootstrap only: HTTP shell, dispatch, threads.
    kernel/
      router.py        — route table (66 routes) + dispatch
      collect.py       — system-state collectors (Docker, ports, storage, proxy)
      db.py auth.py ssh.py log.py
    handlers/          — one file per domain. Imports kernel/ only.
      identity status federation config users events ai tunnel proxy ops
    app.html           — 6,518 lines. Single-file SPA frontend.
    mobile.html        — Mobile shell (lower priority)
    db/server.db       — SQLite. gitignored. Tables: hub_config, activity_log, incidents
  server-kit/
    server.manifest.yml  — BOM for kit-status checks
    install.sh           — Master install script for new servers
    tools/
      kit-status.sh           — Checks all services, posts to ntfy
      boot-health-check.sh    — Oneshot systemd check on every boot
      boot-health-check.service
      fix-netplan.sh          — Removes cloud-init netplan conflict
  knowledge/
    registry.json      — Machine-readable manifest (servers, files, services)
    decisions.sql      — Architecture decisions seed data
    servers.json       — Device UUIDs + connection info
  docs/
    refactor-plan.md   — Phased migration blueprint
  memory/              — Claude persistent memory (not for AI sessions, for Claude Code)
  notes/
    secrets.env        — gitignored. Passwords, tokens, IPs.
  CLAUDE.md            — gitignored. SSH/IP details for this work PC session.
  MASTER.md            — Human-readable system reference
  AGENTS.md            — This file
```

---

## Key endpoints (hub API)

| Method | Path | What it does |
|--------|------|-------------|
| GET | /api/status | Aggregated server info, uptime, load |
| GET | /api/containers | Docker container list + state |
| GET | /api/ports | Active port map |
| GET | /api/sitemap | Full route registry (self-documenting) |
| GET | /api/identity | Node identity: hostname, role, UUID |
| GET | /api/incidents | Last 50 incidents |
| POST | /api/incidents | Create incident |
| POST | /api/peer/register | Join mesh (bidirectional) |
| GET | /api/federation | List known peers |
| GET | /api/hub-context | (NOT BUILT YET) Full AI session context |

Auth: session token in `Authorization: Bearer <token>` header or `token` cookie.
Gate levels: 0=public, 1=user, 2=admin, 3=TOTP.

---

## Kernel primitives (extracted — Phase 1 complete)

| Function | Line (approx) | Target |
|----------|--------------|--------|
| `db_conn()` | ~50 | kernel/db.py |
| `check_auth()` | ~120 | kernel/auth.py |
| `gate_check()` | ~140 | kernel/auth.py |
| `ssh_run()` | ~200 | kernel/ssh.py |
| `log_activity()` | ~250 | kernel/log.py |

Route dispatch is a table in `kernel/router.py`. The if/elif chain is gone.
Gate enforcement is evaluated at dispatch but NOT applied: the table gates 52 of 66
routes while app.html sends a token on 16 calls. `HUB_ENFORCE_GATES=1` arms it;
`router.shadow_report()` shows what would break first.

---

## Services running (key ones)

### fks-services
- hub :8765, flarevault-node :7777, flarevault-monitor, n8n :5678
- postgres :5432, redis :6379, postgraphile :5000, supabase :8000
- netdata :19999, portainer :9443, surrealdb :8001

### ksgcohub
- hub :8765, nginx-proxy-mgr :81, ntfy :8085, n8n :5678
- surrealdb :8001, uptime-kuma :3001, netdata :19999
- portainer :9443, dozzle :8090, redis :6379, homepage :3000
- Cloudflare Tunnel: hub.ksgco.app → :8765, ntfy.ksgco.app → :8085

Full service list with compose paths: `knowledge/registry.json` under `services[]`.

---

## Things NOT YET BUILT (don't assume these exist)

- `hub/ui/` directory (Phase 3)
- `/api/hub-context` endpoint
- FV MCP server
- Ubuntu autoinstall ISO generator
- Backup systemd timer (script exists, timer not set)
- Auth gate on Receipt and AI Chat views
- TOTP gate on hub

---

## Security rules (always enforce)

- Never commit passwords, IPs, or tokens to GitHub
- `notes/secrets.env` is gitignored — real credentials live there
- `CLAUDE.md` is gitignored — SSH details live there
- `hub/db/server.db` is gitignored
- Every code change: commit + push immediately, no batching
- AI stack stays OFF unless user explicitly asks
- Never assign port 8765 to a container
- Confirm before restarting or stopping services

---

## Quick orientation for a new AI session

1. Read this file
2. Read `docs/refactor-plan.md` for where the code is going
3. Read `knowledge/registry.json` for the current state barcode
4. Check `knowledge/decisions.sql` for why things are the way they are
5. Check `hub/db/server.db` incidents table for recent problems
6. Never touch `notes/secrets.env` — read it, don't commit it

---

*Last updated: 2026-09-09*
