# THE UNISON MANAGEMENT PLAN

**Provenance.** Working tree `af9ba09`, branch `fix/project-port-band`, `C:/Dropbox/Files PC Warehouse/claude-server` (= `~/hub` on both servers), derived 2026-09-24. Local repo facts in this document were re-derived in this pass and every correction is listed in Part VII. Server-side facts — HTTP probe results, systemd timers, database row counts — are carried from the last probe (2026-09-24 16:45) and were **not** re-run here; they are marked as such where they matter.

---

## 0. Opening

The premise is one sentence: **the server is the only wire.** A project never talks to the hub, and the hub never talks to a project. Both talk to the server, and the server keeps the record. The only unautomated link is the operator, who points a project at its server out loud. That is deliberate — a trigger that fires itself is a poll, and polling is ruled out.

There are two servers running the same codebase from the same repo. **ksgcohub** (`100.107.234.9`, personal/home, `/srv/data`) and **fks-services** (`100.75.1.105`, 216GB RAM, `/backup` 4.4TB). They are on split tailnets and cannot reach each other; the operator is currently the only link between them. Congruence between them means *the same code ref and the same assertions passing* — never the same values. Different disks must produce different numbers, and that is the system working.

Four projects exist as running apps: `fksinv` and `babyhelp` on ksgcohub, `metaforge` and `flarevault` on fks-services. **Zero are registered, zero have acknowledged anything, zero are aware of any of this.**

**This document supersedes the earlier plan documents in this repo** — `hub/plan/THE-PLAN.md`, `hub/BOM.md`, and the architectural prose in `hub/FABRIC.md`, `hub/KNOWLEDGE.md` and `hub/CONSTITUTION.md` where they disagree with it. `hub/BOM.md` in particular is falsified: it names provenance `db07c5e` and claims 113 files / 25,472 lines against an actual 187 files. Where a number here disagrees with a repo document, the number here was re-derived from the tree and the stale source is named in Part VII.

Nothing below is new design. Where a section previously overstated what exists, it has been fixed **down**.

---

## Status legend — used on every box, table and edge in this document

| Mark | Meaning |
|---|---|
| **LIVE** | Deployed and answering on at least one server today |
| **CODE-ONLY** | Exists in `hub/` on branch `fix/project-port-band`, not deployed, not routed, or deployed on one box only |
| **DESIGN** | Prose in the repo with nothing executable behind it |

```
A ══> B    LIVE          A ──> B   CODE-ONLY        A ┄┄> B   DESIGN
[n]        times this edge has been traversed in production
{owner}    the ONE component that owns this edge. Two owners on one edge is the bug.
```

A **vector** is `(actor, verb, object, transport, owner, state)`. No edge is owned twice; no owner holds two verbs.

---

# PART I — SYSTEM ARCHITECTURE

## I.1 Three parties, one medium

```
              ┌──────────┐
              │ OPERATOR │  the only party that is not software
              └────┬─────┘
                   │ "go talk to your server" — spoken, never a wire  ┄┄> [0]
                   ▼
 ┌────────────────────────┐                   ┌──────────────────────┐
 │ PROJECT                │                   │ HUB  (this session)  │
 │ fksinv · babyhelp      │                   │ reads what projects  │
 │ metaforge · flarevault │                   │ left, publishes next │
 │ LIVE as apps           │                   │ LIVE                 │
 │ 0 of 4 registered      │                   │ SSH + same HTTP API  │
 └───────────┬────────────┘                   └──────────┬───────────┘
             │ GET  /api/admit?project=<p>     LIVE      │
             │ GET  /api/registry/<p>          LIVE      │
             │ POST /api/registry/<p>  (claim) LIVE      │
             │ POST /api/ack/<p>               LIVE      │
             │ POST /api/registry/<p>/verify   CODE-ONLY │
             ▼                                           ▼
 ╔═══════════════════════════════════════════════════════════════════╗
 ║  SERVER :8765  — the medium. hub/server.py + kernel/router.py     ║
 ║  77 routes · 13 handler modules · db/control.db                   ║
 ║  {projects, acks, releases, diffs}                                ║
 ╚═══════════════════════════════════════════════════════════════════╝
             └────── X  no edge PROJECT ── HUB. Forbidden. ──────┘
```

There are exactly **three** vectors at this level and one of them is speech. The `PROJECT ↔ HUB` non-edge is the whole mechanism: `KNOWLEDGE.md` records it was violated once by messaging a project session directly, and that is logged as an **error**, not a shortcut. A UI control that messaged a project directly would be the same defect.

`hub/SERVER-COMMANDS.md` — the file a project saves in its own repo — names seven commands. This is the only surface a project is ever told about; six modules' worth of routes exist that a project never sees. The seven, and whether they resolve, are in Part III.

## I.2 Two servers, one build

```
              IDENTICAL — congruence is THIS column matching
  ┌──────────────────────────────────────────────────────────────┐
  │ code ref (git HEAD)   router.py 77 routes   11 kernel modules │
  │ port lane 12000-18999 · 100/project · fleet-wide  CODE-ONLY   │
  │ /api/node /api/admit /api/receipt /api/registry /api/ack      │
  │ hub on :8765 · tools/{install,storage}-preflight, backup.sh   │
  └──────────────────────────────────────────────────────────────┘
        ▲ same repo, same installer                      ▲
 ┌──────┴────────────────────────┐   ┌───────────────────┴──────────────┐
 │ ksgcohub               LIVE   │   │ fks-services              LIVE   │
 │ 192.168.50.100 / 100.107.234.9│   │ 192.168.1.229 / 100.75.1.105     │
 │ 98GB OS + 458GB /srv/data     │   │ 1TB OS + 4.4TB /backup           │
 │ 7GB RAM                       │   │ 216GB RAM                        │
 │ data root → /srv/data         │   │ data root → /srv/docker          │
 │ fksinv · babyhelp             │   │ metaforge (keynox, 18 ctr)       │
 │                               │   │ flarevault-node :7777  ← AUTHORITY│
 │ ref 3d89b9c · 2 behind HEAD   │   │ ref ab02c2f · 62 behind HEAD     │
 │ registry LIVE                 │   │ no registry · no /api/node       │
 │ band 7100-7899 DEPLOYED       │   │ no ~/.flare identity file        │
 │ backups daily, unattended     │   │ partial backups, 21 vols exposed │
 │ 8 of 10 preflight             │   │ preflight tool absent            │
 │ tunnel: hub.ksgco.app         │   │ no tunnel at all                 │
 └───────────────────────────────┘   └──────────────────────────────────┘
```

**Values differ because disks differ; that is the system working.** `hub/tools/fleet-status.py` states the rule: `congruent = same code ref + both pass the same assertions ≠ same values`. A disagreeing `data root` column is correct. A disagreeing `ref` column is drift — and today it disagrees, on both boxes, plus 1,869 uncommitted lines that are on neither.

```
                        af9ba09  (working tree, +1,869 / −20 on 5 files)
                           │
                     2 commits
                           │
                        3d89b9c  ksgcohub / deploy   ← the only node with a registry
                           │
                    60 commits
                           │
                        ab02c2f  fks-services / master  ← holds FlareVault + Metaforge
```

`git rev-list --count master..HEAD` = **33** (against origin/master; an earlier draft read 73 from a stale local master ref). The 8-commits-behind figure that appeared in an earlier draft is withdrawn; it cannot be reproduced.

## I.3 Three layers, one owner each

```
 ┌─ ENTRY ────────────────────────────────────────────── DESIGN ─┐
 │ FlareSHub — one domain, one session, bilateral frontend       │
 │ owns: the browser's single origin                             │
 │ docs/flareshub-blueprint.md. Zero code. enroll.sh takes       │
 │ --zone every run, which violates one-entry by itself.         │
 └────────────────────────┬──────────────────────────────────────┘
                          │  aggregates N nodes (unbuilt)
 ┌─ NODE ─────────────────┴──────────────────────────────── LIVE ┐
 │ ServerHub — hub/ on :8765, on BOTH boxes                      │
 │ owns: machine-id, disks, ports, containers, activity          │
 │ refuses: credentials, DNS, hostnames (/api/vault/* is a       │
 │          reserved prefix, deliberately unimplemented)         │
 └────────────────────────┬──────────────────────────────────────┘
                          │  pointers up; keys never come down
 ┌─ AUTHORITY ────────────┴─────────── RUNNING, NOT INTEGRATED ──┐
 │ FlareVault — container on fks-services :7777 since 2026-07-27 │
 │ owns: credentials, DNS, tunnels, the trust root, server_id    │
 │ reality: mints nothing. kernel/identity.py derives fvn_<sha6> │
 │ locally and issues HS256 itself (jwt_issuer: self).           │
 │ fks-services has no ~/.flare/server.identity.json at all.     │
 └───────────────────────────────────────────────────────────────┘
```

Authority is a container that is up, not a layer that is wired. The handshake shape is agreed (`kernel/identity.py` docstring, 2026-09-22); nothing crosses it.

## I.4 The tailnet split — what it blocks, what it does not

Verified 2026-09-11 (`docs/session-log-2026-09.md`). Both nodes are healthy; they are on different networks.

```
  tailnet  kyle@ (tail912c87)     ║     tailnet  ksg.co.hub@ (tail4142b4)
  ┌──────────────────────┐        ║     ┌──────────────────┐ ┌──────────┐
  │ fks-services         │        ║     │ ksgcohub         │ │ work PC  │
  │ 100.75.1.105 :8765   │   ╳╳   ║     │ 100.107.234.9    │ │ phone    │
  │ metaforge·flarevault │        ║     │ fksinv·babyhelp  │ │ laptop   │
  └──────────────────────┘        ║     └──────────────────┘ └──────────┘
        peer entry: http://100.107.234.9:8765 — correct address,
        unreachable network. Both boxes already list each other.

  BLOCKED                          NOT BLOCKED
  ─ cross-server backup            ─ each box backs up to its own device
    (4.4TB /backup cannot hold       (Continuity's rule is *different physical
     ksgcohub's 458GB, and             device*, not *different box*)
     vice versa)                    ─ /api/admit, registry, ack: per-server by
  ─ /api/heartbeat node→central       construction, never cross-server
  ─ /api/mesh/fleet as one view    ─ operator reaches BOTH from this PC — one
  ─ /api/peer/register federation     over each path. The operator is the only
  ─ Stage 3 cross-server regards      current link between them.
```

Fix is one command on fks-services (`sudo tailscale up --force-reauth`, `TASKS.md`), needs sudo at the box. Nothing in the two-server design depends on the link: `handlers/registry.py` states cross-server arrives free later *because* the heartbeat carries a node's payload to central — no box ever reaches the other's network.

## I.5 Decomposition — one owner per thing

No component does two jobs. Where two exist for one question, that is named as the defect.

| Thing | Sole owner | Status |
|---|---|---|
| Route table + gate level | `hub/kernel/router.py` `ROUTES` | LIVE (enforcement OFF) |
| Machine identity, HS256 | `hub/kernel/identity.py` | LIVE |
| Disks, data root, backup target | `hub/kernel/storage.py` | LIVE |
| Live substrate read (ports, docker) | `hub/kernel/collect.py` | LIVE |
| Port lane constants | `collect.py:62-82` | CODE-ONLY (12000-18999) |
| Project claims / acks / releases / diffs | `hub/kernel/control.py` → `db/control.db` | LIVE on ksgcohub, 0 rows |
| Project-facing endpoints | `hub/handlers/registry.py` (module 13) | LIVE on ksgcohub |
| Verify / diffs / dispose | `hub/handlers/registry.py` | CODE-ONLY, **uncommitted and unrouted** |
| Admission (band, paths, labels) | `hub/handlers/node.py` `get_admit` | LIVE on ksgcohub |
| Node→central heartbeat | `hub/kernel/heartbeat.py` | LIVE, no central reachable |
| Two-server congruence check | `hub/tools/fleet-status.py` | CODE-ONLY, no caller |
| Bulletins, PIN, the four rungs | — **nothing owns this** | DESIGN |
| Tickets | — **nothing owns this** | DESIGN |

**Known two-owner defects** (detail in Part IV): `/api/sitemap` hand-maintains a second route list beside `ROUTES`; `/api/receipt`, `/api/context`, `/cutsheet` and `/api/status` are four shapes of one question; `kernel/collect.py:338` carries 18 hardcoded services, making every `keynox-*` container on its own machine a `'Discovered'` stub; and two independent readers of the disks are live simultaneously.

---

# PART II — FLOW DAGs AND VECTORS

## II.1 The ladder — a gated chain, not a fan-out

