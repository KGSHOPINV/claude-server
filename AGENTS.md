# AGENTS.md — AI session entry point

> Read this first. Every AI session touching this repo should orient here before
> doing anything.

---

## The standing warning, and it is the whole file

**Every failure this project has found was a *record* disagreeing with the
*machine*, not a code bug.** An installer copying the app where its imports
failed. A unit pointing at a deleted file. Docs describing an already-split
monolith. A memory declaring a live server dead. Five separate files stating
five different route counts. A backup step documented for months and never
written.

So: **do not act on anything written in this repo without checking it against
the live system first.** Documents here carry doctrine — rules, boundaries,
decisions and their reasons. They deliberately carry **no counts, no status
ticks and no hostnames**, because those are the parts that rot.

`docs/flareshub-doctrine.md` §0 is the rule and the full command table.

---

## Orient by running things, not by reading things

| Question | Command |
|---|---|
| What is this system, and what is hand-built rather than installed? | `python3 hub/tools/atlas.py` |
| What are the parts, and their telescope codes? | `python3 hub/tools/atlas.py --parts` |
| Which step of the build order are we on? | `python3 hub/tools/step.py` |
| Which track is next, and what gates it? | `python3 hub/tools/tracks.py` |
| What do the five checklists say today, against the machines? | `python3 hub/tools/matrix.py` |
| What is serving, what is exposed, what could I not see? | `python3 hub/tools/situation.py` |
| What external systems do we touch, and what binds each write? | `python3 hub/tools/edges.py` |
| Is this node at the installer's standard? | `bash bootstrap.sh --check` |
| What routes exist? | `curl -s <hub>/api/sitemap` — generated from the route table |
| What is this machine? | `curl -s <hub>/api/receipt` |

Every instrument ends with **what it could not see**. A section skipped by a
flag registers as a blind spot. A clean report with a hole in it is more
dangerous than a failure, because nobody investigates a pass.

---

## Then read the doctrine, in this order

| File | What it gives you |
|------|-------------------|
| `hub/CONSTITUTION.md` | the laws: what ServerHub is, what it refuses, how its parts may relate |
| `docs/flareshub-doctrine.md` | FlareSHub specifically — the entry chain, the two consoles, the stateless UI, what "done" means |
| `hub/KNOWLEDGE.md` | what was learned the hard way, each with what it cost |
| `hub/FABRIC.md` | the seven dimensions a machine is described by |
| `docs/flareshub-blueprint.md` | why FlareSHub is shaped this way |
| `docs/flareshub-checklists.md` | the five sequences, and why each step earns its place |
| `hub/SERVER-COMMANDS.md` | the seven-command interface a project gets at admit |
| `hub/guides/remote-access.md` | the two-door auth model |
| `knowledge/decisions.sql` | architecture decisions with context and consequence |

---

## What this repo is

Two servers, one codebase. A Python **stdlib-only** HTTP server runs on each
node — no npm, no framework, no build step. Dependencies flow one way:

```
server.py  →  kernel/router.py  →  handlers/  →  kernel/
```

`server.py` is a bootstrap: HTTP shell, dispatch, threads. No route logic in it.
Routes are one dispatch table in `hub/kernel/router.py`. Handlers are one file
per domain and import `kernel/` only — **no handler imports `server.py`**, and
when they did, the split was cosmetic and nothing could be moved or deleted
independently.

Line counts and file inventories are not recorded here. `wc -l` them, or run
`atlas.py`. Two previous copies of those numbers in this file were wrong.

---

## Servers

Connection details — IPs, Tailscale addresses, SSH users, UUIDs — are in
`notes/secrets.env`, `knowledge/servers.json` and `CLAUDE.md`. **All three are
gitignored and none of them ships to a node.** They are not repeated here.

Which nodes exist and where each is reachable is answered by
`python3 hub/tools/situation.py` and `python3 hub/tools/atlas.py`, which read
the zone and the machines rather than a list.

---

## Security rules — always enforce

- Never commit passwords, IPs, or tokens
- `notes/secrets.env`, `knowledge/servers.json` and `CLAUDE.md` are gitignored —
  read them, never commit them
- `db/` is gitignored
- Every code change: commit and push immediately, no batching
- The AI stack stays **off** unless the operator explicitly asks
- Never assign port 8765 to a container
- **Confirm before restarting or stopping anything**
- **Never touch another project.** fksinv, babyhelp, keynox/metaforge,
  FlareVault: read to describe, never change. *"We stopped using it" is not "it
  is dead."* Check whose a thing is before removing it

---

## Three rules about writing in this repo

1. **Report, never repair.** Every instrument reports. None of them fixes
   anything. The operator decides. An instrument that repairs becomes a writer,
   and writers need owners.
2. **Derive, don't maintain.** A number that is typed is a number that will be
   wrong. If you want to add a fact to a document, add a check to a tool.
3. **One writer per fact.** A node is the only writer of its own state. Two
   writers for one fact is a split brain, and it is the failure this whole
   architecture is shaped to prevent.
