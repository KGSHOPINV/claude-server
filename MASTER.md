# MASTER — Complete System Reference

> **This file holds laws and the reasons for them. It is not a source of
> truth about any machine** — it was, and it was wrong: it listed a "7. Backup"
> step that nothing executed, so a server ran for months with no backups while
> this page looked correct. *Prose has no failure mode.*
>
> Ask a machine what a machine is:
>
> ```bash
> python3 hub/tools/atlas.py        what exists, and what was typed rather than installed
> python3 hub/tools/situation.py    what is serving and what is exposed
> curl -s <hub>/api/receipt         this machine, completely
> curl -s <hub>/api/ports           what is actually listening
> ```

---

## 1. Servers in the Ecosystem

**Not listed here.** Addresses, Tailscale IPs and SSH users live in `CLAUDE.md`,
`notes/secrets.env` and `knowledge/servers.json` — all gitignored, none of which
ships to a node. Which nodes exist is derived from the zone's records by
`kernel.fleet.discover`; ask `python3 hub/tools/situation.py`.

**Hub on every server:** `~/hub/` — Python stdlib HTTP server, port **8765**,
systemd **user** service (so it runs without root and survives the SSH session).
**Source:** https://github.com/KGSHOPINV/claude-server
**Bootstrap:** https://github.com/KGSHOPINV/server-kit

---

## 2. Port Lanes — The Law

Ports are assigned by lane. Pick the next free port in the correct lane. Never use random ports.

| Lane | Range | Category |
|------|-------|----------|
| System | 80, 443 | Public HTTP/HTTPS — handled by NPM only |
| Hub | **8765** | Server Hub — reserved, never assign to a container |
| Infrastructure | 3000–3099 | Dashboards, admin UIs, core tooling |
| Monitoring | 19000–19999 | Metrics, graphs, health |
| Automation | 5600–5699 | Workflow engines, schedulers |
| Database | 5400–5499, 6300–6399 | SQL, NoSQL, key-value |
| API / Tools | 8000–8099 | Admin UIs, API tooling |
| Notifications | 8080–8089 | Push alerts, webhooks |
| Storage | 9000–9099 | Object storage, file services |
| Admin | 9400–9499 | Container managers, Linux admin |
| AI | 11000–11999 | Model engines, chat UIs |

### Assignments are not written down here

A port *lane* is a rule and belongs in a document. A port *assignment* is a fact
about a machine and does not — two hand-typed assignment tables stood here, each
row carrying a tick nobody re-checked, and they disagreed with three other
service inventories in this repo.

```bash
curl -s <hub>/api/ports              what is bound, with lane and owner per port
curl -s "<hub>/api/admit?project=X"  the band a project may bind inside, derived live
python3 hub/tools/situation.py       plus what is exposed beyond the box
```

`/api/admit` computes a free band from the live port map at the moment you ask,
so it is never stale. **Lanes are a declaration, not a policy** — nothing
enforces them, which is exactly how admission handed out ports inside another
stack's reserved lane for months while two places answered the same question
differently.

**Rules:**
- 8765 is Hub. Always. Never a container.
- ntfy is 8085. Always.
- If you add a new service, check this list first, pick the next free port in the lane, add it here.

---

## 3. Naming Convention — The Law

```
/srv/docker/
  SERVICE/              ← shared infrastructure
  PROJECTNAME-SERVICE/  ← project-specific (isolated)
```

**Folder name = container_name = stack name.** No exceptions, no Docker-generated names.

| Pattern | Example | Use case |
|---------|---------|----------|
| `redis` | `/srv/docker/redis/` → container `redis` | Shared utility |
| `keyknox-redis` | `/srv/docker/keyknox-redis/` → container `keyknox-redis` | Project-isolated |
| `metaforge-db` | `/srv/docker/metaforge-db/` → container `metaforge-db` | MetaForge's DB |
| `flarevault-api` | `/srv/docker/flarevault-api/` → container `flarevault-api` | FV service |

**Why:** Hub's dynamic discovery reads `docker ps` by name. CLI tools (`dklogs`, `dkrestart`) use the name. Portainer shows it as a named stack. Everything is findable without documentation.

---

## 4. Ecosystem Map

```
┌─────────────────────────────────────────────────────────┐
│                    SERVER HUB (8765)                    │
│         Native Python — runs on every server            │
│  /api/status  /api/containers  /api/ports  /api/storage │
│  /api/identity  /api/peer/register  /api/federation     │
└──────────┬──────────────────────────┬───────────────────┘
           │                          │
    pushes health/ports        pushes container
    events + port landscape    feed + activity
           │                          │
    ┌──────▼──────┐           ┌───────▼──────┐
    │  FlareVault  │           │  MetaForge   │
    │  (FV)        │           │  (MF)        │
    │  Cloudflare  │           │  Project     │
    │  management  │           │  orchestrator│
    └─────────────┘           └──────────────┘
           │                          │
           └──────────┬───────────────┘
                      │
              ┌───────▼────────┐
              │  Peer Mesh     │
              │  /api/identity │
              │  /api/peer/    │
              │  register      │
              └────────────────┘
```

