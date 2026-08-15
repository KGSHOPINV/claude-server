# Architecture Map

How Server Hub fits into the full system — two repos, order of operations, access layers, and where this is going.

---

## Two Repos — Source of Everything

```
claude-server              server-kit
─────────────────          ─────────────────────────
hub/server.py              00-bootstrap.sh
hub/app.html               01–16 install scripts
hub/guides/                docker/ (24 compose files)
PORTS.md                   docs-site/ → Netlify
CLAUDE.example.md
```

**server-kit** sets up a blank server (Docker, UFW, Fail2Ban, all services by tier).  
**claude-server** is the hub app that runs on a server after server-kit has done its job.

The server pulls from `claude-server` on GitHub on every update. The Netlify docs site builds from `server-kit`.

---

## Order of Operations — Any New Server

These always run in this order:

| Step | What | How |
|------|------|-----|
| 1 · Provision | Bare Ubuntu 24.04, SSH key access | VPS, homelab, cloud |
| 2 · Bootstrap | Docker, UFW, Fail2Ban, SSH hardening | `server-kit/00-bootstrap.sh` |
| 3 · Stack | Services by tier (only what you need) | Scripts 01–16 |
| 4 · Hub | Clone claude-server, set `HUB_SSH_HOST`, start systemd | `systemctl --user start hub` |
| 5 · Access | Tailscale enroll, Cloudflare tunnel | :8765 = control room |

`HUB_SSH_HOST` is the only thing that tells the hub which server it's controlling. Default is `localhost` (hub on the same box it controls). Set it to `user@ip` to control a remote machine.

---

## The Hub at :8765

Eight views, one port:

| View | What it gives you |
|------|-------------------|
| **Server** | Live RAM, CPU, disk, uptime, container count |
| **Services** | All Docker containers — start, stop, restart, logs |
| **Terminal** | SSH shell in the browser, command history |
| **Files** | Browse the server filesystem |
| **Vault** | Encrypted passwords — master key never leaves the browser |
| **Remote** | Local / Tailscale / Cloudflare URLs, tunnel on/off |
| **Infra Map** | Visual map of running services and ports |
| **Docs** | In-app guides (this file) |

Backend: Python stdlib HTTP server, SQLite for state, TOTP gate on shell endpoints.

---

## Access Topology — Three Paths In

```
LAN           192.168.x.x:8765   Same network, just works
Tailscale     100.x.x.x:8765    Your devices, anywhere — intranet extension
Cloudflare    https://hub.domain  Anyone with the URL, Access auth gate optional
```

**The key division:**
- Your devices → Tailscale (you're *on* the intranet from anywhere)
- Public internet / sharing → Cloudflare Tunnel + Access

Tailscale also makes SSH trivial from anywhere: `ssh user@100.x.x.x` — no port forwarding, no jump host.

See `remote-access.md` for the full breakdown of each tool.

---

## Port Lanes

All services are assigned to category-scoped port ranges. See `PORTS.md` in the repo root.

| Lane | Range |
|------|-------|
| Hub | 8765 (reserved) |
| Infrastructure | 3000–3099 |
| Monitoring | 19000–19999 |
| Automation | 5600–5699 |
| Database | 5400–5499, 6300–6399 |
| Storage | 9000–9099 |
| Admin | 9400–9499 |
| AI | 11000–11999 |

---

## Multi-Server — Where This Is Going

The hub is built to be portable. `HUB_SSH_HOST` makes it point at any server. Three patterns:

**Pattern A — one hub, SSH into remote**  
Hub runs on Server A. `HUB_SSH_HOST` points at Server B via Tailscale IP. Hub A's terminal and monitoring run against B. No hub on B required.

**Pattern B — hub on each server**  
Each server runs its own hub at `100.x.x.x:8765`. Switch between them in the browser. Same vault, same GitHub-backed config.

**Pattern C — hub of hubs (planned)**  
A server picker UI — one hub that registers multiple servers and switches SSH context between them. Tracked in GitHub Issues.

---

## What Makes It Portable

- No hardcoded IPs in source — `HUB_SSH_HOST` / `HUB_SSH_USER` env vars
- `CLAUDE.md` gitignored — real IPs and SSH details stay local
- `server_info` read live from the server at runtime (hostname, OS, IP, cores, home dir)
- Drop on any Ubuntu box: clone, set env vars, start systemd — done in ~5 min
