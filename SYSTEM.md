# ServerHub -- System Map

> Read this first. One file, full picture.

---

## The Premise

ServerHub is a control plane for a Linux server running Docker.

A Python **stdlib-only** HTTP server runs as a systemd **user** service. It gives you a browser UI and JSON API over everything happening on the server -- containers, disk, RAM, ports, logs, credential *pointers*, and AI.

It is no longer one file, and describing it as one was wrong on this page for
weeks after the split. `hub/server.py` is a bootstrap; routes are a dispatch
table in `hub/kernel/router.py`; request handling is one file per domain in
`hub/handlers/`; shared machinery is `hub/kernel/`. Dependencies flow one way
and **no handler imports `server.py`** — when they did, the split was cosmetic.

**Hard requirements:** Docker + Python 3. That is all.

Everything else -- Portainer, Netdata, n8n, Uptime Kuma, all of it -- are **optional services** that ServerHub manages. Hub does not depend on any of them. Hub watches them, reports on them, lets you control them from the browser, and alerts you when they go wrong.

No npm. No frameworks. No build step. Pure Python stdlib.

**Port:** `:8765`

---

## How a New Server Gets Set Up

**server-kit is the entry point.** It bootstraps a blank Ubuntu server into a full running stack:

```bash
git clone https://github.com/KGSHOPINV/server-kit
cd server-kit
bash install.sh
```

`install.sh` asks which optional services you want, then:
- Sets up Docker and system dependencies
- Deploys the services you selected under `/srv/docker/`
- Clones `claude-server` into `~/hub`
- Writes the hub's systemd **user** unit and starts ServerHub on **port 8765**

After that: `http://SERVER_IP:8765` -- you are live.

> This page said `7000` in three places, and `8765` in a fourth, for months.
> **8765 is the hub. Always. Never a container.** Corrected 2026-09-27.

**The installer must finish the job** — running it should end with the node at
standard and holding a live hostname, not with "installed, now go configure
Cloudflare". Whether it does today is `bash bootstrap.sh --check`, which asserts
against the machine and derives what to expect from the installer's own
heredocs.

---

## Two Repos -- Know the Split

| Repo | What it is | On server at |
|------|-----------|--------------|
| `KGSHOPINV/claude-server` | Hub app -- all code, UI, API | `~/hub` |
| `KGSHOPINV/server-kit` | Bootstrap installer + Docker stack | `~/server-kit` |

Hub app code goes in `claude-server`. Docker compose files and install scripts go in `server-kit`. Never cross them.

Third repo (private): `KGSHOPINV/FV-MF-SH-integrations` -- federation contracts between ServerHub, FlareVault, and Metaforge. On server at `~/FV-MF-SH-integrations`.

Update hub independently at any time -- no reinstall needed:
```bash
cd ~/hub && git pull && systemctl --user restart hub
```

---

## Optional Services (managed by ServerHub)

These are installed by server-kit. None are required for hub to function.
Hub monitors and controls all of them from the browser.

This list is **not written down here any more.** It was one of four
hand-maintained service tables in this repo that disagreed with each other, and
`hub/CONSTITUTION.md` §4 is explicit: *a bill of materials may never be prose.*

Ask the node:

```bash
curl -s localhost:8765/api/receipt   | jq '.containers'   # what is running, with ports
curl -s localhost:8765/api/services  | jq                 # known services + live docker state
curl -s localhost:8765/api/ports     | jq                 # what is actually listening
```

In the UI: **Server Receipt** view. The catalogue those endpoints enrich is
`SERVICES` in `hub/kernel/collect.py` — one list, in code, next to the scanner
that checks it. Port *lanes* (which range a new service may claim) remain prose
by necessity and live in `PORTS.md` and `MASTER.md` §2; port *assignments* do not.

---

## What ServerHub Does For These Services

- Shows every container's status in real time (running / stopped / unhealthy)
- Lets you restart, stop, or start any container from the browser
- Alerts via ntfy when a container dies or recovers
- Logs all events to the activity feed
- Exposes container state, port landscape, and server metrics via API
- Pushes that data to FlareVault and Metaforge when federation is active