```
                 ┌──────────────────────────────────────────┐
   rung 1        │ "You are already in this server."        │
   BASELINE      │ what the machine sees of you:            │
                 │ containers · ports · data · compose ·    │
                 │ labels — or that you have none           │
                 └───────────────┬──────────────────────────┘
                                 │ readout carries PIN₁
                                 ▼
                        ┌────────────────┐
                        │  ack(1, PIN₁)  │  ┄┄> [0] {DESIGN}
                        └────────┬───────┘
                                 │  ── GATE ──  no PIN₁, rung 2 not served
                                 ▼
                 ┌──────────────────────────────────────────┐
   rung 2        │ "Here is where this server is going."    │
   DIRECTION     │ roadmap · restructuring · band moves     │
                 └───────────────┬──────────────────────────┘
                                 │ PIN₂  → ack(2) ── GATE ──
                                 ▼
                 ┌──────────────────────────────────────────┐
   rung 3        │ "Here is what that means for you."       │
   CONSEQUENCE   │ your diffs, each with a disposition:     │
                 │   fix · accept · defer · hub-wrong       │
                 └───────────────┬──────────────────────────┘
                                 │ PIN₃  → agree(3)
                                 ▼
                 ┌──────────────────────────────────────────┐
   rung 4        │ MAINTAINED                               │
   STANDING      │ bulletins against a standing agreement   │
                 └───────────────┬──────────────────────────┘
                                 └──> re-enters at §II.5 (bulletin),
                                      never at rung 1
```

**Why the gate exists.** Rung 2 says a value is *changing*. "Changing" is a delta, and a delta needs a left operand. A project that has not confirmed rung 1 has no left operand — it is being told a number moved from something it never agreed it held. It cannot evaluate the change; it can only nod. That nod is indistinguishable from a skim, and a skim is what the PIN exists to make impossible.

This is not theory. `STATE.md`, "What I got wrong", item 1: the port band was deployed to ksgcohub with the ack list empty — rung 2 served to projects standing on no rung at all. `KNOWLEDGE.md` calls that inversion "the single most expensive mistake in this repo's history."

**Gate direction is one-way and monotone.** Rungs never revoke. A project at rung 4 that ignores a bulletin does not fall to rung 3; it becomes *stale* (§II.5), which is a marker, not a demotion.

### What is actually built

| Rung | Vector | Transport | Owner | State |
|---|---|---|---|---|
| 1 readout | SERVER → PROJECT | `GET /api/admit` `20311702` + `GET /api/receipt` `20302713` | `handlers/node.py`, `handlers/status.py` | **LIVE** ksgcohub [0] |
| 1 ack | PROJECT → SERVER | `POST /api/ack/<project>` `20313704` | `handlers/registry.py:149` | **LIVE** ksgcohub [0] |
| — ack storage | SERVER → disk | `acks(project, ref, answer, at)` append-only | `kernel/control.py:65` | **LIVE**, 0 rows |
| — gate enforcement | — | — | — | **DESIGN**. 59 of 77 routes *declare* a gate, none apply it |
| 2, 3 | — | — | — | **DESIGN**. No rung concept in code |
| PIN | — | — | — | **DESIGN**. `grep -rniE "\bpin\b" hub/kernel/*.py hub/handlers/*.py` → **zero hits** |

**The substitution that is live today.** `acknowledge()` (`control.py:130`) keys on `ref` — the server's git master ref — not a PIN. It proves *which code the project was told about*, not *that the project read anything*. It is the right column with the wrong contents: one field change from carrying a PIN, and that field change is the smallest real step on this whole graph.

**And the staged-change notice is broken in both directions.** `_pending()` (`handlers/registry.py:180`) is gated on `PROJECT_BAND_FLOOR == 7100`:

- ksgcohub deploys `3d89b9c`, where the floor **is** 7100 — so it announces a pending change *it has already completed* (`10020-10990 → 7100-7899`).
- HEAD and the working tree are at 12000, where the branch never fires — so the move to `12000-18999` is announced **nowhere**.

The only staged-change notice a project could ever receive is either stale or unreachable. Verified: `git show 3d89b9c:hub/kernel/collect.py` → `7100`; `af9ba09` → `12000`.

## II.2 Two entry paths — allocation vs alignment

Same ladder, two distinct pre-ladder subgraphs. Choosing wrong is not a style error; it produces a false report.

```
                      ┌───────────────────────┐
                      │ does it run anything  │
                      │ on this host today?   │
                      └───────┬───────┬───────┘
                       no     │       │    yes
              ┌───────────────┘       └───────────────┐
              ▼                                       ▼
   ══ A. ALLOCATION (new) ══              ══ B. ALIGNMENT (existing) ══
   the project needs a SHAPE              the project needs a RECONCILIATION
   before it has a body                   of a body that already exists

   A1 claim a name                        B1 "you are already here"
      unique FLEET-WIDE                      machine-read: containers, ports,
      {control.register()}                   data, compose, labels
      │                                      {kernel/collect.py}
      ▼                                      ▼
   A2 receive a band                      B2 the floor
      100 ports, reserved BEFORE             12 lanes · every bound port ·
      deploy. collect.py:1001 scans          every neighbour · disks · what
      12000-18999 step 100 for a             is backed up
      band with 0 bound ports                │
      │                                      ▼
      ▼                                   B3 its band, OFFERED
   A3 receive paths                          migration, not cutover.
      /srv/data/<name>/{db,media,            "Outgrowing 100 is a ticket,
      cache,releases,public,private}         not a violation."
      │                                      │
      ▼                                      ▼
   A4 receive rules                       B4 its claim
      labels · naming · network ·            the half only it knows
      forbidden · acceptance test            │
      │                                      ▼
      ▼                                   B5 the diffs
   A5 receive the floor                      each carrying a disposition:
      the 12-lane map BEFORE its             fix · accept · defer · hub-wrong
      position on it                         {control.record_diffs():490,
      │                                       control.dispose():513}
      ▼                                      │
   A6 build to it  (nothing enforced)        │
      │                                      │
      ▼                                      │
   A7 deploy ──> THEN verify                 │
      │                                      │
      ▼                                      ▼
   A8 file its claim                      B6 ── converge ──
      └──────────────┬───────────────────────┘
                     ▼
              rung 1 ack  →  THE LADDER (§II.1)
```

**Why the split is load-bearing.** Verification is a comparison. Run it against a project with nothing deployed and every container is "missing", every port "unbound", every path "absent" — a clean page of red that reads as total failure when the true state is *not yet built*. `KNOWLEDGE.md`: "Verifying a project that does not exist reports every container missing and reads as total failure."

The inverse error is symmetric: hand an existing project an allocation and it is told to take ports it is already sitting next to, with no acknowledgement that it holds different ones.

**Terminal state differs, and this is the part most often got wrong:**

```
ALLOCATION  terminal = COMPLIANT     built to the shape it was given
ALIGNMENT   terminal = RECONCILED    every difference has a disposition

RECONCILED ≠ IDENTICAL. Four accepted deviations is fully reconciled.
An UNDECLARED deviation is the only failure state.
```

| Path | Endpoint / file | State |
|---|---|---|
| A2 band scan | `collect.py:1001-1004`, `FLOOR=12000`, `CEIL=18999`, `SIZE=100` | **CODE-ONLY** — unmerged. ksgcohub serves 7100-7899 |
| A3/A4 rules | `GET /api/admit` `20311702` | **LIVE** ksgcohub [0] |
| A8 / B4 claim | `POST /api/registry/<p>` `20313703` | **LIVE** ksgcohub [0] |
| A7 / B5 verify | `POST …/verify` — dispatched at `registry.py:125`, no router row | **CODE-ONLY, uncommitted** |
| B5 dispose | `POST …/dispose` — `registry.py:128` | **CODE-ONLY, uncommitted** |
| B5 read diffs | `GET …/diffs` — `registry.py:103` | **CODE-ONLY, uncommitted** |
| A1 name uniqueness | `projects.name` PRIMARY KEY **per server DB** | **DESIGN gap** — uniqueness is per-box; fleet-wide needs a central, and the boxes cannot reach each other |
| decision node | which server a new project lands on | **DESIGN**. `STATE.md`: "nothing answers this yet" |

## II.3 The backup model — a state machine

Four producers write into one store. Each writes a **differently labelled** artifact, because each makes a different claim, and a restore must know which claim it is trusting.

```
                        ┌──────────────────────────┐
                        │        IDLE              │
                        └──┬───┬────┬──────────┬───┘
         nightly timer ────┘   │    │          │
   ┌──────────────────────────┘    │          └──────────────────────┐
   │              deploy event ────┘                                 │
   │                                     explicit operator save ─────┤
   ▼                                                                 │
┌────────────────┐ ┌────────────────────┐ ┌────────────────┐ ┌───────┴────────┐
│  ROTATING      │ │  CHECKPOINT        │ │  BASELINE      │ │  BASELINE      │
│  label: (none) │ │  label: "pinned"   │ │  label:"saved" │ │  label: "auto" │
│  KEEP = 14     │ │  EXEMPT from       │ │  operator      │ │  7 quiet days, │
│  oldest pruned │ │  rotation until    │ │  asserts this  │ │  no operator   │
│                │ │  RELEASED          │ │  is good       │ │  assertion     │
└───────┬────────┘ └─────────┬──────────┘ └────────────────┘ └───────┬────────┘
        │                    │ release                               ▲
        │                    ▼                            ┌──────────┴─────────┐
        │          ┌──────────────────┐                   │ quiet-day counter  │
        └─────────>│ rejoins rotation │                   └──────────┬─────────┘
                   └──────────────────┘                              │
                                                  ┌───────────────────┴────────┐
                                                  │  OPEN TICKET on this       │
                                                  │  project?                  │
                                                  └───────┬─────────────┬──────┘
                                                      yes │             │ no
                                                          ▼             ▼
                                                 ┌─────────────┐  ┌───────────┐
                                                 │  BLOCKED    │  │  PROMOTE  │
                                                 │ counter     │  │ to "auto" │
                                                 │ holds       │  └───────────┘
                                                 └─────────────┘
```

**The retention guard, which is LIVE and is the reason the rest is safe to build on:**

```
   RUN ──> wrote > 0 AND no failures? ──yes──> PRUNE oldest beyond KEEP
                      │
                      └──no──> "retention skipped — this run had failures,
                               keeping every copy"      backup.sh:355-361
```

An unconditional `find -delete` removes the last good copy during a failure streak. `KNOWLEDGE.md` records this was found in another project's script and *shipped in this one anyway* before being fixed.

**Why four labels and not one retention policy.** Each artifact answers a different question at restore time:

```
(none)   "this is what the machine looked like that night"   — no claim
pinned   "this is what it looked like immediately before     — a boundary
          a specific deploy"
saved    "a human looked at this and said it was good"       — an assertion
auto     "nothing broke for 7 days, so probably good"        — an inference
```

Collapsing them loses the distinction between *asserted* and *inferred*, and a restore that cannot tell those apart is a restore made on hope.

**Why an open ticket blocks "auto" and nothing else.** Quiet means *nobody reported a problem*. An open ticket is a standing report of a problem. Seven quiet days with a ticket open is not quiet — it is unattended, and unattended is the one state that must not be promoted to a baseline. It blocks only the inference; the nightly rotation and an explicit save both still run, because a human asserting "good" outranks a machine inferring "quiet".

| Element | State | Evidence |
|---|---|---|
| nightly run | **LIVE** ksgcohub, "daily, proven unattended" | `STATE.md` |
| `KEEP = 14` | **LIVE** | `backup.sh:57` |
| prune-only-on-success | **LIVE** | `backup.sh:355-361` |
| zero-artifacts = FAIL | **LIVE** | `backup.sh:350-353` |
| different-device check | **LIVE** | `_derive_dest()` asks `kernel/storage.py` |
| named volumes without host sudo | **LIVE** | `docker run -v <vol>:/src:ro`; fks-services went 5.0MB → 1.1GB |
| bind mounts `/srv/docker` | **GAP, reported not skipped** | no volume to mount; needs filesystem read |
| `pinned`/`saved`/`auto` labels | **DESIGN** | no label field in `backup.sh`, no table |
| deploy → checkpoint trigger | **DESIGN** | `releases` (`control.py:74`) records `staged\|checked\|promoted\|rolled_back`, emits nothing |
| quiet-day counter | **DESIGN** | requires the ticket store, which does not exist |
| **fks-services** | **partial** — 21 volumes exposed; FlareVault and Metaforge both here, **neither backed up** | `STATE.md` |

The `deploy → checkpoint` edge is the cheapest real one on this page: the `releases` table already fires on the exact event. It needs an emitter, not a design.

## II.4 Ticket / self-fix — ordered, not optional