### What Hub feeds FV:
- Port landscape (all bound ports + federation fields)
- Health events via ntfy

### What Hub feeds MF:
- `/api/context` — server snapshot
- Container feed (all running containers with names)
- Activity log

### Peer mesh:
- Every hub exposes `/api/identity` → hostname, hub_url, local_ip, tailscale_ip
- `POST /api/peer/register {hub_url, echo:true}` → bidirectional handshake, both hubs register each other
- Peers visible in federation panel

---

## 5. What's on Each Server

Two hand-typed tables stood here, one per server, each row carrying a green tick
that nobody re-checked. They were a bill of materials in prose, which
`hub/CONSTITUTION.md` §4 forbids: *the moment a bill of materials is typed into
a table, it is wrong and nobody knows.* Deleted 2026-09-23 in favour of the node
answering for itself.

```bash
curl -s <hub>/api/receipt  | jq '{hostname, os, uptime, disks, containers}'
curl -s <hub>/api/services | jq                  # catalogue + live docker state
curl -s <hub>/api/ports    | jq                  # what is really listening
curl -s <hub>/api/storage  | jq                  # mounts and usage
```

Same answer in the UI: the **Server Receipt** view, per node. `/api/receipt`
also returns `sync_issues` — services expected by the catalogue in
`hub/kernel/collect.py` that are not running. That is the list that used to be
guessed at with ticks.

**The one class of thing the receipt cannot tell you**, stated as a rule
rather than as a list:

**A service installed outside Docker is invisible to every container-shaped
question.** A snap, an apt package, anything bound by the host directly — it
never appears in `docker ps` and never in `/api/receipt`'s container list. Only
`/api/ports` sees it, because only `/api/ports` reads the sockets rather than
the daemon. So a port can be occupied by something no container view will ever
show you, and **`/api/ports` is the authority on what is bound**, not the
container list.

That is also why Law VIII matters — *only projects are containers*. Anything
unclaimed by a project label is drift, and anything bound with no container at
all needs a human to say what it is.

---

## 6. Install Order — Why This Order

> **This list is a recipe, and a recipe is not a spec.** `hub/CONSTITUTION.md`
> §5: the recipe and the assertions *"must become one map"*, where every step
> ends in an assertion and every assertion names the step that satisfies it.
> Until they are one map, a step here can be true on paper and absent on the
> machine — which is exactly what happened to step 7.
>
> **The order below is the doctrine. Whether a given step happened is
> `bash bootstrap.sh --check`**, which derives what to expect from the
> installer's own heredocs rather than from this page, so it cannot drift from
> the installer the way this page drifted from it.

1. **System** — apt updates, UFW, Fail2Ban, timezone, static IP
2. **Docker** — everything else depends on this
3. **Hub** — clone `~/hub`, systemd user service, port 8765. Runs immediately so you have a dashboard while the rest installs.
4. **NPM** — creates the `proxy` Docker network. Must run before any other Docker service.
5. **Portainer** — Docker GUI
6. **Monitoring** — Homepage, Uptime Kuma, Netdata, Dozzle
7. **Backup** — set up before adding data
8. **Security** — Fail2Ban rules, SSH hardening
9. **CLI Tools** — helper scripts at `/usr/local/bin/`
10. **Extras** — n8n, Redis, SurrealDB, MinIO, etc. (user selects)
11. **Peer registration** — asks for existing hub URL, bidirectional handshake

**Critical:** NPM must start before any service that joins the `proxy` network.  
**Critical:** Hub installs right after Docker so you have visibility from minute 3 onward.

---

## 7. Adding a New Service — The Workflow

```bash
new-service add CATEGORY NAME [project-prefix]
```

Examples:
```bash
new-service add database surrealdb           # → /srv/docker/surrealdb/ port 8001
new-service add database redis keyknox       # → /srv/docker/keyknox-redis/ port 6380
new-service add automation n8n               # → /srv/docker/n8n/ port 5678
```

What it does automatically:
1. Identifies the lane from the category
2. Finds next free port in that lane
3. Creates `/srv/docker/NAME/docker-compose.yml` from template
4. Sets `container_name: NAME` in compose
5. Adds UFW rule for the port
6. Runs `docker compose up -d`
7. Hub discovers it on next refresh (dynamic — reads `docker ps`)
8. Logs to activity feed

---

## 8. Mesh — What Servers Know About Each Other