Hub does not care which services are installed. It reads what Docker has running and works with whatever is there.

---

## API surface, port map, file tree, CLI tools and units — all derived

Five hand-maintained tables stood here. Every one of them drifted, and three of
them were **actively wrong in a way that would cost you an hour**:

- the hub's port was given as `7000` in three places and as `8765` in a fourth,
  on the same page
- ntfy was given as `:7001` in one place and `8085` in another
- the file tree described `server.py` as *"entire backend, all routes"*, which
  stopped being true when the monolith was split into `kernel/` and `handlers/`

That is what a typed table does. Ask instead:

| What you wanted | What answers it |
|---|---|
| Every route, from the route table itself | `curl -s <hub>/api/sitemap` |
| What is actually listening, with lane and owner | `curl -s <hub>/api/ports` |
| This machine, completely | `curl -s <hub>/api/receipt` |
| Mounts, volumes, Docker usage, log size | `curl -s <hub>/api/storage` |
| The code's own parts, with telescope codes | `python3 hub/tools/atlas.py --parts` |
| Which units exist on a node, and which fire | `systemctl --user list-timers` **and** `systemctl list-timers` |
| Which CLI tools a node has | `ls /usr/local/bin/` on that node |
| Every external system this touches, and what binds each write | `python3 hub/tools/edges.py` |

**Check both unit paths, always.** A script this repo once recorded as "invoked
by nothing" was `ExecStartPost=` in a **user** unit and had been firing the
fleet's wrongest alert on every restart. The audit that declared it dead had
read only `/etc/systemd/system`.

The one constant worth stating, because it is a rule and not a reading:
**the hub is `:8765`, it is never a container, and 8765 is never assigned to
one.** The hub must survive Docker being down — a monitor inside the thing it
monitors dies exactly when it is needed.

## Federation DAG

ServerHub, FlareVault, and Metaforge are three sovereign systems. Each has a doctrine. They communicate only through agreed API endpoints.

```
Boot order:  SH -> FV -> MF    (SH is always first -- it installs before anything else)

          +-----------------------------------------------+
          |               ServerHub (SH)                  |
          |  - installs first on any server               |
          |  - control plane over Docker                  |
          |  - exposes port landscape, capacity, events   |
          |  - NEVER modifies MF containers               |
          |  - defers all credentials to FV               |
          +------------------+----------------+-----------+
                             |                |
                             |                |
          +------------------v--+    +--------v-----------+
          |   FlareVault (FV)   |    |   Metaforge (MF)   |
          |  - credentials      |<-->|  - entity ledger   |
          |  - Cloudflare layer |    |  - fuse colors     |
          |  - deploys services |    |  - tenant registry |
          +---------------------+    +--------------------+
```

**SH -> FV:** port landscape before any deploy, capacity check, container health events, external watch on FV node (FV cannot see itself go down from inside Docker).

**SH -> MF:** `/api/context` primary handoff, container feed, activity log, port landscape for drift detection.

---

## Multi-Server Architecture — DESIGN, NOT BUILT (checked 2026-09-23)

> The HQ/node pairing flow that stood here was written in the present tense as
> though it existed. It does not. `POST /api/pair` and `GET /api/peers` are in
> no route table — grep `hub/kernel/router.py`. They are listed as future work
> in `TASKS.md` → "HQ/Node Pairing". There is no `role: "hq"` and no `hq_url`
> anywhere in the codebase, and `install.sh` takes no `PAIR_TOKEN`/`PAIR_HOST`.
> The design is kept below because it is still the intent; the labels are fixed
> so nobody calls an endpoint that was never written.

**What is actually built and live**