```
   PROJECT observes a symptom  ("my container will not start")
              │
              ▼
   ┌─────────────────────────┐   POST /api/ticket/<project>
   │  FILE TICKET            │   ┄┄> [0]  {DESIGN — no route, no handler}
   │  {problem, what_i_see}  │
   └───────────┬─────────────┘
               ▼
   ┌───────────────────────────────────────────────┐
   │  SERVER DIAGNOSES from what only it can see   │
   │    disk at 96%          neighbour on its port │
   │    volume pruned        band moved underneath │
   └───────────┬───────────────────────────────────┘
               ▼
   DIAGNOSIS → PROJECT ──> PROJECT FIXES ──> DECLARE the fix ──> TICKET CLOSED
                           (the project still     what changed,      → unblocks the
                            does the fixing.      why, under          quiet-day
                            It now does the       which ticket        counter (§II.3)
                            RIGHT one.)

   The forbidden edge:   symptom ──X──> fix
                         blind fix, no ticket, no declaration
```

**Why ticket-before-fix, and not ticket-after.** The two parties hold disjoint halves of the diagnosis:

```
   PROJECT SEES                      SERVER SEES
   container will not start          disk at 96%
   port refused                      another project bound to that port
   data gone                         the volume was pruned
   was working yesterday             the band moved
```

A project fixing on its half alone produces the specific failures this system was built to stop — rebinding to a random free port, dropping data on the OS disk, joining another project's network. All three are *reasonable* given only the left column, and all three break isolation in the name of getting unstuck.

**Why self-fix is allowed but must be declared.** Six weeks later, an undeclared self-fix and unexplained drift produce an identical row: a value that does not match what was claimed, with no reason attached. The declaration is the only thing that distinguishes deliberate work from decay. `KNOWLEDGE.md`: "an unrecorded self-fix is indistinguishable from drift."

**Nothing in this graph blocks.** The project is not prevented from fixing blind. The ordering is a norm the server records compliance with — `SERVER-COMMANDS.md` rule 2, "Your compliance is your own."

Everything in II.4 is **DESIGN**. No `ticket` table in `control.py` (`projects`, `acks`, `releases`, `diffs` only), no `/api/ticket` row in `router.py`. The word "ticket" appears exactly once in any `.py` in the repo and it is a comment at `collect.py:81`. The nearest live thing is `diffs` + `dispose`, which handles *differences found at verification* — not *symptoms reported by a project*. Those are different objects and must not share a table: one is machine-derived and re-derivable every verify, the other is a project's observation and is not derivable at all.

## II.5 Bulletin — broadcast and targeted, one mechanism

```
   HUB
    │ publish
    ▼
   ┌─────────────────────────────────────────────────┐
   │  SERVER: bulletin N                             │
   │    body, self-contained (no links out,          │
   │          no "see also")                         │
   │    version bump ONLY on actionable change       │
   │    ends with: THE ONE THING YOU DO              │
   │               ("nothing right now" is valid)    │
   │    ends with: PIN                               │
   └───────┬──────────────────────────┬──────────────┘
    BROADCAST                     TARGETED
    every project on               one project, its own
    THIS server, same text         correction, same mechanism
           └────────────┬─────────────┘
                        │  sits. does not push. does not block.
                        ▼
              OPERATOR  "pull up our server commands"
                        ▼
              PROJECT   server bulletins   GET /api/bulletins?since=$LAST_PIN
                        server read <n>    GET /api/bulletins/<n>
                        server ack <n> <pin> + answer (REQUIRED)
                        ▼
              SERVER records who read what, and their answer
                        ▼
              STALE LIST  = projects not on N  → OPERATOR
                          INFORMATION, NOT A GATE
```

**The snapshot vector.** A project holds bulletin N. The server moves to N+1. The project comes back for the delta — it does not re-read from rung 1.

```
   project @ N ────> server @ N+1 ────> delta ────> ack(N+1) ────> project @ N+1
```

**Version-bump discriminator** — this is what keeps the PIN meaningful:

```
   BUMPS                                 DOES NOT BUMP
   port bands                            current port usage
   data paths                            disk percent
   isolation rules                       container counts
   a project arriving or leaving         any live reading
   direction / restructuring
```

Bump on live readings and every project is permanently stale, staleness stops carrying information, and the PIN degrades into a receipt for noise.

**Why nothing blocks.** A blocking bulletin makes the server a dependency of every deploy on it. Then an unread bulletin is an outage, and the correct response to a bulletin becomes "ack it fast so the deploy goes through" — which is exactly the skim the PIN exists to prevent. Non-blocking keeps the PIN's only currency *attention*. The stale list flows to the operator, who is the only enforcement mechanism in the system and has judgement.

**Load-bearing detail:** empty is reported as `none`, not as silence. "No bulletins for you" and "the call did not reach the server" are different answers and only one is information.

**Why "the one thing you do" is mandatory and may be "nothing".** A bulletin that always demands work trains projects to treat bulletins as work queues, and work queues get deferred. `STATE.md`: "If every bulletin demands work they stop reading them."

Everything in II.5 is **DESIGN**. `grep -rni "bulletin" hub/ --include=*.py` returns **0** — not one comment, zero. The word appears only in `KNOWLEDGE.md`, `STATE.md` and `SERVER-COMMANDS.md`. The `answer` column exists — `acks.answer` at `control.py:65` — and `control.stale()` / `control.fleet_stale()` (`:147`, `:167`) already compute a stale list, keyed on the git master ref rather than a bulletin number. **The staleness engine is live; the thing it should be measuring staleness against is not.**

## II.6 Vector inventory — every edge, one owner each

| # | From → To | Verb | Transport | Owner (single) | State |
|---|---|---|---|---|---|
| V1 | OPERATOR → PROJECT | point | speech | operator | **LIVE**, unautomated by design |
| V2 | PROJECT → SERVER | read rules | `GET /api/admit` `20311702` | `handlers/node.py` | **LIVE** ksg [0] |
| V3 | PROJECT → SERVER | read self | `GET /api/registry/<p>` `20313702` | `handlers/registry.py:94` | **LIVE** ksg [0] |
| V4 | PROJECT → SERVER | claim | `POST /api/registry/<p>` `20313703` | `handlers/registry.py:121` | **LIVE** ksg [0] |
| V5 | PROJECT → SERVER | verify | `POST …/verify` | `handlers/registry.py:695` | **CODE-ONLY**, uncommitted + unrouted |
| V6 | PROJECT → SERVER | read diffs | `GET …/diffs` | `handlers/registry.py:752` | **CODE-ONLY**, uncommitted + unrouted |
| V7 | PROJECT → SERVER | dispose | `POST …/dispose` | `handlers/registry.py:792` | **CODE-ONLY**, uncommitted + unrouted |
| V8 | PROJECT → SERVER | ack | `POST /api/ack/<p>` `20313704` | `handlers/registry.py:149` | **LIVE** ksg [0], keyed on git ref not PIN |
| V9 | HUB → SERVER | read registry | `GET /api/registry` `20313701` | `handlers/registry.py:83` | **LIVE** ksg |
| V10 | HUB → SERVER | read machine | `GET /api/receipt` `20302713` | `handlers/status.py` | **LIVE both** |
| V11 | SERVER → SERVER | heartbeat | `POST /api/heartbeat` `20312701` | `handlers/mesh.py` | **CODE-ONLY** — split tailnets |
| V12 | HUB → SERVER | publish bulletin | — | — | **DESIGN** |
| V13 | PROJECT → SERVER | list bulletins | `GET /api/bulletins?since=` | — | **DESIGN** |
| V14 | PROJECT → SERVER | read bulletin n | `GET /api/bulletins/<n>` | — | **DESIGN** |
| V15 | PROJECT → SERVER | file ticket | `POST /api/ticket/<p>` | — | **DESIGN** |
| V16 | SERVER → PROJECT | diagnosis | — | — | **DESIGN** |
| V17 | PROJECT → SERVER | declare self-fix | — | — | **DESIGN** |
| V18 | SERVER → disk | nightly backup | `tools/backup.sh` | `backup.sh` | **LIVE** ksg / **partial** fks |
| V19 | releases → backup | deploy checkpoint | — | — | **DESIGN**; `releases` already fires the event |
| V20 | SERVER → OPERATOR | stale list | `control.stale()` `:147` | `kernel/control.py` | **LIVE**, wrong key |
| V21 | gate declaration → enforcement | — | `HUB_ENFORCE_GATES` | — | **DESIGN** — 59 of 77 declare, 0 apply |

**Tally.** 8 LIVE vectors, 7 of which have been traversed **zero** times by a project. 4 CODE-ONLY. 9 DESIGN. The honest reading: the *project-facing surface* is partly built and completely unused; the *ladder, the PIN, the bulletin and the ticket* — the four things that make the surface mean anything — are not built at all.

## II.7 The cut set — which absent edges dominate the graph

Ranked by how many other edges they hold up, not by effort.

```
  1. PIN            gates V8, V13, V14 — the entire ladder. Without it "ack"
                    records that a project was told, not that it read.
                    Smallest real change on the page: acks.ref carries a PIN.
  2. bulletin store V12→V14, and gives V20 something correct to measure against.
                    The staleness engine already exists, pointed at a git ref.
  3. ticket store   V15→V17, and unblocks the §II.3 quiet-day counter. Cannot be
                    the diffs table: machine-derived ≠ project-observed.
  4. backup labels  V19. The event source (releases) already exists; only the
                    emitter and a label field are missing.
  5. fleet-wide     V11 is unreachable — split tailnets. Until resolved,
     uniqueness     "unique fleet-wide" is asserted by the operator, not the
                    code, and a new project's name collision is undetectable.
```

Every one of these is a **store plus one emitter**. None is a new subsystem. The graph is not missing components; it is missing four tables and the edges that write to them.

---

# PART III — THE SURFACE (SITEMAP)

**How this was measured.** Route table parsed from `hub/kernel/router.py` `ROUTES` by `ast.literal_eval` in this pass. Liveness was probed 2026-09-24 16:45 against both servers (not re-run here); POST routes were not probed and inherit their module's GET result.

```
  DECLARED          77 routes in ROUTES        48 GET · 29 POST
  REACHABLE         80                         +3 sub-actions dispatched inside
                                                a prefix handler (uncommitted)
  PUBLISHED         57                         what /api/sitemap tells a project
                                                — wrong on both boxes
  PLAN NEEDS        +3 or more                 do not exist anywhere
```

## III.1 The route table, by module — one owner each

`LIVE-BOTH` = 200 on both. `LIVE-KSG` = 200 on ksgcohub, **404 on fks-services**. `HEAD` = in committed code, not probed (POST). `UNCOMMITTED` = working tree only, on no server.

| Mod | Owner file | N | Routes | Status |
|----|----|--:|----|----|
| 01 identity | `handlers/identity.py` | 10 | `/`, `/mobile`, `/desktop`, `/ui/*`, `/manifest.json`, `/sw.js`, `/api/my-ip`, `/api/identity`, `/api/access` | LIVE-BOTH |
| | | | `/api/auth/provider` (20301710) | **LIVE-KSG** |
| 02 status | `handlers/status.py` | 21 | GET `/api/status` `/api/setup/status` `/api/containers` `/api/services` `/api/ports` `/api/storage` `/api/docker/images` `/api/docker/volumes` `/api/docker/stats` `/api/docker/diagnostics` `/api/integrations` `/api/manifest` `/api/receipt` `/api/sync` `/api/context` `/api/sitemap` `/cutsheet` | LIVE-BOTH (17 probed 200) |
| | | | POST `/api/refresh` `/api/docker/prune` `/api/docker/action/*` `/api/ports/ack` | HEAD |
| 03 federation | `handlers/federation.py` | 3 | GET+POST `/api/federation`, POST `/api/peer/register` | LIVE-BOTH |
| 04 config | `handlers/config.py` | 7 | GET `/api/vault` `/api/issues` `/api/journal` `/api/config`; POST same | LIVE-BOTH |
| 05 users | `handlers/users.py` | 10 | GET `/api/auth/check` (401 by design) `/api/users` `/api/totp/status` `/api/totp/setup`; POST `/api/auth/login` `/api/auth/logout` `/api/users` `/api/totp/confirm` `/api/totp/verify` `/api/totp/disable` | LIVE-BOTH |
| 06 events | `handlers/events.py` | 4 | GET+POST `/api/incidents`, GET+POST `/api/activity` | LIVE-BOTH |
| 07 ai | `handlers/ai.py` | 3 | GET+POST `/api/ai/config`, POST `/api/ai/chat` | LIVE-BOTH |
| 08 tunnel | `handlers/tunnel.py` | 2 | POST `/api/tunnel/start` `/api/tunnel/stop` | HEAD |
| 09 proxy | `handlers/proxy.py` | 4 | `/proxy/*`, `/api/docs`, `/api/docs/content`, `/api/files` | LIVE-BOTH |
| 10 ops | `handlers/ops.py` | 4 | POST `/api/run` `/api/update` `/api/setup/generate-claude-md` `/api/service/install` | HEAD |
| 11 node | `handlers/node.py` | 2 | `/api/node`, `/api/admit` | **LIVE-KSG** |
| 12 mesh | `handlers/mesh.py` | 3 | POST `/api/heartbeat` `/api/mesh/register`, GET `/api/mesh/fleet` | **LIVE-KSG** |
| 13 registry | `handlers/registry.py` | 4 | GET `/api/registry` `/api/registry/<p>`, POST `/api/registry/<p>`, POST `/api/ack/<p>` | **LIVE-KSG** |

