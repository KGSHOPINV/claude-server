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
| Vault UX overhaul | Full modal UI — category pills, search, copy buttons, password generator, no more `prompt()` |
| Update Hub button | `⬆ Pull Latest & Restart` in Settings → runs git pull + service restart |
| Quick-ref print card | `manual/quick-ref.html` — one-page A4 with all IPs, ports, URLs, CLI tools, runbooks |
| Hub Survey view | 🔍 Survey in nav — one-click full health report: containers, disk, RAM, load, maintenance |
| Alert system → ntfy | `hub-alert.timer` every 15 min — state-change alerts only (down + recovery). `hub-daily.timer` 7am morning brief |
| n8n Disk Alert workflow | Imported + activated — checks disk via Netdata every 2h, ntfy alert at 72%/85% |
| **Phase 1 — kernel extraction** | `db/auth/ssh/log/router` split out of server.py. Merged PR #9 |
| **Phase 2 — handler split** | 11 handlers + `kernel/collect.py`. **server.py 2,890 → 122 lines.** Cycle broken: handlers no longer import server.py. Merged `ab02c2f` |
| **Deploy path repaired** | `update.sh` copied the app where its imports failed — broken since Phase 1, which is why fks sat 15 commits behind. Fixed + tested on both servers |
| **Both servers current** | fks-services and ksgcohub both on `ab02c2f`, 41/41 routes verified against a copy of the prod DB |
| **Two-door auth built** | Cloudflare Access identity accepted only from the tunnel address; local login stays the break-glass. Off by default — see `guides/remote-access.md` |
| **Phase 3 started** | `/ui/` static route + `ui/registry.js`. Adding a view = one file + one registry entry. 2 of 19 views migrated |
| **Deployment landscape documented** | `guides/deployment.md` + 6 rows in `knowledge/decisions.sql` |

---

## 🔵 Up Next

**Needs the user — sudo or a browser, cannot be automated:**

| Task | Notes |
|------|-------|
| 🔴 **Rotate the sudo password** | `1234qwerR` is in **public** git history (`a34a8f1`). Check reuse on Portainer, NPM, n8n, Uptime Kuma |
| **Merge PR #11** | 7 commits: security fix, two-door auth, docs, Phase 3 |
| **Tailnet re-auth on fks-services** | `sudo tailscale up --force-reauth` as `ksg.co.hub@gmail.com`. Fixes the mesh — both hubs already have each other as peers but sit on different tailnets |
| **Remove stale system unit** | `/etc/systemd/system/hub.service` is enabled and points at a deleted file |

**Ready to build:**

| Task | Notes |
|------|-------|
| **Phase 3 — remaining 17 views** | Next ones aren't static stubs: `dashboard`, `network`, `terminal`, `logs` call helpers still in app.html |
| **Enable two-door auth** | Built and tested; needs `HUB_CF_TRUST_IP` on ksgcohub's unit |
| **Login events → ntfy** | The hub records **no logins at all**, successful or failed. ntfy only fires on container events |
| **UUID in `/api/identity`** | Peers are keyed by URL, so an address change kills the peer. Machine-ids are stable and already recorded |
| **Fix `_users_list()`** | Returns `[]` on any exception — `/api/users` currently lies on ksgcohub |
| **Persist sessions** | In-memory dict; every hub restart logs everyone out |
| **Service tokens** | Named long-lived tokens with role scope — separate AI/n8n identity from human sessions |
| **Uptime Kuma → ntfy** | Add ntfy channel in Uptime Kuma (Settings → Notifications) |
| **Vaultwarden** | Self-hosted Bitwarden on 8083 |

**Deliberately not done:**

| Task | Why |
|------|-----|
| Gate enforcement | 52 of 66 routes gated in the table; app.html sends a token on 16 calls. Arming it locks the UI out |
| Vault view link | Hardcodes `192.168.1.229:7779` — wrong when the hub runs on ksgcohub |

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

## Planned Builds

### MCP Server
- Expose /api/* as Claude tools via MCP protocol
- Lives in server-kit/mcp/
- Auth: TOTP or Cloudflare service token
- Enables Claude to act on server from any session without SSH

### HQ/Node Pairing  *(partly built — `/api/peer/register` exists and both
servers already list each other as peers; blocked only by the tailnet split)*
- /api/pair endpoint -- accepts one-time token + node identity
- /api/peers endpoint -- returns all nodes with live status
- HQ dashboard peer view -- see all servers in one UI
- Pairing token generator in hub config UI

### Cloudflare Tunnel Setup  *(live on ksgcohub — hub.ksgco.app, ntfy.ksgco.app,
fks.ksgdev.com. fks-services has no tunnel at all)*
- cloudflared service routing hub.domain.com -> localhost:8765
- ntfy.domain.com -> localhost:8085 (phone alerts without Tailscale)
- Cloudflare Access policy (email OTP gate)
- Service tokens for Claude, MF, FV identities

### Server Identity
- Declared name at install time -- written to hub config
- Every /api response includes "server": "name"
- CLAUDE.md template filled with real server identity at install

---

## Hub Architecture

```
hub/
  server.py       # 122 lines. Bootstrap only: HTTP shell, dispatch, threads
  kernel/         # router (66 routes) · collect · db · auth · ssh · log
  handlers/       # one file per domain — identity status federation config
                  # users events ai tunnel proxy ops. Imports kernel/ only
  ui/             # registry.js + views/ (Phase 3 — 2 of 19 migrated)
  app.html        # Desktop UI — 6,518 lines, still one file
  mobile.html     # Mobile UI
  maintenance.py  # Nightly maintenance agent

# Dependencies flow one way: server -> router -> handlers -> kernel

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
