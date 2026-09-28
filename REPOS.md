# Two-Repo Architecture

This project exists across two GitHub repositories with a clear split of
responsibility — and the split follows **the layers, not convenience.**

> **The test, from `hub/CONSTITUTION.md` §6:** *could a stranger install this
> without receiving anything personal?* The installer currently clones the
> workspace repo onto every node, which ships `CLAUDE.md` — both servers'
> addresses and SSH usernames — along with session notes and a local database,
> to every machine that installs. **Today the answer is no**, and closing that
> is the reason the split exists rather than a tidiness preference.
>
> | Repo | Holds | Ships to a node |
> |---|---|---|
> | **serverhub** | the product: `hub/`, `tools/`, `bootstrap.sh` | **yes** |
> | **workspace** (this one) | notes, session logs, `CLAUDE.md`, issues | **never** |
> | **integrations** | contracts between the three systems | no — read by all |

---

## Repositories

| Repo | Purpose | Audience |
|------|---------|----------|
| `KGSHOPINV/claude-server` | Hub app — the control panel | Hub developers, iterators |
| `KGSHOPINV/server-kit` | Bootstrap installer — gets a server ready | New server installs |

---

## claude-server (this repo)

**What it is:** The Server Hub — a Python HTTP server + single-page app that gives you a browser-based control panel over a Linux server.

**What it owns:**
- the hub runtime — `hub/server.py` (a bootstrap), `hub/kernel/`, `hub/handlers/`
- the frontends it serves, and `hub/ui/`
- `hub/guides/` — markdown docs the hub serves at `/api/docs`
- `hub/tools/` — the instruments. Report, never repair
- `notes/`, `db/` — local, gitignored, and they **never ship to a node**

**What it does NOT contain:**
- Docker compose files for any service (those live in server-kit or directly on the server)
- Bootstrap/install scripts for getting a fresh server ready
- Any hardcoded server credentials

**How it gets to the server:**
```bash
# server-kit's install.sh does this automatically:
git clone https://github.com/KGSHOPINV/claude-server ~/hub
```
Then `hub.service` runs `server.py` on the server as a systemd unit with `HUB_LOCAL=1`.

**Independent update cycle:**
```bash
# On the server — update hub without touching Docker stack:
cd ~/hub && git pull && sudo systemctl restart hub
```

---

## server-kit (separate repo)

**What it is:** A complete, USB-ready bootstrap kit for standing up a fresh Linux server with this full Docker stack.

**What it owns:**
- the numbered setup script series
- Docker compose files for the optional services
- `tools/` — CLI tools deployed to `/usr/local/bin/`
- `install.sh` — the one-command installer
- its own documentation

Its exact contents are not listed here; a directory listing cannot go stale and
this paragraph could.

**What it does NOT contain:**
- Hub application code (delegates to claude-server via git clone)
- Any live server state or secrets

**Reference to this repo:**
server-kit's `install.sh` clones `claude-server` at install time:
```bash
git clone https://github.com/KGSHOPINV/claude-server ~/hub
```

---

## Exclusion Rules

| Thing | Goes in | NOT in |
|-------|---------|--------|
| Hub app code | claude-server | server-kit |
| Docker compose files | server-kit | claude-server |
| Bootstrap scripts | server-kit | claude-server |
| Claude MCP config | server-kit | claude-server |
| Secrets / credentials | **neither** (local only, gitignored) | both |
| guides/*.md | claude-server | server-kit |
| CLI tools (/usr/local/bin/) | server-kit | claude-server |

---

## The Lifecycle

```
1. Download server-kit (git clone or zip download)
2. Run: bash install.sh
   → asks: server IP, SSH user, timezone, admin password
   → runs 01-16 setup scripts
   → clones claude-server → ~/hub
   → writes hub.service → starts hub on :8765
3. Browse to http://SERVER_IP:8765
4. Update hub independently: cd ~/hub && git pull && sudo systemctl restart hub
5. Update stack independently: cd ~/server-kit && git pull && bash self-update.sh
```

---

## Manifest / System Pulse

The hub exposes a live snapshot at `/api/manifest` — all services, container states, health, server info, disk — as a single JSON download.

From the hub UI: Settings → "Download System Snapshot"
Direct URL: `http://SERVER_IP:8765/api/manifest?download=1`
