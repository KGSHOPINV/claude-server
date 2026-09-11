# Hub Refactor Plan

> Migration from monolith to kernel architecture. Zero downtime. One phase at a time.

---

## Current state (as of 2026-09-09)

### server.py — 3,119 lines
- No kernel class. 5 scattered primitives: `db_conn`, `check_auth`, `gate_check`, `ssh_run`, `log_activity`
- Route dispatch: flat if/elif chain. ~35 GET branches, ~25 POST branches
- Auth is opt-in per route — not enforced globally
- DB layer: ~60% extracted into helpers, ~40% inline SQL inside handlers
- Modularity scores: Add API endpoint **2/10**, Add UI view **4/10**, Swap DB **2/10**

### app.html — 6,518 lines (5,250 JS)
- View system: `mountPaneContent()` is a ~300-line `switch(viewType)` block
- Global state: `const S = {}` mutated directly everywhere
- Adding a new view requires touching 4 separate places
- What IS modular: workspace system, pane system, individual view loaders

---

## Target layout

```
hub/
  kernel/
    db.py       — all DB access, one place, no inline SQL anywhere else
    auth.py     — enforced on every request at router level
    router.py   — dispatch table, not elif chain
    ssh.py      — server bridge + cache
    log.py      — activity log, ntfy push, Docker event watcher
  handlers/
    status.py   — /api/status, /api/containers, /api/ports
    config.py   — /api/config, /api/users, /api/vault
    federation.py — /api/federation, /api/peer/register
    ai.py       — /api/ai_chat, /api/ai_system_prompt
    events.py   — /api/incidents, /api/journal
    auth.py     — /api/auth, /api/login, /api/totp
    proxy.py    — /api/proxy_fetch, /api/cutsheet
  server.py     — thin bootstrap: init kernel, register handlers, start server
ui/
  state.js          — centralized state manager (replaces S = {} global)
  view-registry.js  — single registration point (replaces 4 scattered lists)
  workspace.js      — already clean, minor cleanup only
  views/
    dashboard.js
    network.js
    containers.js
    federation.js
    incidents.js
    [one file per view]
```

---

## Migration phases

### Phase 0 — Freeze & Map — COMPLETE
**No code changes.** Create the knowledge layer.

Deliverables:
- [x] `AGENTS.md` — AI session entry point
- [x] `docs/refactor-plan.md` — this file
- [x] `knowledge/registry.json` — machine-readable manifest
- [x] `knowledge/decisions.sql` — architecture decisions
- [x] `knowledge/servers.json` — device UUIDs (from /etc/machine-id)

**Rule:** Phase 1 does not start until registry.json is correct and both server UUIDs are populated.

---

### Phase 1 — Kernel Extraction — COMPLETE (merged, PR #9)
**Identical behavior. Zero new features.**

Extract the 5 kernel primitives from server.py into separate modules.
server.py imports from them — behavior unchanged.

Moves:
- `db_conn()` + all DB helpers → `hub/kernel/db.py`
- `check_auth()` + `gate_check()` → `hub/kernel/auth.py`
- `ssh_run()` + SSH caches → `hub/kernel/ssh.py`
- `log_activity()` + ntfy + Docker watcher → `hub/kernel/log.py`
- if/elif dispatch → `hub/kernel/router.py` (dispatch table)

**Rule:** Auth is now enforced at router level. No handler can skip it.
Every route declares its required gate level in the dispatch table.

Ship this as: branch `refactor/phase-1-kernel`, PR to master, verify all endpoints respond identically.

---

### Phase 2 — Handler Split — COMPLETE (branch refactor/phase-2)
**Identical behavior. server.py becomes a bootstrap.**

Split the 60-branch elif chain into domain handler files.
Each handler imports only from `kernel/`. No handler imports another handler.

Migrate one domain at a time, ship each separately:
1. `handlers/status.py` — GET /api/status, /api/containers, /api/ports
2. `handlers/events.py` — GET/POST /api/incidents, /api/journal
3. `handlers/federation.py` — GET/POST /api/federation, /api/peer/register
4. `handlers/config.py` — GET/POST /api/config, /api/users, /api/vault
5. `handlers/ai.py` — POST /api/ai_chat
6. `handlers/auth.py` — GET/POST /api/auth, /api/login
7. `handlers/proxy.py` — remaining routes

**Rule:** Handler file may only import from `kernel/`. No inline SQL — all DB via `kernel/db.py`.

---

### Phase 3 — UI Modularization — NEXT
**app.html stays as the entry point. Script block moves to modules.**

- `S = {}` global → `hub/ui/state.js` with get/set/subscribe
- `VIEW_DEFS` + `mountPaneContent switch` + openView dicts + buildCmdIndex → `hub/ui/view-registry.js`
- Each view function → `hub/ui/views/<name>.js`
- app.html loads these as ES modules or bundled via esbuild

**Rule:** Adding a new view = one file + one entry in view-registry.js. Nothing else changes.

---

### Phase 4 — MCP Layer (FV milestone)
**Built on clean kernel. This is what makes agentic editing safe.**

- FV MCP server connects to hub kernel directly (no HTTP round-trips)
- MCP tools: `query_mesh()`, `get_status()`, `deploy_update()`, `get_context()`
- Every AI session connects to FV, gets tools, calls clean kernel functions
- ISO generator: FV produces per-node Ubuntu autoinstall ISOs

**Rule:** MCP tools only call `kernel/` functions. Never raw SSH. Never inline SQL.

---

## Migration rules (all phases)

1. Each phase ships on its own branch and PR — never mix phases in one commit
2. Behavior must be identical before and after each phase — no features
3. Tests (even manual curl tests) run before merging any phase PR
4. registry.json updates with every structural change
5. decisions.sql gets a new row for every meaningful architectural choice

---

## What the registry covers

The registry (`knowledge/registry.json`) is NOT just the hub kernel.
It covers everything:
- **servers** — UUID as primary key (survives hostname/IP change)
- **files** — every significant file, its purpose, phase, and refactor status
- **services** — all Docker containers on all servers, desired vs actual state

The kernel reads and writes the registry. FV is the authority that keeps it current.

---

## Phase 2 as actually built

The plan assumed handlers would be self-contained once split. They were not:
`status.py` imported server.py back 19 times, `identity.py` twice, `ai.py` once —
22 lazy `import server as _srv` calls into 22 module-level helpers, making
server.py a dependency of its own handlers.

Fixed by adding `kernel/collect.py` (not in the original plan): the 1,888-line
collector region moved out of server.py. Handlers now import `kernel.collect`.
server.py went 2,890 -> 122 lines.

Verified against production on fks-services: 41 GET routes status-identical,
14 endpoints byte-identical against a copy of the live DB.

---

*Last updated: 2026-09-10*