| Route | Does |
|---|---|
| `POST /api/peer/register` | bidirectional peer handshake — adds the caller's URL to this hub's `peers` list in `hub_config` and calls back |
| `GET /api/federation` | the peer list plus FlareVault / Metaforge URLs |
| `POST /api/federation` | set `fv_url`, `mf_url`, `peers`, contact timestamps |
| `POST /api/mesh/register`, `GET /api/mesh/fleet` | mesh membership and the fleet view |
| `POST /api/heartbeat` | node liveness |
| `GET /api/identity`, `GET /api/node` | who this node is |

Note the shape: the stored `peers` value is a **JSON list of URL strings**, not
the `{name, url, role}` objects the old text showed. `hub/handlers/identity.py`
and `hub/handlers/node.py` both carry the same warning — peers keyed by URL die
when the address moves, so machine-id is the better key.

**Still to build** (design intent, see `TASKS.md`)

- one-time pairing token with expiry, generated from the HQ dashboard
- `POST /api/pair` — token + node identity, token consumed on use
- `GET /api/peers` — all peers with live status polled from each
- an explicit HQ role in hub config, so a node knows who aggregates it

**Server identity** — each hub declares its name at install time; it is served by
`GET /api/identity`. Whether every response carries a `server` field is a
property of the code, not of this file: check `hub/kernel/identity.py`.

---

## MCP Server (planned)

ServerHub will expose its API as an MCP server so any Claude session can call hub tools directly without SSH.

Planned tools:
- `get_status()` -- RAM, CPU, uptime, load
- `get_containers()` -- all Docker containers + state
- `restart_container(name)` -- restart any container
- `run_command(cmd)` -- TOTP-gated shell execution
- `get_ports()` -- full port landscape
- `get_storage()` -- disk, mounts, usage
- `get_activity()` -- event log
- `get_peers()` -- all registered server nodes

Two corrections to the list above, as of 2026-09-23: `server-kit/mcp/` does not
exist (`server-kit/` contains `tools/` only), and `get_peers()` names a route
that was never built — the live equivalents are `GET /api/federation` and
`GET /api/mesh/fleet`. Build the tool list from `GET /api/sitemap`, which is
generated from the route table, rather than from this list.

When built, the MCP server lives in `server-kit/mcp/`. Combined with Cloudflare Tunnel, any Claude session can connect to hub from anywhere.

---

## Federation build state — not a table here

A status table of LIVE / NOT BUILT rows stood here, blocked-on column and all.
Rows went stale in both directions and nothing could tell you which.

```bash
python3 hub/tools/edges.py       every external joint, what binds each write, and what breaks without it
python3 hub/tools/atlas.py       which planes the installer produces, and which were typed
curl -s <hub>/api/sitemap        what actually answers
```

`edges.py` is the right instrument for this question specifically: it names, per
joint, **what breaks without it** and **where the credential comes from (never
the value)** — which is what a "blocked on" column was trying and failing to say.
## New Session Quickstart

1. Read this file
2. Read `TASKS.md` for what is next
3. SSH in: `ssh YOUR_USER@YOUR_SERVER_IP`
4. Check hub: `curl -s http://localhost:8765/api/status | python3 -m json.tool`
5. Check containers: `dkps`

Done. You are oriented.

---

## Troubleshooting

```bash
# Hub won't start
journalctl --user -u hub -n 50 --no-pager

# Container down
dklogs CONTAINER_NAME

# Full health dump
health-check

# After power outage -- find anything not running
docker ps --format "table {{.Names}}\t{{.Status}}" | grep -v " Up "
```

**ntfy note:** ntfy is **8085**, always — the notifications lane. (`:7001`
stood here and was never right.) A phone receives alerts only if it can reach
that endpoint, which means Tailscale or a tunnel. **ntfy deliberately stays off
Cloudflare Access** — it is an app endpoint with its own token auth, and Access
would silently kill push.

Whether ntfy is delivering anything is a separate claim from whether it is
running: it sat correctly configured and locked deny-all, having published
nothing, while a panel claimed alerts were going to it. Built and delivering
nothing is not the same as built. `curl -s <hub>/api/events/self`.

**AI stack:** keep OFF unless actively using. No GPU -- full CPU load if models run.
