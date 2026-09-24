# Server Installation Map — SUPERSEDED 2026-09-23

> **This file no longer describes any machine. Do not use it for port or service facts.**
> It was a hand-written snapshot of one install run, taken 2026-07-31, and was
> never updated afterwards. Nothing in the repo read it: no script, no handler,
> no other document referenced `installation-map.md`.

## Why it was retired

It was a **second, contradictory port registry**. Its "What's NOT Installed"
table assigned SurrealDB `8181`, Wiki.js `3003`, Adminer `8083` and Grafana
`3002` — Grafana colliding with the port Wiki.js holds everywhere else. The live
catalogue (`SERVICES` in `hub/kernel/collect.py`) and `PORTS.md` both say
SurrealDB **8001**, Wiki.js **3002**, Adminer **8082**. A session that read this
file first got the wrong number with no way to know it was wrong.

`hub/CONSTITUTION.md` §4 — *a bill of materials may never be prose*. This file
was prose pretending to be a BOM.

## Where the same answers come from now

| Question | Ask this instead |
|---|---|
| What is installed and running right now | `GET /api/receipt` |
| Every known service + live Docker state | `GET /api/services` |
| What is listening on which port | `GET /api/ports` |
| Which port a *new* service may claim | `PORTS.md` (lane law), `MASTER.md` §2 |
| What the installer actually does | `bootstrap.sh`, `enroll.sh` |
| What is known-missing | `AGENTS.md` "Things NOT YET BUILT", `TASKS.md` |

The open questions this file ended with — unknown process on 8080, Cloudflare
tunnel status, whether `gh` is installed — are all answerable from `/api/ports`
and `/api/status` on the node itself. That is where they should be asked, not
recorded in a file that ages silently.
