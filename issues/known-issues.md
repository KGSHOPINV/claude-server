# Known Issues — SUPERSEDED 2026-09-23

> **This file is not the issue tracker and never was reachable from the product.**
> `GET /api/issues` reads the `issues` table in `hub/db/server.db`
> (`hub/handlers/config.py::get_issues`). It has never read this Markdown file.
> Anything written here was invisible to the hub UI, to the API, and to every
> other node.

## Where issues live now

| Want | Use |
|---|---|
| The tracked issue list | `GET /api/issues` (SQLite `issues` table) |
| Incidents raised by the hub | `GET /api/incidents`, `POST /api/incidents` |
| What is known-missing by design | `AGENTS.md` "Things NOT YET BUILT", `TASKS.md` |
| Whether a service is actually down | `GET /api/receipt` → `sync_issues` |

## Why the old contents were removed rather than migrated

The six OPEN items dated 2026-07-31 were two months stale and contradicted by
`MASTER.md` §5 on every point that could still be checked: "Dozzle not running"
and "18 services DOWN / most of stack not installed" are both recorded as
running there, and ntfy on 8085 is now a first-class entry in the `SERVICES`
catalogue in `hub/kernel/collect.py`. The load-average note was a single reading
taken during one session. None of it was worth copying into the database.

**One item is carried forward because it is unverified, not because it is true:**
the 2026-07-31 note claimed the server's real Docker aliases are `dps` / `dlogs`
/ `dcu` / `dcd` / `dcr`, not the `dkps` / `dklogs` / `dkrestart` names used in
`CLAUDE.md`, `MASTER.md` §12 and `SYSTEM.md`. That claim cannot be settled from
the repo — three documents disagree with it. Settle it on the node
(`type dkps; type dps`) and fix whichever side is wrong; do not assume either.

The two RESOLVED entries (Fail2Ban ban on the work PC, missing SSH key, both
2026-07-31) were fixed and needed no record here.