**10 of 77 routes exist on ksgcohub and not on fks-services** — the whole project-facing layer (node 11, mesh 12, registry 13) plus `/api/auth/provider`. "Two servers, one build" is the target, not today's fact.

## III.2 The 3 routes that are not in the route table

`resolve()` matches the longest **literal** prefix, and the project name sits in the middle of the path, so these cannot be declared. They are split inside the handler (`handlers/registry.py:61` `_target`, `ACTIONS` at line 79):

```
GET  /api/registry/<project>/diffs      -> get_registry_diffs      (registry.py:752)
POST /api/registry/<project>/verify     -> post_registry_verify    (registry.py:695)
POST /api/registry/<project>/dispose    -> post_registry_dispose   (registry.py:792)
```

Status: **UNCOMMITTED.** Verified: `git show HEAD:hub/handlers/registry.py | grep -c get_registry_diffs` → **0**. The committed file defines seven functions; the working tree defines twenty-four. `handlers/registry.py` is +705 lines uncommitted. They run on no server.

A reader auditing the surface from `ROUTES` alone will miss these three. A reader auditing from `/api/sitemap` will miss twenty.

## III.3 Gate distribution — verified in code

```
gate 0  public          18  ██████
gate 1  user            41  ███████████████
gate 2  admin           14  █████
gate 3  totp             4  █
                        --
                        77      gated (>0) = 59
```

**Enforcement is OFF.** `hub/kernel/router.py:193`:

```python
ENFORCE_GATES = os.environ.get('HUB_ENFORCE_GATES', '0').lower() not in ('0', 'false', '')
```

Default `'0'` → `False`. `grep -rn HUB_ENFORCE_GATES` across the repo: six hits, all of them a definition, a comment, or documentation. **Nothing sets it.** A failed gate appends to `_shadow_denials` (capped at 500) and the request proceeds. `shadow_report()` has no route — the shadow log is unreadable over HTTP.

**Three counts in the repo are stale and disagree with each other and with the table:**

| Source | Claims | Actual |
|---|---|---|
| `kernel/router.py:189-190` | "52 of 65 routes gated" | 59 of 77 |
| `FABRIC.md:168` | "52 of 73 routes declare a gate" | 59 of 77 |
| `BOM.md:128` | "55 of 73 routes declare a gate above 0" | 59 of 77 |

None is generated. **A number maintained in prose beside the thing is the drift this project exists to remove, and the plan documents are doing it too.**

## III.4 The published sitemap is not the route table

`GET /api/sitemap` (20302716, gate 0) returns a **second, hand-written list** in `handlers/status.py:167`. Both servers publish **57 entries**.

```
 57  published      of which 1 is fictional: '/proxy/{port}/{path}'
                    (no such path in ROUTES)
 18  routes in ROUTES that the published sitemap omits
  0  live on fks-services of the 5 routes it publishes but 404s
```

fks-services publishes the same 57 as ksgcohub while serving 10 fewer routes. **A project that discovers the surface via `/api/sitemap` on fks-services is told about endpoints that will 404 it.** `routes_by_module()` (`kernel/router.py:145`) exists as the seam to generate this list from `ROUTES` and has no callers.

## III.5 Endpoints the plan needs that do not exist

`grep -rn "bulletin\|/api/ticket" --include=*.py hub/` returns **nothing**. Probe: `/api/bulletins` → 404 on both.

| Endpoint | Gate | Owner module (proposed) | Status |
|---|---|---|---|
| `GET /api/bulletins?since=<pin>` | 1 | 14 bulletins — new file | DESIGN, no code |
| `GET /api/bulletins/<n>` | 1 | 14 bulletins | DESIGN, no code |
| `POST /api/ticket/<project>` | 1 | 15 tickets — new file | DESIGN, no code |

Reserve **14** and **15** now. Modules 13-19 are free per the namespace block at `kernel/router.py:24`; taking them costs nothing and a collision after both servers ship costs a migration.

**Backup model — `save` / `deploying` / `deployed`.** No endpoint, no handler, no route, and **no definition in the repo**: `grep -i "deploying\|deployed\|snapshot\|rollback"` across `plan/THE-PLAN.md`, `KNOWLEDGE.md`, `STATE.md` returns only prose about the port band, never a state machine. What exists today is `backup.sh` (363 lines) installed to `~/.local/bin/hub-backup.sh` on a `hub-backup.timer` at 03:00 — a cron, with no HTTP surface at all. The model in §II.3 has to be written down before any route can be defined for it.

## III.6 The seven commands → the routes they call

| # | Command | Route it calls | ksgcohub | fks-services |
|--:|---|---|---|---|
| 1 | `server status` | `GET /api/registry/$PROJECT` | LIVE | **404** |
| 2 | `server bulletins` | `GET /api/bulletins?since=$LAST_PIN` | **404** | **404** |
| 3 | `server read <n>` | `GET /api/bulletins/<n>` | **404** | **404** |
| 4 | `server ack <n> <pin>` | `POST /api/ack/$PROJECT` | LIVE, **wrong body** | **404** |
| 5 | `server rules` | `GET /api/admit?project=$PROJECT` | LIVE | **404** |
| 6 | `server claim` | `POST /api/registry/$PROJECT` | LIVE | **404** |
| 7 | `server ticket` | `POST /api/ticket/$PROJECT` | **404** | **404** |

**4 of 7 commands work, on one of two servers. On fks-services, zero of seven.**

**Command 4 is a contract mismatch, not a gap.** `SERVER-COMMANDS.md:76` documents the body as `{"bulletin": <n>, "pin": "<pin>", "answer": "..."}`. `post_ack` (`handlers/registry.py:149`) reads `ref` and `answer` and never looks at `bulletin` or `pin`:

```python
ref = (b.get('ref') or '').strip()
n, msg = _ctl.acknowledge(name, ref or cur, b.get('answer', ''))
```

`ref` is the **git master ref** of the server, not a PIN. A project following the saved file posts a PIN, gets `ok: true`, and has acknowledged nothing — `ref` falls through to `ref or cur`, so the server records the project as having acked its own current ref without reading it. **The PIN mechanism — the whole point of the ladder — is unimplemented, and the documented call silently succeeds without it.** This is the failure mode the project exists to remove, reproduced inside it.

Live evidence, ksgcohub, 2026-09-24 16:45:

```json
{"master": "", "projects": [], "stale_count": 0,
 "who": {"node": "ksgcohub", "server_id": "fvn_685a59", "mode": "node"}}
```

`master` is empty — there is no ref to acknowledge.

## III.7 Surface at a glance

```
                         ksgcohub          fks-services
DECLARED    77           ───────────────   ───────────────
  live                        67                 57
  absent                       0                 10   ← modules 11,12,13
  POST, unprobed (HEAD)       10                 10
UNDECLARED   3           ─────────────────────────────────
  registry sub-actions         0                  0   ← uncommitted, nowhere
MISSING      3+          ─────────────────────────────────
  bulletins ×2, ticket         0                  0   ← design only
  backup state machine         0                  0   ← model undefined

PUBLISHED   57  identical on both · omits 18 real · invents 1 ·
                overstates fks-services by 10
ENFORCEMENT OFF everywhere · 59 of 77 routes declare a gate no one checks
```

---

# PART IV — MODULE MAP (NON-MONOLITHIC)

Counted 2026-09-24 on branch `fix/project-port-band`. `handlers/mesh.py`, `handlers/registry.py`, `kernel/control.py`, `tools/fleet-status.py` and `bootstrap.sh` are **uncommitted working-tree** versions, so their counts include work not yet in any commit.

```
                         LINES   FILES
  hub/server.py            152       1    HTTP shell + process boot
  hub/kernel/            3,798      12    11 modules + empty __init__.py
  hub/handlers/          3,645      14    13 modules + __init__.py
  hub/app.html           5,765       1    the UI. one file. see Part VI
  hub/tools/             1,334       8    the assertions. 4 have no caller
```

## IV.1 The doctrine, and the shape that actually exists

```
  DOCTRINE                          ACTUAL
  server.py                         server.py ─────────────┐
     │                                 │                   │ (V1)
     ▼                                 ▼                   │
  kernel/router.py                  kernel/router.py       │
     │                                 │ importlib         │
     ▼                                 ▼                   ▼
  handlers/*                        handlers/* ──(V2)──> handlers/registry.py
     │                                 │
     ▼                                 ▼
  kernel/*                          kernel/*  ──(V3)──> kernel/collect.py ──> kernel/storage.py
                                                              │ (V4: also reads disks itself)
                                                              ▼
                                                        kernel/auth.py (V5: re-exported)
```

## IV.2 kernel/ — every module, what it OWNS

| Module | Lines | OWNS (one thing, or the list of things) | imported by |
|---|--:|---|---|
| `db.py` | 115 | the SQLite connection and schema bootstrap. **Clean: one owner.** | 16 |
| `ssh.py` | 38 | running one command on the box. **Clean.** | 10 |
| `log.py` | 165 | activity rows, ntfy push, the Docker event loop. *Three things.* | 11 |
| `auth.py` | 279 | sessions, gate tokens, TOTP, `_config_get`. *Four things.* | 13 |
| `identity.py` | 207 | `server.identity.json`, mode, HS256 issue/verify. *Two things.* | 7 |
| `heartbeat.py` | 184 | node-side emitter + 3-path fallback chain. **Clean.** | `server.py` |
| `fleet.py` | 195 | central-side fleet registry + status state machine. **Clean.** | `handlers/mesh` |
| `storage.py` | 284 | the disk landscape, derived. **Clean, and the model for the rest.** | 5 |
| `control.py` | 549 | projects · acks · releases · diffs · dispositions · weight. *Six things.* | `handlers/{mesh,registry}` |
| `router.py` | 300 | route table + dispatch + gate evaluation + shadow denials. *Four things, in the wrong package.* | `server.py` |
| `collect.py` | **1,482** | **§IV.4. the remaining monolith.** | 6 |

## IV.3 handlers/ — every module

| Module | Lines | Routes | OWNS | Note |
|---|--:|--:|---|---|
| `registry.py` | 846 | 4 (+3 dispatched) | claims, acks, verify, machine-read, compare, diffs, dispositions | *Seven things.* The largest handler. `_machine(project)` at :267 is an 81-line second container reader |
| `proxy.py` | 419 | 4 | reverse proxy + HTML/CSS rewrite + cache + docs + guide tokens + **its own `get_server_info`** | *Five things* |
| `mesh.py` | 380 | 3 | heartbeat intake, registration, fleet view, congruence, self-entry | reaches sideways into `handlers/registry` (V2) |
| `status.py` | 330 | 21 | 21 endpoints, **each a 3-line passthrough into `collect`** | 18 separate lazy imports of `collect`. Owns nothing; it is `collect.py`'s URL surface |
| `users.py` | 322 | 10 | login/logout, users CRUD, TOTP, config get/set, journal | *Five things* |
| `node.py` | 287 | 2 | `node_payload` + admission band derivation | *Two things, in different dimensions* |
| `identity.py` | 222 | 10 | `app.html`, manifest, service worker, `/ui/` assets, identity, access | *Six things.* Static serving and Identity in one module because both start with "i" |
| `ai.py` | 194 | 3 | AI chat + its own `_config_get`/`_config_set` | |
| `ops.py` | 165 | 4 | ops commands + **a third `get_server_info`** | |
| `federation.py` | 163 | 3 | peer list/register + `_config_get_all`/`_config_set` | |
| `config.py` | 131 | 7 | vault pointers, issues, journal, config | *Four things* |
| `tunnel.py` | 98 | 2 | tunnel start/stop + the real watcher | |
| `events.py` | 87 | 4 | activity feed | **Clean** |

## IV.4 `kernel/collect.py` — the remaining monolith

1,482 lines. It is not "system-state collectors" as its docstring claims. It is **nine unrelated concerns**, spanning six of the seven dimensions plus Law A, in one file that six modules import.

