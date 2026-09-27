# ServerHub — Constitution

What this is, what it refuses to be, and how its parts are allowed to relate.

Short on purpose. Everything here is load-bearing; if a rule stops being true,
the thing stops being ServerHub.

---

## 1. What it is

> **A server that can explain itself — specifically, about itself, without you
> knowing what to ask.**

Not a dashboard. A dashboard shows numbers to someone who already knows which
numbers matter. Every defect found in September 2026 was a number being shown
and meaning nothing: `98G` on a machine carrying 557G, 40GB of cache nobody
reclaimed, a backup step documented and never written.

ServerHub has two halves and they are not the same job:

| | |
|---|---|
| **Install** | turn a bare machine into a *known* machine |
| **Post-install** | keep telling the truth about it, forever after |

Most tools do the first and stop. The second is where servers actually fail,
because failures there are silent and delayed.

---

## 2. The laws

**I. Derive, do not maintain.**
A record kept alongside a machine drifts away from it. Read the machine. Every
failure in September 2026 was a record disagreeing with reality — an installer
copying an app where its imports failed, a unit pointing at a deleted file, a
port band contradicting another port band, docs naming a mount point that does
not exist.

**II. Assert, do not describe.**
Prose has no failure mode. `MASTER.md` said *"7. Backup — set up before adding
data"* and could not be wrong, because nothing executed it — so a server ran
without backups for months while the document looked correct. Anything that
must stay true gets an assertion that can fail. Everything else is commentary.

**III. Intent beats inference.**
When the operator has already answered a question, read the answer. A 4.4TB
disk mounted at `/backup` is a declaration; nominating it for live data because
it is the largest mount is the machine overruling a human who was right.

**IV. Report, never repair.**
Every finding carries the command that fixes it. Nothing runs that command on
its own. A tool that silently repartitions a server is a worse outcome than a
full disk.

**V. Credentials are never here.**
Pointers only. The node holds no key and creates no hostname. That belongs to
the authority, which is the only layer outside the blast radius.

**VI. Isolation is provable, not promised.**
`docker ps --filter label=com.ksg.project=X` returns every container a project
owns and nothing else. If deleting a project's directory and containers
disturbs anything else, it was never isolated. No reviewer required.

---

## 3. What it owns, and what it refuses

| Owns | Delegates |
|------|-----------|
| its machine-id, disks, ports, containers, activity | credentials, DNS, tunnels → **FlareVault** |
| what a project may bind, write, and name | tenancy, provisioning → **Metaforge** |
| whether this node is finished | one address for many nodes → **FlareSHub** |
| the truth about *what is* | any opinion about *what should be* |

That last row is the seam. **Intent lives with the authority; the node reports
only what is.** When the two disagree, that is drift — and drift you can see is
the entire point.

---

## 4. The four artifacts, and which are allowed to be prose

This is the part that went wrong, so it is stated explicitly.

| Artifact | Answers | Form | Where |
|---|---|---|---|
| **BOM** | what this machine *is* | **derived** — never written by hand | `/api/receipt` |
| **SOP** | how to do a thing repeatably | **executable** — a script, not a step list | `tools/`, `bootstrap.sh` |
| **Blueprint** | why it is shaped this way | prose, unavoidably | `docs/` |
| **Knowledge** | what we learned the hard way | prose | `docs/`, decisions |

**The rule: BOM and SOP may never be prose.** The moment a bill of materials is
typed into a table, it is wrong and nobody knows. The moment a procedure is a
numbered list in a document, a step gets skipped and nothing notices.

Blueprint and knowledge are prose because they must be — they carry reasoning,
and reasoning does not execute. So they are kept **small and few**, because
every page is a surface that can quietly stop being true. This document is one
such surface.

---

## 5. Install and post-install are one map, two halves

A finished node is not "the install script exited zero". It is a set of
statements that are true, checkable at any moment, on any node:

```
python3 tools/install-preflight.py
```

The recipe (what to install, in order) and the spec (what must be true) are
currently two lists that barely overlap — 11 steps in `MASTER.md`, 8 assertions
in the preflight, 2 in common. **They must become one map**, where every recipe
step ends in an assertion and every assertion names the step that satisfies it.

The installer therefore **converges rather than installs**: run it on a bare box
and it is an install; run it on a live one and it brings the node to standard,
skipping what is already true. "Did step 7 happen?" stops being a memory
question.

---

## 6. Separation of repositories

`bootstrap.sh` currently clones the workspace repo onto every node, which ships
`CLAUDE.md` — containing both servers' addresses and SSH usernames — along with
session notes, issues and a local database, to every machine that installs.

Separation follows the layers, not convenience:

| Repo | Holds | Ships to a node |
|---|---|---|
| **serverhub** | the product: `hub/`, `tools/`, `bootstrap.sh`, this file | **yes** |
| **workspace** (current `claude-server`) | notes, session logs, `CLAUDE.md`, issues | **never** |
| **FV-MF-SH-integrations** | contracts between the three systems | no — read by all |

The test: *could a stranger install this without receiving anything personal?*
Today the answer is no.

---

## 7. What a project is owed on arrival

A project should never have to learn the server. It asks once:

```
GET /api/admit?project=<name>
```

and is told the ports it may bind, the labels it must carry, where its database
goes, where its media goes, what is forbidden, and a runnable test proving it
complied.

**babyhelp is the case this exists for.** It was built by someone who knew
nothing about this machine, and there was nothing to ask. It works — and it is
invisible: no `com.ksg.*` labels, so the acceptance test returns **0 of its 3
containers**; data in an opaque named volume on the OS disk; a published port
outside any assigned band; no compose file on the host.

Nothing about that is the builder's fault. There was no endpoint to ask, and
no answer if there had been.

---

## 8. The one-sentence version

**ServerHub turns "I have a server and I hope it's fine" into "here are the
things that must be true, here is which ones are, and here is the command for
the rest."**

Everything else — the mesh, one Cloudflare entry, the temperature map — is that
sentence at fleet scale instead of one machine.
