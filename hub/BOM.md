# ServerHub — Bill of Materials

## There is no bill of materials in this file, and there must never be one

`hub/CONSTITUTION.md` §4 is explicit: **a BOM may never be prose.** *"The moment
a bill of materials is typed into a table, it is wrong and nobody knows."*

This file used to be 595 lines of exactly that — file counts, line counts, route
counts, per-module tables, tool inventories, a census of every document. It
opened by admitting the violation ("this file is prose under protest") and
predicting its own rot. The prediction was correct within a day: it named a
provenance commit and a file count that were both wrong before anyone read it,
and three separate route counts elsewhere in the repo were each measured against
it and each came out different.

It is kept as a file, rather than deleted, because the name means something and
because this is the shortest statement of why the rule exists.

---

## What a BOM is, and where it lives

| Artifact | Answers | Form | Where |
|---|---|---|---|
| **BOM** | what this machine *is* | **derived — never written by hand** | `GET /api/receipt` |
| **SOP** | how to do a thing repeatably | **executable — a script, not a step list** | `hub/tools/`, `bootstrap.sh` |
| **Blueprint** | why it is shaped this way | prose, unavoidably | `docs/` |
| **Knowledge** | what we learned the hard way | prose | `hub/KNOWLEDGE.md` |

Only the bottom two rows may be prose. They carry reasoning, and reasoning does
not execute — so they are kept **small and few**, because every page is a
surface that can quietly stop being true.

---

## The commands that answer what this file used to claim

Run them. Do not transcribe their output back into this file.

| Question this file used to answer | Command |
|---|---|
| What planes exist, and which are hand-built rather than installed? | `python3 hub/tools/atlas.py` |
| What are the parts — engines, modules, tools — and their codes? | `python3 hub/tools/atlas.py --parts` |
| Which telescope codes are taken, and which duplicated? | `python3 hub/tools/atlas.py --codes` |
| How many routes are there, and how many declare a gate? | `python3 hub/tools/edges.py` (it parses `ROUTES` and says so) |
| What external systems do we touch, and what binds each write? | `python3 hub/tools/edges.py` |
| Which step of the build order are we on? | `python3 hub/tools/step.py` |
| What do the checklists say today, against the machines? | `python3 hub/tools/matrix.py` |
| What is serving, what is exposed, what could I not see? | `python3 hub/tools/situation.py` |
| Is this node at the installer's standard? | `bash bootstrap.sh --check` |
| What is this machine, completely? | `curl -s <hub>/api/receipt` |
| What is actually listening? | `curl -s <hub>/api/ports` |
| Which routes exist, from the route table itself? | `curl -s <hub>/api/sitemap` |

Every one of those reads the machine or the tree at the moment you ask. None of
them can be stale, and each one ends by naming **what it could not see** — a
blind spot is not a pass.

---

## The three findings this file earned before it was drained

Kept because they are the evidence for the rule, not because they are current.

**Three copies of one number, all different (2026-09-24).** `router.py`,
`FABRIC.md` and this file each stated how many routes declared a gate. All three
disagreed with each other and all three disagreed with `ROUTES`. `UNISON-PLAN.md`
later added a fourth number, and `situation.py` a fifth. A number maintained in
prose beside the thing it describes is the drift this project exists to remove.

**A dead tool that was not dead (2026-09-24).** This file listed
`alert-startup.sh` under *"invoked by nothing"*. It was `ExecStartPost=` in
fks-services' **user** unit and had been firing the fleet's wrongest alert on
every restart. The audit that declared it dead had read only
`/etc/systemd/system`. **Look in both unit paths before writing "nothing" in an
invoker column** — and better, do not keep an invoker column.

**A second, drifting route table (2026-09-24).** `GET /api/sitemap` hand-
maintained its own list of paths alongside `ROUTES`. The drift was omission
only, which is the quiet direction: a project told about endpoints is never told
about the ones nobody remembered to add. `kernel.router.routes_by_module()`
exists as the seam for generating it.

---

## The rule, in one line

**If you want to add a fact to this document, add a check to a tool instead.**