| Lines | Concern | Dimension | Where it belongs |
|---|---|---|---|
| 48–85 | `PROJECT_BAND` 12000–18999, per-project 100 | Admission | `kernel/admission.py` |
| 398–432 | `PORT_LANES` (12 lanes), `_PORT_NAMES`, `_port_lane` | Admission | `kernel/admission.py` |
| 101–140 | `get_server_info` — hostname/OS/IP/cores | Identity | `kernel/identity.py` |
| 141–258 | `get_status` — uptime/RAM/disk/load, 60s cache | Substrate | `kernel/substrate.py` |
| 632–757 | `scan_ports`, `_do_port_snapshot`, `_port_scan_loop` | Substrate + Account | reader → `substrate`, diff/emit → `account` |
| **1028–1131** | **`api_storage_info`** — `df -BG` + `lsblk` + `docker system df` | Substrate | **delete. §IV.5** |
| 1134–1198 | `api_docker_images` / `_volumes` / `_stats` | Substrate | `kernel/substrate.py` |
| 259–308 | `get_containers` + `SERVICES` (18 hardcoded) | Tenancy | reader → `tenancy`, table → `kernel/recognise.py` |
| 310–395 | `build_services` — enrich SERVICES with live Docker | Tenancy (Law C) | `kernel/tenancy.py` + `recognise` |
| 1383–1420 | `get_integrations` — hardcoded Redis/SurrealDB/n8n probes | Tenancy (Law C) | `kernel/recognise.py` |
| 1200–1309 | `api_docker_diagnostics` — 110 lines of interpreted findings with their own severity words | Account | `kernel/account.py` |
| 1436–1482 | `tunnel_status`, `get_access_info` — which doors exist | Authority | `kernel/authority.py` |
| 33–36 | re-exports `check_auth, gate_check, gate_create, totp_*, _sessions, _gate_sessions` | Authority | **delete the re-export.** Callers import `kernel.auth` |
| **435–630** | **`build_cutsheet_html`** — 196 lines of HTML generation | *none* | Law A: a projection → `hub/projections/` |
| 820–1024 | `build_receipt` (114 lines), `build_context` (90) | *none* | Law A: projections |
| 1311–1381 | `get_manifest` — BOM: server info, services, docker df, git ref | *none* | Law A: projection |
| 14, 16 | `import http.server`, `import socketserver` | — | **dead.** A kernel collector importing a web-server framework |

Receipt, context, manifest and the cutsheet are **four renderers of the same facts living inside the reader of those facts.** That is FABRIC.md Law A stated as a file layout: four shapes, one source, nobody removed the previous one.

## IV.5 The two readers of the disks — LIVE and UNRESOLVED

This is the bug the fortnight was spent removing, still live on both servers.

```
  /api/storage ──> handlers/status.py:94 ──> collect.api_storage_info()  ─┐
                                                                          ├─> the disks
  /api/node    ──> handlers/node.py:232 ──> storage.landscape()          ─┘
  /api/status  ──> collect.get_status() ──> storage.landscape() (:220, lazy)
```

`handlers/status.py:94` is the only caller of `api_storage_info`, and it is the endpoint the UI's storage view uses. The two readers disagree by construction:

| | `kernel/storage.py:88 mounts()` | `kernel/collect.py:1028 api_storage_info()` |
|---|---|---|
| reads | `findmnt -J -b` (bytes, JSON) | `df -BG` (whole gigabytes) |
| filters | **allowlist** `REAL_FS` | **substring denylist** `docker overlay tmpfs udev loop /snap` |
| dedupe | yes — one device bind-mounted twice counts once | **no** |
| units | `round(size/GB, 1)` | `int(p[2].rstrip('G'))` |
| cache | 120s, derivation cached | none, shells out 5× per call |

`collect.get_status()` already learned this and delegates to `storage.landscape()` at line 220 with the comment *"a missing total is better than a wrong one"* — **but `api_storage_info` 800 lines below in the same file never got the same treatment.** The fix is one line in `handlers/status.py:94` and the deletion of 104 lines; until it is done, `/api/storage` and `/api/node` can hand a project two different pictures of the same machine.

## IV.6 Doctrine violations — `server → router → handlers → kernel`

| # | Violation | Evidence | Status |
|---|---|---|---|
| V1 | **server imports a handler directly**, skipping the router | `server.py`: `from handlers.node import node_payload` | LIVE |
| V2 | **handler imports handler** — lateral | `handlers/mesh.py:31`: `from handlers.registry import _master as _central_ref` | LIVE (uncommitted) |
| V3 | **kernel imports handlers** — the layer inversion. `router.py` sits in `kernel/` and calls `importlib.import_module('handlers.' + module)` at :245, so `kernel` is not the bottom layer; it is a package-level cycle | `kernel/router.py:245` | LIVE. Router is misfiled |
| V4 | **second reader of a dimension** | §IV.5 | LIVE |
| V5 | **kernel/collect re-exports kernel/auth** | `kernel/collect.py:33–36` | LIVE, unused by any handler — dead surface |
| V6 | **`handlers/status.py` owns nothing.** 21 routes, 18 identical lazy imports of `collect` | `handlers/status.py` | LIVE |
| V7 | **three copies of `get_server_info`** | `kernel/collect.py:102`, `handlers/proxy.py:142`, `handlers/ops.py:25` | LIVE |
| V8 | **four copies of config get/set**, plus a fifth private one in the kernel | `handlers/{ai,users,federation,identity}`, `kernel/auth.py:138` | LIVE. There is no `kernel/config.py`. `handlers/ai.py:20` admits it: *"pending move to kernel/config.py"* |
| V9 | **two copies of `_machine_id`** outside its owner | `kernel/identity.py:51` owns it; `handlers/node.py:33` and `handlers/identity.py:50` re-derive it | LIVE |
| V10 | **ten public handler functions are unreachable** — no route entry exists | verified by ast diff, list in Part V | **CODE-ONLY**. Three of them are the whole of rung 3 |
| V11 | **the UI is one 5,765-line file** | `hub/app.html` | LIVE. `hub/ui/registry.js` and `hub/ui-next/` both exist as replacements; nothing imports `ui-next` |

## IV.7 Target decomposition — one module per dimension

`kernel/` becomes seven owners, one per FABRIC dimension, plus three support modules and a separate projection layer. **Nothing below is built. DESIGN.**

```
  hub/
    server.py         HTTP shell only. loses the handlers.node import (V1)
    routing/
      table.py        the 77 route entries. data, not code
      dispatch.py     resolve + call.        moves OUT of kernel/ (V3)
      gate.py         evaluate + shadow.     the one place authority is applied
    kernel/                                   <-- bottom layer. imports nothing above
      identity.py     1. what am I           + get_server_info      <- collect:101
      substrate.py    2. what am I made of   + get_status, scan_ports, docker df
                                             <- collect:141,632,1134  DELETE collect:1028
      storage.py      2. (already correct — kept beneath substrate)
      tenancy.py      3. what lives here     + get_containers, build_services
                                             <- collect:259,310
      recognise.py    3. Law C: enrichment keyed by image, never a gate
                                             <- collect SERVICES:288, get_integrations:1383
      admission.py    4. what may a newcomer take
                                             <- collect:48 band, :398 lanes, node.py _free_band
      continuity.py   5. what survives       <- tools/backup.sh, today outside the code
      authority.py    6. who may act         <- auth.py + collect:1436 tunnel, :1454 doors
      account.py      7. what happened       <- log.py + collect:1200 diagnostics
                                                + collect:704 port diff + fleet.py severity
                                                ONE severity scale. today there are five
      db.py  ssh.py  config.py                support. config.py is new and kills V8
      control.py      SPLIT: claims.py · acks.py · releases.py
    projections/                              Law A. renderers, never readers
      receipt.py      one projection at four depths
                                             <- collect:820 receipt, :935 context,
                                                :1311 manifest, :435 cutsheet
    handlers/                                 thin. URL in, projection out. no logic
```

**What each move costs, honestly:**

| Move | Blocked by | Size |
|---|---|---|
| Delete `api_storage_info`, point `/api/storage` at `storage.landscape()` | nothing | 1 line + 104 deleted. **Do this first — it is the live two-readers bug** |
| Route the ten orphan handlers (V10) | a decision on gate level | 10 route entries |
| Lift the 4 projections out of `collect.py` | nothing | ~400 lines moved, 0 rewritten |
| `kernel/config.py`, delete 4 copies | nothing | ~60 lines net negative |
| Move `router.py` → `routing/` | V1 must go first, or `server.py` still reaches past it | mechanical |
| Split `control.py` into claims/acks/releases | uncommitted work must land first | 549 → 3 files |
| `account.py` with one severity scale | requires the five vocabularies to be reconciled: `storage.findings` high/warn/info · `fleet._derive_status` five states · `users` failure counter · `log` level · `api_docker_diagnostics` its own words | **the real work.** Everything else is moving files |

Ordering follows FABRIC's cleanup order, not file size: **Continuity has no module at all** — it exists only as `tools/backup.sh` — and Authority has 59 declared gates and zero enforcement. Those two are unbuilt dimensions, not messy ones. `collect.py` is merely untidy, and untidy is cheaper than absent.

---

# PART V — BILL OF MATERIALS

Every count carries the command that produced it. Per `CONSTITUTION.md` §4 a BOM may never be hand-written prose — this section is the cached output of the commands in it, and **the commands are the real BOM. Re-run them; do not trust the numbers.**

## V.1 Files and lines by type

```
git ls-files | wc -l                                       → 186 files
git ls-files -z | xargs -0 wc -l | tail -1                 → 34,959 total
```

| Type | Files | Lines | Owner of this mass |
|---|--:|--:|---|
| `.py` | 35 | 8,807 | hub runtime, tools, maintenance agent |
| `.html` | 7 | 8,675 | `hub/app.html` 5,765 · `hub/mobile.html` 771 · docs-site + manual |
| `.md` | 43 | 6,716 | blueprint, knowledge, plan — see §V.6 |
| `.jsx` | 43 | 3,798 | `hub/ui-next/src/` — **nothing imports any of it** |
| `.json` | 8 | 3,613 | `knowledge/telescope-codes.json`, `registry-live.json` |
| `.sh` | 17 | 2,157 | `bootstrap.sh` 844 · `hub/tools/backup.sh` 363 · `enroll.sh` 232 |
| `.js` | 8 | 547 | `hub/ui/registry.js` 104 + 2 views |
| `.bat` | 11 | 123 | Windows launchers, work PC only, never ship |
| `.css` | 2 | 297 | ui-next |
| `.sql` | 1 | 147 | `knowledge/decisions.sql` — 2 INSERTs |
| `.service` | 3 | 40 | legacy units at repo root + server-kit |
| `.timer` | 1 | 9 | `hub-maintenance.timer` |
| `.toml` | 1 | 9 | `netlify.toml` |

`hub/ui-next/` in total is 56 tracked files, 4,637 lines. Full assessment in Part VI.

## V.2 Routes — 77

```
python -c "import ast;src=open('hub/kernel/router.py').read()
R=[ast.literal_eval(n.value) for n in ast.parse(src).body
   if isinstance(n,ast.Assign) and getattr(n.targets[0],'id','')=='ROUTES'][0]
from collections import Counter
print(len(R), Counter(r['method'] for r in R), sorted(Counter(r['gate'] for r in R).items()),
      Counter(r['module'] for r in R).most_common())"

77 routes        GET 48 · POST 29        prefix-match 6 · exact 71
gate 0  18   gate 1  41   gate 2  14   gate 3  4
```

```
status     21  ####################
identity   10  ##########       users 10
config      7  #######
registry    4  ####     events 4   proxy 4   ops 4
mesh        3  ###      federation 3   ai 3
node        2  ##       tunnel 2
```

Eight routes are not under `/api`: `/` `/mobile` `/desktop` `/ui/` `/proxy/` `/manifest.json` `/sw.js` `/cutsheet`.

**Handlers with no route — 10 of 85 public functions are unreachable.** Verified by ast diff of `{(module, handler)}` in `ROUTES` against public `FunctionDef` names in `hub/handlers/*.py`:

```
registry.post_registry_verify    registry.get_registry_diffs
registry.post_registry_dispose   mesh.get_mesh_registry
node.node_payload                ops.get_server_info
proxy.proxy_fetch                proxy.get_server_info
tunnel.tunnel_start              tunnel.tunnel_stop
```

The three `registry.*` ones are the verify/diff/dispose half of the plan. They are written, unrouted, **and uncommitted**.

## V.3 Tools — 8, and what invokes each