Each hub exposes:
- `GET /api/identity` — hostname, hub_url, LAN IP, Tailscale IP, server name
- `GET /api/status` — RAM, disk, uptime, load
- `GET /api/containers` — all running containers
- `GET /api/ports` — all bound ports
- `POST /api/peer/register` — bidirectional registration

**Peers are not listed here.** `curl -s <hub>/api/federation` and
`python3 hub/tools/situation.py` answer who is registered and who has been
heard from — and those are different questions: a DNS-sourced row means *this
server exists*; a heartbeat-sourced row means *this server is alive*. Collapsing
the two showed a dead box as healthy.

**Peers must be keyed on `machine_id`, never on a URL.** Keyed by URL, a moved
peer is a dead peer; keyed by machine-id, it has simply changed address. That is
Law X, and it was learned by having two hubs list each other and never connect.

**What the mesh is for:**
- Cross-server health monitoring (peer goes offline → ntfy alert)
- See what's running on another server from your hub
- One-command pairing at install time
- Foundation for: remote deploy, shared activity feed, HQ/node architecture

**What it is NOT yet:**
- Automatic failover
- Shared config sync
- Central deploy target (planned — HQ/node pairing)

---

## 9. Access Flavors

| Flavor | How | Use case |
|--------|-----|----------|
| LAN direct | `http://192.168.x.x:PORT` | At home, fastest |
| Tailscale | `http://100.x.x.x:PORT` | Remote, any device, encrypted |
| Cloudflare Tunnel | `https://hub.yourdomain.com` | Public URL, no port forwarding |
| CF + Access | Email OTP gate on CF URL | Secure public access |
| CF SSH proxy | `ssh user@ssh.yourdomain.com` | SSH over HTTPS, mobile-friendly |
| Two Tailscale accounts | Device on both accounts | Two separate orgs, one machine |
| Tailscale mesh | Multiple servers, one tailnet | All servers see each other |

---

## 10. Hub API surface, planned builds, CLI tools — all derived

Three hand-maintained tables stood here: an endpoint list, a numbered roadmap,
and a catalogue of CLI tools. Each was a record kept alongside the thing it
described, and each drifted. The endpoint table named routes that were never
built and omitted ones that were; the roadmap outlived its own priorities.

| What you wanted | What answers it |
|---|---|
| Every route, from the route table itself | `curl -s <hub>/api/sitemap` |
| Which routes declare a gate, and whether anything applies it | `python3 hub/tools/matrix.py`, sequence A |
| What is next, and what gates it | `python3 hub/tools/tracks.py` · `python3 hub/tools/step.py` |
| What is built vs hand-built vs phasing out | `python3 hub/tools/atlas.py` |
| Operator decisions nothing proceeds on by itself | `python3 hub/tools/atlas.py`, its closing section |
| Which CLI tools exist on a node | `ls /usr/local/bin/` on that node, and `python3 hub/tools/atlas.py --parts` for this repo's own |

**A tool nothing calls is a document with a shebang**, and an invoker column in
a document is the least reliable column of all: one script listed here as
"invoked by nothing" was `ExecStartPost=` in a **user** unit and had been firing
the fleet's wrongest alert on every restart. The audit that declared it dead had
read only `/etc/systemd/system`. Look in both unit paths — or better, do not
keep the column.
## 11. Key Decisions (Why We Did It This Way)

| Decision | Reason |
|----------|--------|
| Hub on 8765, not a container | Hub must survive Docker being down |
| Hub as user systemd service | Runs without root, auto-restarts |
| All services under /srv/docker/ | One place, consistent, backupable |
| Folder = container name | Makes CLI tools, Portainer, hub discovery all work with one name |
| Proxy network created by NPM | NPM must start first — it owns the network |
| ntfy on 8085 | Notifications lane, below 8090 (Dozzle) |
| Static IP at install | Server must always be at the same address |
| Tailscale SSH (--ssh flag) | Bypasses UFW, works with Tailscale identity |
| Dynamic container discovery | Hub reads docker ps — shows Nextcloud, anything else added manually |
| Bidirectional peer handshake | One POST registers both sides — no manual config on each server |

---

## 12. Repos

| Repo | URL | What |
|------|-----|------|
| claude-server | https://github.com/KGSHOPINV/claude-server | Hub app, API, dashboard |
| server-kit | https://github.com/KGSHOPINV/server-kit | Bootstrap installer, compose files |

**Rule:** Every code change commits and pushes immediately. No batching.

---

## 13. Never Do

- Never commit passwords, IPs, or secrets to GitHub
- Never run AI stack (Ollama/OpenWebUI) without a GPU
- Never restart/stop services without confirming
- Never assign port 8765 to a container
- Never use random container names — folder = name = law
- Never skip the port registry when adding a service