| Tool | Lines | Invoked by | Status |
|---|--:|---|---|
| `backup.sh` | 363 | `bootstrap.sh:763` → `hub-backup.service` | **invoked** |
| `install-preflight.py` | 248 | `bootstrap.sh:45,312,314,813` | **invoked** |
| `reclaim.sh` | 25 | `bootstrap.sh:764` → `hub-reclaim.service` | **invoked** |
| `storage-preflight.py` | 88 | `bootstrap.sh:753` | **invoked** |
| `registry_gen.py` | 279 | — | **NOTHING** |
| `fleet-status.py` | 190 | — | **NOTHING** |
| `flare-mode.sh` | 85 | — | **NOTHING** (docs mention only) |
| `check-views.py` | 56 | — | **NOTHING** |

**4 of 8 tools, 610 of 1,334 lines, have no caller.** `check-views.py` appears four times in `hub/kernel/control.py` (lines 297, 450, 456, 476) — every one of them is a *string* in a `next:` advice field, not an execution. `hub/kernel/identity.py:206` states outright that it is "not a caller" of `registry_gen.py`.

## V.4 systemd units — they differ per server, and that is drift

`bootstrap.sh` writes exactly five units (`713 hub.service · 766 hub-backup.service · 775 hub-backup.timer · 787 hub-reclaim.service · 796 hub-reclaim.timer`).

| Unit | ksgcohub | fks-services |
|---|---|---|
| `hub.service` | active running | active running |
| `hub-backup.timer` | **active**, last 2026-09-24 03:11 | **absent** |
| `hub-reclaim.timer` | **active**, next Sun 04:15 | **absent** |
| `hub-alert.timer` | absent | active, 15-min |
| `hub-daily.timer` | absent | active — service **failed** |
| `hub-maintenance.timer` | absent | active, 03:00 |

This is not values-differ-because-disks-differ. These are **different units from different generations of the installer**. fks-services has never run the bootstrap that writes backup and reclaim, and carries `hub/tools/` with **2 files** (`__init__.py`, `registry_gen.py`) — `install-preflight.py` cannot be run there, so the node cannot be checked at all.

## V.5 Databases and tables

**ksgcohub `~/hub/db/server.db`** — 11 tables, 1.5 MB
```
port_events 19,253 | activity_log 949 | port_snapshots 96 | hub_config 3
users 1 | incidents 0 | issues 0 | journal 0 | notes 0 | sessions 0
```

**ksgcohub `~/hub/db/control.db`** — 4 tables (`projects`, `acks`, `releases`, `diffs`, schema at `control.py:52-96`), **every one empty.** This is the plan's central record and it has never held a row.

**fks-services `~/hub/db/server.db`** — 10 tables, 4.2 MB
```
port_events 49,611 | activity_log 6,310 | port_snapshots 96 | hub_config 3 | users 1 | rest 0
```
**No `control.db` exists.** No `sessions` table (schema predates auth work).

**Work-PC `db/server.db`** — 9 tables, a third schema again: `services 23 | notes 19 | containers 7 | issues 5 | connections 1 | users 1 | hub_config 0 | journal 0`.

Three machines, three incompatible schemas. Tables that exist on all three: 4 (`hub_config`, `issues`, `journal`, `users` — and `issues`/`journal` are empty everywhere).

## V.6 Documents, and whether anything can falsify each

| Document | Lines | Falsifier | Verdict |
|---|--:|---|---|
| `hub/CONSTITUTION.md` | 175 | none | prose, by its own admission (§4) |
| `hub/FABRIC.md` | 242 | none | prose — and its gate count is stale |
| `hub/KNOWLEDGE.md` | 194 | none | prose |
| `hub/plan/STATE.md` | 201 | none | prose; declared authoritative |
| `hub/plan/THE-PLAN.md` | 326 | none | operator's words, not checkable |
| `hub/SERVER-COMMANDS.md` | 152 | **7 curl calls — 3 of them 404, 1 wrong body** | **partially falsified**, Part III.6 |
| `hub/BOM.md` | 591 | `git ls-files \| wc -l` | **FALSIFIED** — says 113 files / 25,472 lines, is 186 / 34,959 |
| `hub/CAPABILITIES.md` | 147 | the ✅ column claims tools run | 3 of its 5 named tools have no caller |
| `MASTER.md` | 350 | `install-preflight.py` | **11 install steps vs 10 assertions** |
| `docs/flareshub-blueprint.md` | 390 | none | prose |
| `docs/flareshub-frontend-dag.md` | 159 | none | prose |
| `hub/INTAKE.md` + `hub/intake/MANIFEST.md` | 336 | `hub/intake/*` dirs are **empty** | nothing filed |

`python3 hub/tools/install-preflight.py` is the only falsifier that runs: 10 assertions, **8 of 10 on ksgcohub**, unrunnable on fks-services.

```
[x] hub service  [x] identity fvn_685a59  [x] data root /srv/data 457.4GB
[x] backup target  [x] backups running  [x] cache reclamation
[~] storage sound — /srv/data 0% used while / carries the load
[x] layout  [x] admin password  [ ] enrolled — no public hostname
```

Prose to executable-assertion ratio: **6,716 lines of Markdown against 10 assertions.** One assertion per 672 lines of claim.

## V.7 Three-column status — every capability in the plan

| Capability | ksgcohub | fks-services | Status |
|---|---|---|---|
| `server status` → `GET /api/registry/<p>` | 200 | 404 | **LIVE** one node |
| `server rules` → `GET /api/admit` | 200 | 404 | **LIVE** one node |
| `server claim` → `POST /api/registry/<p>` | route present | 404 | **LIVE** one node, 0 claims |
| `server ack` → `POST /api/ack/<p>` | route present | 404 | **LIVE** one node, 0 acks, wrong contract |
| `server bulletins` / `server read <n>` | 404 | 404 | **DESIGN** — 0 lines |
| `server ticket` | 404 | 404 | **DESIGN** — 0 lines |
| **The PIN** (proof-of-read) | — | — | **DESIGN** — 0 hits in kernel/handlers |
| Ladder rungs 1–4 | — | — | **DESIGN** |
| Registry verify / diffs / dispose | unrouted | absent | **CODE-ONLY** — uncommitted |
| `control.db` projects/acks/releases/diffs | 4 tables, 0 rows | no file | **LIVE, empty** / absent |
| `GET /api/node` | 200 | 404 | **LIVE** one node |
| `GET /api/receipt` | 200 | 200 | **LIVE both** |
| `GET /api/mesh/fleet` | 200 | 404 | **LIVE** one node |
| `GET /api/federation` | 200 | 404 | **LIVE** one node; peer unreachable |
| Node identity file | `fvn_685a59` | **absent** | **LIVE** one node |
| Enrolment / public hostname | not enrolled | not enrolled | **CODE-ONLY** (`enroll.sh`, 232 lines) |
| Nightly backup / cache reclamation | timers active | **no timers** | **LIVE** one node |
| `install-preflight` 10 assertions | 8 of 10 | tool absent | **LIVE** one node |
| Port band **12000–18999**, 100/project | running 7100–7899 | nothing | **CODE-ONLY** |
| 12-lane port library in first readout | — | — | **DESIGN** |
| Storage template `/srv/data/<project>/…` | — | — | **DESIGN** |
| `public/` vs authenticated rule | — | — | **DESIGN** |
| Host uids for project isolation | — | — | **DESIGN — undecided** |
| Label-provable isolation | **0 of 16** containers labelled | 34 containers, unmeasured | **DESIGN** |
| Intake inbox/outbox/claims/working/closed | dirs exist, **empty** | absent | **CODE-ONLY** |
| `hub/ui-next/` | not served | not served | **CODE-ONLY** — 4,637 lines, 0 importers |
| Recipe and spec as one map | 11 steps vs 10 assertions | — | **DESIGN** |
| Repo separation serverhub / workspace | `CLAUDE.md` still ships | same | **DESIGN** |
| BOM as `GET /api/receipt` output, not a file | `BOM.md` 591 lines of prose | same | **DESIGN** |

## V.8 The ratio

```
36 capabilities counted above
   LIVE       12   — and 11 of those 12 are live on ONE server only
   CODE-ONLY   5
   DESIGN     19

DESIGN     ###################  19  (53%)
LIVE       ############         12  (33%)  ← 11 of 12 are single-node
CODE-ONLY  #####                 5  (14%)
```

**Fleet-wide, exactly one capability is LIVE on both servers: `GET /api/receipt`.**

The premise of the whole plan — *projects read the bulletin, acknowledge with a PIN, comply on their own schedule* — is four capabilities, and all four are DESIGN. `grep -rni bulletin hub/ --include=*.py` returns **0**. Not partial, not scaffolded: zero lines.

The measurable record of the mechanism working:

```
projects registered   0        acknowledgements      0
bulletins published   0        diffs recorded        0
tickets filed         0        containers labelled   0 of 16 on ksgcohub
```

Against that, the parts that *are* moving are the parts nobody asked to move: 19,253 and 49,611 `port_events` rows accumulating on two machines with nothing reading them, 4,637 lines of an unused frontend, 610 lines of tools no process invokes, and 1,869 lines uncommitted on the five files that hold the registry.

---

# PART VI — UI LANDSCAPE

## VI.1 What exists today — before any of the design below

| Thing | Where | Status |
|---|---|---|
| 28 view entries, 24 offered in nav | `hub/ui/registry.js` (104 lines) | **LIVE** |
| 4 not in nav | `iframe`, `blank` (shells); `platform`, `tasks` (tombstones) | **LIVE** |
| Every `mount` is `null` | all 28 still render from the legacy switch in `app.html` | **LIVE** |
| 2 views have their own file | `hub/ui/views/browser.js`, `hub/ui/views/issues.js` | **CODE-ONLY** — files load, mounts not wired |
| One 5,248-line global script scope | inside `app.html` (5,765 lines total); 18 localStorage keys | **LIVE** |
| Layout is **not** persisted | every session starts `createWorkspace('Home')`, `app.html:6166` | **LIVE** |
| Two-server matrix | `hub/tools/fleet-status.py` — CLI text table, one SSH round trip per host | **CODE-ONLY**, no caller |
| Registry read/write surface | 4 declared routes + 3 dispatched | **LIVE on ksgcohub** (declared 4 only), 404 on fks-services |
| Bulletins, PINs, tickets, checkpoints | `hub/SERVER-COMMANDS.md` prose only | **DESIGN — zero code** |

"Checkpoint" as a word does not exist in the repo. The nearest real thing is the `releases` table, `staged\|checked\|promoted\|rolled_back` (`hub/kernel/control.py:74`).

**None of the four screens below exist. All four are DESIGN.**

## VI.2 Sitemap — the DAG of screens

```
                          ┌──────────────┐
                          │ [1] LANDING  │   the fleet, both boxes, one screen
                          └──────┬───────┘
          ┌──────────────┬───────┼────────────┬──────────────┐
          ▼              ▼       ▼            ▼              ▼
   ┌────────────┐ ┌───────────┐ ┌──────────┐ ┌──────────┐ ┌─────────┐
   │[2] PROJECT │ │[3]BULLETIN│ │[4] PORT  │ │ ACTIONS  │ │ the 24  │
   │   VIEW     │ │   VIEW    │ │   MAP    │ │  drawer  │ │ existing│
   └─────┬──────┘ └─────┬─────┘ └────┬─────┘ └────┬─────┘ │  views  │
         │              │            │            │       └─────────┘
    ┌────┴────┐    ┌────┴────┐       │       ┌────┴────┐
    ▼    ▼    ▼    ▼         ▼       ▼       ▼         ▼
  diffs claim ack  read/     PIN   band    trigger  publish
        │    │     unread    audit holder  a read   a bulletin
        ▼    ▼       matrix                         promote release
     dispose history                                release checkpoint
```

Edges are one-way. There is no edge from **PROJECT VIEW** to a project session — the operator is the only path, and the server is the only channel (Part I.1).

## VI.3 The landing — both servers at once

Values in `⟨ ⟩` are read live at render; they are not figures held in this repo.

```
┌─ FLEET ──────────────────────────────────────────── ⟨ts⟩ ───┐
│  CONGRUENCE   ⚠ DRIFT   refs differ: ⟨a1b2c3⟩, ⟨d4e5f6⟩     │
│               the ref is the test. Different data roots and │
│               bands below are the system WORKING.           │
│  ┌── ksgcohub ──────────────┐ ┌── fks-services ───────────┐ │
│  │ ref      ⟨3d89b9c⟩ 2 back│ │ ref    ⟨ab02c2f⟩ 62 back  │ │
│  │ hub      ⟨active⟩  ⟨200⟩ │ │ hub    ⟨active⟩   ⟨200⟩   │ │
│  │ preflight  8 of 10       │ │ preflight  tool absent    │ │
│  │ identity   present       │ │ identity   MISSING        │ │
│  │ ─────────────────────────│ │───────────────────────────│ │
│  │ OS disk    98G   ⟨n%⟩    │ │ OS disk    1T    ⟨n%⟩     │ │
│  │ data root  /srv/data     │ │ data root  /srv/docker    │ │
│  │            458G  ⟨n%⟩    │ │ backup vol /backup  4.4T  │ │
│  │ ─────────────────────────│ │───────────────────────────│ │
│  │ band       7100-7899     │ │ band       ⟨- no /admit⟩  │ │
│  │ projects   0 registered  │ │ projects   n/a  ← unknown,│ │
│  │ stale      0 of 0        │ │ stale      n/a    not zero│ │
│  │ ─────────────────────────│ │───────────────────────────│ │
│  │ backup   ✓ daily, timer  │ │ backup   ⚠ PARTIAL        │ │
│  │          armed, unattended│ │          21 named volumes │ │
│  │ reclaim  ✓ timer         │ │          exposed; FlareVault│
│  │                          │ │          + Metaforge: none │ │
│  │ ─────────────────────────│ │───────────────────────────│ │
│  │ here     fksinv          │ │ here     metaforge/keynox │ │
│  │          babyhelp        │ │            18 containers  │ │
│  │                          │ │          FlareVault :7777 │ │
│  └──────────────────────────┘ └───────────────────────────┘ │
│  FLEET TOTALS — stated separately, never summed             │
│    4 projects · 0 registered · 0 acknowledged · 0 aware     │
│    registry unreadable on fks-services: its projects are    │
│    UNKNOWN, not current.                                    │
└─────────────────────────────────────────────────────────────┘
```

Three rules this card enforces, carried straight from `fleet-status.py`:

- **`n/a` and `0` are different answers and only one is information.** `_registry_cells()` (`tools/fleet-status.py:112`) refuses to print `0` for a node whose registry did not answer. The card must refuse the same way — a grey `n/a`, never a green `0`.
- **Never one fleet-wide stale total.** Summing a node that answered with a node that did not produces a number that reads as though both were checked.
- **A blank ref cell reads as "no drift".** `ref=${REF:-?}` exists because `echo` succeeds whether or not `git` printed. The card renders `?`, and `?` is a red state.

## VI.4 Project view — one standing record

Source: `GET /api/registry/<project>` (LIVE) + `/diffs` (CODE-ONLY, uncommitted) + tickets (DESIGN).

```
┌─ babyhelp ───────────────── home: ksgcohub ⟨server_id⟩ ─────┐
│ state  claimed          status  dev                         │
│        awaiting→claimed→verified→reconciled                 │
│        ●──────────●─────────○──────────○                    │
│                                                             │
│ RUNG    1 ●  you are already in this server    ack'd ⟨-⟩    │
│          2 ○  where this server is going       locked       │
│          3 ○  what that means for you          locked       │
│          4 ○  maintained                       locked       │
│          a project that has not confirmed what it IS        │
│          cannot evaluate what is CHANGING.                  │
│                                                             │
│ ─ PORTS ────────────────────────────────────────────────── │
│   band offered   ⟨from /api/admit⟩  (proposed, unallocated) │
│   actually bound 12080              ← outside, migration    │
│   fksinv, same server 10100/10101   ← Supabase Stack lane   │
│   MIGRATION not cutover. Neither is urgent. Neither is a    │
│   violation.                                                │
│                                                             │
│ ─ DATA ─────────────────────────────────────────────────── │
│   /srv/data/babyhelp/  db/ media/ cache/ releases/          │
│                        public/ private/                     │
│   DESIGN — the template in STATE.md does not exist on disk. │
│                                                             │
│ ─ CONTINUITY ───────────────────────────────────────────── │
│   volume babyhelp-data   1.0MB   ✓ in nightly tar           │
│   baseline    ⚠ NEVER RESTORED. A backup nobody has         │
│               restored is a belief. (FABRIC, cleanup #1)    │
│                                                             │
│ ─ ACKS (append-only) ───────────────────────────────────── │
│   ref            answer                          at         │
│   (none)         — never acknowledged any master —          │
│                                                             │
│ ─ DIFFS ────────────────────────────────────────────────── │
│  id claimed        machine       why          disposition   │
│  ⟨⟩ ⟨from claim⟩  ⟨read now⟩    ⟨…⟩          [fix][accept]  │
│                                                [defer]      │
│                                                [hub-wrong]  │
│   hub-wrong is a first-class button, not a footnote. The    │
│   hub has been wrong about which band it owned.             │
│   Disposing RECORDS. It never runs the fix.                 │
│                                                             │
│ ─ CLAIM (verbatim, never edited) ───────────────────────── │
│   CF zone · hostname · tunnel · Access policy · DNS ·       │
│   where secrets live · who its users are · what it plans    │
│   NOT containers, ports or mounts — the server reads those. │
│                                                             │
│ ─ TICKETS ──────────────────────────────────────────────── │
│   DESIGN. No table, no route, no storage.                   │
└─────────────────────────────────────────────────────────────┘
```

Left half is derived and re-read every load. Right half (claim, acks, dispositions) is stored because it is not re-derivable. The panel border is where that line falls, deliberately.

## VI.5 Bulletin view — the read/unread matrix

The single most useful screen here, and **100% DESIGN**. Today every cell is the same value.

```
┌─ BULLETINS ── ksgcohub ─────────────────────────────────────┐
│                    │ fksinv │ babyhelp │ (2 on fks-services)│
│  ──────────────────┼────────┼──────────┼─────────────────── │
│  #3 rung 2  ⟨date⟩ │   ·    │    ·     │   not published    │
│  #2 storage ⟨date⟩ │   ·    │    ·     │   there            │
│  #1 you are        │   ·    │    ·     │                    │
│     already here   │   ·    │    ·     │                    │
│  ──────────────────┴────────┴──────────┴─────────────────── │
│   ● read + ack'd, PIN matched   ○ published, unread         │
│   · nothing has ever been published                         │
│                                                             │
│  A COLUMN is a project's ignorance. A ROW is a bulletin's   │
│  reach. Read down to find who to point at; read across to   │
│  find what never landed.                                    │
│                                                             │
│  THE MATRIX IS INFORMATION, NOT A GATE. Nothing blocks.     │
│                                                             │
│  ┌─ #1 · broadcast · ksgcohub ───────────────────────────┐  │
│  │ scope     every project on this server, same text     │  │
│  │ version   bumps ONLY on actionable change (§II.5)     │  │
│  │ self-contained  no links out, no "see also"           │  │
│  │ ends with THE ONE THING THEY DO                       │  │
│  │ PIN       ████  hidden in the UI.                     │  │
│  └───────────────────────────────────────────────────────┘  │
│  ANSWERS — required even when "nothing, does not affect me" │
└─────────────────────────────────────────────────────────────┘
```

**The PIN is masked on the operator's screen on purpose.** Its whole value is that it proves a project read the text; an operator who can see it can hand it over, and then it proves nothing. Reading the PIN out to a project is being the messenger again.

## VI.6 Port map — 12 lanes, fleet-wide

Lanes verbatim from `PORT_LANES`, `hub/kernel/collect.py:398`.

```
┌─ PORT LANES ── one library, both servers ───────────────────┐
│ lane             range(s)                    holder         │
│ ──────────────── ──────────────────────────  ────────────── │
│ System           1-1023                      OS             │
│ Infrastructure   80-81, 443, 3000-3099       NPM, Homepage  │
│ Database         5400-5499,6300-6399,6379    PG, Redis      │
│ Automation       5600-5699                   n8n            │
│ Hub              8765                        THIS           │
│ Tools            8000-8999                   Supabase API,  │
│                                              Adminer, ntfy  │
│ Storage          9000-9089, 9091-9099        MinIO          │
│ Admin            9090, 9400-9499, 9443       Cockpit, Ptnr  │
│ Supabase Stack   10000-10999                 RESERVED       │
│ AI               11000-11999                 Ollama et al   │
│ Projects         12000-18999    ← the lane   see below      │
│ Monitoring       8090, 19000-19999           Netdata,Dozzle │
│                                                             │
│ ─ PROJECTS LANE · 12000-18999 · 100 each · 70 bands ─────── │
│   ALLOCATION IS FLEET-WIDE. A band is unique across BOTH    │
│   servers, so a project moves machines without renumbering. │
│   (Today uniqueness is per-box — see §II.2. Fleet-wide is   │
│    asserted by the operator, not enforced by the code.)     │
│                                                             │
│   band          project    server        state              │
│   12000-12099   fksinv     ksgcohub      PROPOSED — bound   │
│                                          at 10100/10101     │
│   12100-12199   babyhelp   ksgcohub      PROPOSED — bound   │
│                                          at 12080           │
│   —             metaforge  fks-services  unallocated        │
│   —             FlareVault fks-services  unallocated,       │
│                                          bound 7777         │
│   12200-18999   67 bands free                               │
│                                                             │
│ ─ OFFSET inside a band — suggested, NEVER enforced ──────── │
│   x00-x19 UI      x20-x39 API     x40-x59 data              │
│   x60-x79 workers x80-x99 dev/preview/debug                 │
│   The band is the boundary. The split inside it belongs to  │
│   the project. Outgrowing 100 is a ticket, not a violation. │
│                                                             │
│ ⚠ UNRESOLVED, shown on this screen and not hidden:          │
│   7100-7899 was DEPLOYED to ksgcohub before any project was │
│   told, and is still what that box serves. 12000-18999      │
│   replaced it on the branch, also untold, and is on no      │
│   server. 0 of 4 projects know either number.               │
└─────────────────────────────────────────────────────────────┘
```

Collision detection already exists live: `/api/ports` (`hub/handlers/status.py:55`) scans with `ss` and classifies by lane. This screen is its projection plus the allocation table, which has no storage yet.

## VI.7 What the operator ACTS on from here

Four buttons. Every one goes to the **server**. None goes to a project.

```
ACTION                 WRITE VECTOR                        STATUS
─────────────────────  ──────────────────────────────────  ──────
trigger a project      renders the exact sentence the      DESIGN
to read                operator says out loud, plus which
                       server. Emits NOTHING. The UI is a
                       teleprompter, not a transmitter.

publish a bulletin     POST → bulletins store              DESIGN
                       scope broadcast|targeted            no route,
                       mints the PIN, pins the version     no table
                       refuses to publish without "the
                       one thing they do"

promote a release      control.promote(ref) →              CODE-ONLY
                       releases: staged→checked→promoted   control.py
                       rollback writes rolled_back;        :210-325
                       weight() reads the rows in order    no UI

release a checkpoint   NO SUCH CONCEPT IN THE REPO.        DESIGN
                       Nearest: `releases` above, and      (undefined)
                       tools/backup.sh. What a checkpoint
                       is — a ref, a backup, or both
                       pinned together — is undecided and
                       this button must not ship before
                       that word means one thing.
```

Two things deliberately absent: **nothing arms a gate**, and **nothing rejects a claim**. `HUB_ENFORCE_GATES` is off with 59 of 77 routes declaring a gate, and whether admission *rejects* an out-of-band claim or merely *records* a violation is still open in `STATE.md`. A UI button is not the place to decide it.

## VI.8 Read vectors — one panel, one owner, one source

Non-monolithic means each panel is a separate file under `hub/ui/views/`, one registry entry each, and none fetches on behalf of another.

| Panel | Owner file | Source | Dimension | Status |
|---|---|---|---|---|
| fleet cards | `views/fleet.js` | `fleet-status.py --json` | all seven | tool CODE-ONLY, view DESIGN |
| congruence banner | `views/fleet.js` | ref set comparison | Identity | logic exists in the tool |
| disk / data root | `views/storage.js` (exists) | `/api/receipt` | Substrate | view LIVE |
| standing record | `views/project.js` | `/api/registry/<p>` | Tenancy | route LIVE, view DESIGN |
| diffs + dispose | `views/diffs.js` | `/diffs`, `/dispose` | Tenancy | routes CODE-ONLY, view DESIGN |
| rung ladder | `views/rungs.js` | acks table | Account | table LIVE, no projection |
| bulletin matrix | `views/bulletins.js` | — | Account | DESIGN, nothing to read |
| port lanes | `views/ports.js` (registered) | `/api/ports` | Substrate | route LIVE, view via switch |
| band allocation | `views/bands.js` | — | Admission | DESIGN, no store |
| backup state | `views/continuity.js` | timers + manifest | Continuity | partial |
| actions drawer | `views/act.js` | writes only | — | DESIGN |

Eleven panels, eleven owners. The failure this avoids is the one `ui/registry.js` already documents: a view that lived in four places drifted — `survey` had a renderer and no metadata, `_browser_old` was dead code in a switch. Adding a panel here is one file plus one line.

## VI.9 `hub/ui-next/` — stated plainly

`hub/ui-next/` is a **clone of another app's shell**. The source files were copied byte for byte from fksinv's UI at `/srv/docker/fksinv/ui/src` on ksgcohub: ~3,040 lines verbatim (15 shell components, 20 `components/ui` primitives, 2 layout components, 4 of 6 stores), ~108 lines of verbatim config, ~145 lines written here (an emptied registry, 5 widget stubs, an entry point). Total tracked: 56 files, 4,637 lines, of which 43 files / 3,798 lines are `.jsx`.

**Nothing imports it.** The hub serves `hub/app.html`. Deleting the directory changes nothing else in the repo. It still carries fksinv's shape in two places — `useUserStore` is that app's auth model, not ServerHub's sessions; `useScannerStore` is a barcode toggle.

**Whether the UI adopts it is UNDECIDED.** The trade is legible: `app.html` is one 5,248-line global script scope with a legacy switch that `ui/registry.js` is mid-way through dismantling; `ui-next` is a modern shell with no content and a borrowed auth model. Adopting it means the screens above land in React; not adopting means they land as `ui/views/*.js` files behind the existing registry, which is the path already half-walked and already reversible per view. Both are defensible. Neither has been chosen, and the four screens above are written to be buildable either way — they are panel boundaries and data vectors, not components.

---

# PART VII — CORRECTIONS APPLIED

Every correction below was re-derived from `C:/Dropbox/Files PC Warehouse/claude-server` at `af9ba09` in this pass. Where two source sections disagreed, the tree decides.

| # | Claim(s) in the source sections | Corrected to | How |
|--:|---|---|---|
| 1 | "73 routes" / "78 routes" / "65 routes" | **77** | `ast.literal_eval` of `ROUTES` |
| 2 | "52 of 73 gated" (`FABRIC.md:168`), "52 of 65" (`router.py:189`), "55 of 73" (`BOM.md:128`) | **59 of 77** (18/41/14/4) | same parse. All three repo sources are stale and disagree with each other |
| 3 | "`grep bulletin` returns one hit, a comment at `collect.py:81`" | **Zero hits in any `.py`.** The comment at `collect.py:81` says *ticket*, not *bulletin* | `grep -rni bulletin hub/ --include=*.py` → 0 |
| 4 | "`app.html` 5,765 lines" vs "5,248-line global scope" | **Both correct, different things.** File = 5,765 lines; the script block inside it = 5,248, per `ui/registry.js:15` | `wc -l` |
| 5 | "`backup.sh` (200 lines, `BOM.md:222`)" | **363 lines** | `wc -l`. `BOM.md` stale |
| 6 | "`handlers/registry.py` (7 routes)" | **4 declared in `ROUTES` + 3 dispatched inside the prefix handler = 7 reachable** | route parse + `registry.py:79` `ACTIONS` |
| 7 | verify / diffs / dispose listed as **LIVE [0]** in the vector tables | **CODE-ONLY** — uncommitted *and* unrouted, on no server | `git show HEAD:hub/handlers/registry.py \| grep -c get_registry_diffs` → 0; ast diff shows all three unrouted |
| 8 | "fks-services 8 commits behind" | **Withdrawn.** `git rev-list --count master..HEAD` = **33** (against origin/master; an earlier draft read 73 from a stale local master ref); the last probe put fks-services at `ab02c2f`, 62 behind. 8 cannot be reproduced | local git |
| 9 | "4.3TB /backup" (task brief) | **4.4TB** | five repo sites: `KNOWLEDGE.md:62`, `CONSTITUTION.md:48`, `FABRIC.md:219`, `kernel/storage.py:47`, `plan/STATE.md:32` |
| 10 | "12 telescope modules" in `kernel/` | **11 modules** + an empty `__init__.py` (12 files). Handlers: **13 modules** + `__init__.py` (14 files) | `wc -l hub/kernel/*.py`, `hub/handlers/*.py` |
| 11 | "`_pending()` still describes the old move, gated on 7100 which `collect.py:62` no longer is" | **Worse, and in both directions.** ksgcohub deploys `3d89b9c` where the floor **is** 7100, so it announces a move it has already completed. HEAD is 12000, where the branch never fires, so the new band is announced nowhere | `git show 3d89b9c:hub/kernel/collect.py` → 7100; `af9ba09` → 12000 |
| 12 | "10 of 85 public functions unrouted" | **Confirmed exactly.** Full list in §V.2 | ast diff |
| 13 | "`control.db` — 4 tables" | **Confirmed**: `projects`, `acks`, `releases`, `diffs` (`control.py:52,65,74,85`) | grep |
| 14 | "`post_ack` reads `ref`, never `pin`" | **Confirmed verbatim**, including the `ref or cur` fallback that makes a PIN-bearing call silently succeed | `handlers/registry.py:149-171` vs `SERVER-COMMANDS.md:76` |
| 15 | "BOM.md: 113 files / 25,472 lines" | **186 files / 34,959 lines.** `hub/BOM.md` is falsified and superseded by Part V | `git ls-files` |
| 16 | "`ui-next` 3,798 lines" | **3,798 lines of `.jsx`; 4,637 lines across 56 tracked files** | `git ls-files "hub/ui-next/*"` |

**Deduplication.** The premise and the PROJECT↔HUB non-edge are now stated once (Part I.1) and referenced. The ladder is stated once in full (II.1). The seven commands are tabulated once (III.6). The gate-enforcement fact is stated once (III.3). The two-readers bug is stated once (IV.5). The port lane table is stated once (VI.6). The fleet congruence rule is in I.2; its three display rules are in VI.3.

---

# PART VIII — WHERE THIS STANDS, AND THE SEQUENCE OUT

## VIII.1 LIVE

Deployed and answering today. Eleven of these twelve are on **one server only**.

1. `hub` on :8765 — both servers
2. `GET /api/receipt` — **both servers. The only fleet-wide capability.**
3. `GET /api/node`, `GET /api/admit` — ksgcohub
4. `GET /api/registry`, `GET /api/registry/<p>` — ksgcohub
5. `POST /api/registry/<p>` (claim) — ksgcohub, 0 claims filed
6. `POST /api/ack/<p>` — ksgcohub, 0 acks, **keyed on git ref, not a PIN**
7. `GET /api/mesh/fleet`, `GET /api/federation` — ksgcohub; peer unreachable
8. `db/control.db` with 4 tables — ksgcohub, **every table empty**
9. Node identity `fvn_685a59` — ksgcohub only; fks-services has no identity file
10. Nightly backup + cache reclamation timers, proven unattended — ksgcohub
11. `backup.sh` retention guard, zero-artifact failure, different-device check, named-volume backup without host sudo
12. `install-preflight.py` — 8 of 10 assertions pass on ksgcohub; the tool is absent on fks-services

Plus, live and **unwanted**: 59 routes declaring gates that nothing enforces; two independent readers of the disks; three copies of `get_server_info`; five copies of config get/set; 68,864 `port_events` rows across two machines with nothing reading them.

## VIII.2 CODE-ONLY

In the tree; on no server, or on one, or unrouted.

1. **`verify` / `diffs` / `dispose`** — written, uncommitted, unrouted. The whole of rung 3.
2. **Port lane 12000–18999** — in `collect.py` at HEAD, deployed nowhere. ksgcohub still serves 7100–7899.
3. **`tools/fleet-status.py`** — 190 lines, the only two-server congruence check, no caller.
4. **`registry_gen.py`, `flare-mode.sh`, `check-views.py`** — 420 more lines, no callers.
5. **`enroll.sh`** — 232 lines; neither server is enrolled, no public hostname on either.
6. **`hub/ui-next/`** — 4,637 lines, zero importers.
7. **`hub/intake/`** — directories exist on ksgcohub, all empty; absent on fks-services.
8. **Heartbeat / peer registration** — code is fine; the network is split.

## VIII.3 DESIGN

Prose only. Nothing executable.

1. **The PIN.** Zero hits in `kernel/` or `handlers/`. Gates the entire ladder.
2. **Bulletins** — `GET /api/bulletins`, `GET /api/bulletins/<n>`, the store, the version-bump rule, the read/unread matrix. Zero lines of code.
3. **Tickets** — `POST /api/ticket/<p>`, the store, the diagnosis edge, the self-fix declaration. Zero lines.
4. **Rungs 2, 3, 4** and the gate between them. No rung concept in code.
5. **Gate enforcement.** `HUB_ENFORCE_GATES` is never set by anything.
6. **Backup labels** `pinned` / `saved` / `auto`, the deploy→checkpoint trigger, the quiet-day counter. The `releases` table already fires the event and emits nothing.
7. **"Checkpoint"** as a defined word. It does not exist in the repo.
8. **Fleet-wide band uniqueness.** `projects.name` is a primary key per box.
9. **Storage template** `/srv/data/<project>/{db,media,cache,releases,public,private}` — not on disk anywhere.
10. **Label-provable isolation** — 0 of 16 containers labelled on ksgcohub; fks-services unmeasured.
11. **Host uids for project isolation** — undecided.
12. **Whether admission rejects or merely records** an out-of-band claim — open in `STATE.md`.
13. **FlareSHub** — the entry layer. 390 lines of blueprint, zero code.
14. **Which server a new project lands on** — `STATE.md`: "nothing answers this yet."
15. **BOM as `GET /api/receipt` output** rather than a file.
16. All four UI screens in Part VI.

## VIII.4 The sequence to running on both servers

Ordered by what unblocks the most, not by effort. Each step is verifiable by a command, and nothing after step 3 should start before step 3 is true.

**Stage 0 — stop the bleeding in the tree (no server change).**

1. **Fix the two-readers bug.** Point `handlers/status.py:94` at `storage.landscape()`; delete `collect.api_storage_info` (104 lines). One line changed. Until this lands, `/api/storage` and `/api/node` can give a project two different pictures of the same machine.
2. **Commit the 1,869 uncommitted lines** on `bootstrap.sh`, `handlers/mesh.py`, `handlers/registry.py`, `kernel/control.py`, `tools/fleet-status.py`. They hold the entire registry. Nothing below can be deployed while they are only on this laptop.
3. **Route the ten orphan handlers**, or delete them. Three of them are rung 3. Ten route entries plus a gate-level decision.
4. **Generate `/api/sitemap` from `ROUTES`** via the existing unused `routes_by_module()` seam. Kills the second route list, the 18 omissions, the one fictional path, and the fks-services overstatement in one change.

**Stage 1 — make the two servers the same build.**

5. **Re-auth fks-services onto the `ksg.co.hub@` tailnet** (`sudo tailscale up --force-reauth`, at the box, needs sudo). Unblocks V11, `/api/mesh/fleet` as one view, and federation.
6. **Merge `fix/project-port-band` to master and deploy it to both boxes.** 73 commits. After this, `/api/node`, `/api/admit`, `/api/registry`, `/api/ack` exist on fks-services — 10 routes that are missing there today — and both boxes run the same `PROJECT_BAND_FLOOR`.
7. **Run `bootstrap.sh` on fks-services** so it gets `hub-backup.timer` and `hub-reclaim.timer` and the six missing tools. FlareVault and Metaforge are currently unbacked on the box that holds the trust root.
8. **Verify congruence** with `tools/fleet-status.py`. Refs must match; data roots must not.

**Stage 2 — make an ack mean something.**

9. **Add the PIN.** `acks.ref` becomes `acks.pin` (or gains one). This is a field change, not a subsystem. Until it lands, every ack proves only that a project was *told*.
10. **Build the bulletin store and its two routes** (module 14, reserved now). `control.stale()` and `fleet_stale()` already compute the stale list and are pointed at a git ref; repoint them at a bulletin number.
11. **Fix `_pending()`** — it announces a completed move on one box and nothing on the other. Either drive it from `kernel/control.releases` as its own docstring promises, or delete it.
12. **Reconcile `SERVER-COMMANDS.md` with `post_ack`.** Right now the documented call posts a PIN, returns `ok: true`, and records nothing. That is the exact failure this project exists to remove, reproduced inside it.

**Stage 3 — turn the mechanism on.**

13. **Publish bulletin #1** — "you are already in this server" — to both boxes, and point the four projects at it, one at a time, out loud.
14. **Take the first ack.** The number that matters is not 77 routes or 34,959 lines. It is `acks` going from 0 rows to 1.
15. **Then, and only then**, build the ticket store (module 15, reserved now), the backup labels, and the deploy→checkpoint emitter — each of which is a table plus one emitter, and none of which is a new subsystem.

**The honest close.** The project-facing surface is largely built and has been used zero times. The four things that make it mean anything — the PIN, the bulletin, the ticket, the gate — are four tables and the edges that write to them, and all four are absent. Nothing on this page is blocked by difficulty. It is blocked by 1,869 lines sitting uncommitted, two servers on different networks, and no project having ever been told any of it.