# THE UNISON MANAGEMENT PLAN

**This document holds doctrine. It contains no counts, no status marks, no
commit refs and no hostnames** — every one of those was in it, and Part VII is
the record of them being wrong. Every question of fact is answered by a command;
`docs/flareshub-doctrine.md` §0 holds the full table. Drained 2026-09-27.

---

## 0. Opening

The premise is one sentence: **the server is the only wire.** A project never talks to the hub, and the hub never talks to a project. Both talk to the server, and the server keeps the record. The only unautomated link is the operator, who points a project at its server out loud. That is deliberate — a trigger that fires itself is a poll, and polling is ruled out.

There are two servers running the same codebase from the same repo. Their
addresses, disks and RAM are **not written here** — `python3 hub/tools/situation.py`.
They are on split tailnets and cannot reach each other; the operator is
currently the only link between them. **Congruence between them means the same
code ref and the same assertions passing — never the same values.** Different
disks must produce different numbers, and that is the system working.

Several projects exist as running apps across the two boxes. How many are
registered, and how many have acknowledged anything, is `python3 hub/tools/step.py`
and `curl -s <hub>/api/registry` — not a sentence here that was true once.

**This document supersedes the earlier plan documents in this repo** where they
disagree with it. Where a claim here disagreed with the tree, the tree decided
and the correction is listed in Part VII.

Nothing below is new design. Where a section previously overstated what exists, it has been fixed **down**.

---

```
A ──> B    an edge: an actor, a verb, an object
{owner}    the ONE component that owns this edge.
           Two owners on one edge is the bug.
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
                   │ "go talk to your server" — spoken, never a wire  ──>
                   ▼
 ┌────────────────────────┐                   ┌──────────────────────┐
 │ PROJECT                │                   │ HUB  (this session)  │
 │ fksinv · babyhelp      │                   │ reads what projects  │
 │ metaforge · flarevault │                   │ left, publishes next │
 │ running apps           │                   │ the record           │
 │ 0 of 4 registered      │                   │ SSH + same HTTP API  │
 └───────────┬────────────┘                   └──────────┬───────────┘
             │ GET  /api/admit?project=<p>               │
             │ GET  /api/registry/<p>                    │
             │ POST /api/registry/<p>  (claim)           │
             │ POST /api/ack/<p>                         │
             │ POST /api/registry/<p>/verify             │
             ▼                                           ▼
 ╔═══════════════════════════════════════════════════════════════════╗
 ║  SERVER :8765  — the medium. hub/server.py + kernel/router.py     ║
 ║  the route table · the handler modules · the control store        ║
 ║  {projects, acks, releases, diffs}                                ║
 ╚═══════════════════════════════════════════════════════════════════╝
             └────── X  no edge PROJECT ── HUB. Forbidden. ──────┘
```

There are exactly **three** vectors at this level and one of them is speech. The `PROJECT ↔ HUB` non-edge is the whole mechanism: `KNOWLEDGE.md` records it was violated once by messaging a project session directly, and that is logged as an **error**, not a shortcut. A UI control that messaged a project directly would be the same defect.

`hub/SERVER-COMMANDS.md` — the file a project saves in its own repo — is the
whole interface between a project and its server. **The route table is the
truth about those commands**, not that document: it once named two endpoints
that did not exist, and a project following it would have posted a PIN, received
`ok:true`, and acknowledged nothing. `curl -s <hub>/api/sitemap` is the check.
## I.2 Two servers, one build

Their disks, RAM, refs, preflight scores, projects and container counts are
**not drawn here.** A two-box diagram stood in this spot and every figure in it
was a reading taken once.

```bash
python3 hub/tools/situation.py    both nodes: what is serving, exposed, and unseen
curl -s <hub>/api/receipt         one node, completely
```

**Values differ because disks differ; that is the system working.** `hub/tools/fleet-status.py` states the rule: `congruent = same code ref + both pass the same assertions ≠ same values`. **A disagreeing `data root` column is correct. A disagreeing `ref` column is
drift.** Whether it disagrees today is `python3 hub/tools/situation.py`.
Uncommitted work is on neither box and shows as neither — which is its own
failure mode, and the reason the standing rule is commit and push immediately,
never batch.

How far apart the two boxes are is a question for the machines, not for a
diagram that was redrawn twice and wrong both times — one draft read a commit
count from a stale local ref and overstated it by a factor of two.

```bash
python3 hub/tools/situation.py    each node's build ref, and whether it answered
curl -s <hub>/api/mesh/registry   what runs where, and whether it is the same build
```

**A disagreeing `ref` column is drift. A disagreeing `data root` column is
correct.** Congruence is the code ref and the same assertions passing — never
the same values.

## I.3 Three layers, one owner each

```
 ┌─ ENTRY ───────────────────────────────────────────────────────┐
 │ FlareSHub — one domain, one session, bilateral frontend       │
 │ owns: the browser's single origin                             │
 │ docs/flareshub-blueprint.md. Zero code. enroll.sh takes       │
 │ --zone every run, which violates one-entry by itself.         │
 └────────────────────────┬──────────────────────────────────────┘
                          │  aggregates N nodes (unbuilt)
 ┌─ NODE ─────────────────┴──────────────────────────────────────┐
 │ ServerHub — hub/ on :8765, on BOTH boxes                      │
 │ owns: machine-id, disks, ports, containers, activity          │
 │ refuses: credentials, DNS, hostnames (/api/vault/* is a       │
 │          reserved prefix, deliberately unimplemented)         │
 └────────────────────────┬──────────────────────────────────────┘
                          │  pointers up; keys never come down
 ┌─ AUTHORITY ────────────┴──────────────────────────────────────┐
 │ FlareVault                                                    │
 │ owns: credentials, DNS, tunnels, the trust root, server_id    │
 │ today: the node derives its own server_id and issues its own  │
 │ token, with the issuer named `self` rather than `flarevault`  │
 └───────────────────────────────────────────────────────────────┘
```

**A container that is up is not a layer that is wired**, and the difference is
the whole of I.3. The handshake shape was agreed in September 2026 and recorded
in `kernel/identity.py`'s docstring.

**The issuer field is the honest part.** The token is HS256 rather than RS256
by recorded decision — the hub is stdlib-only, and the issuer agreed to match
so this code does not change when `self` becomes `flarevault`. Naming the issuer
`self` while it *is* self is what stops the swap being a silent one.

## I.4 The tailnet split — what it blocks, what it does not

**Discovered 2026-09-11** (`docs/session-log-2026-09.md`). Both nodes were
healthy; they were on different networks. Whether that is still true is
`python3 hub/tools/situation.py`, which reports a node it could not reach as
**unknown, not fine.**

```
  tailnet  kyle@ (tail912c87)     ║     tailnet  ksg.co.hub@ (tail4142b4)
  ┌──────────────────────┐        ║     ┌──────────────────┐ ┌──────────┐
  │ fks-services         │        ║     │ ksgcohub         │ │ work PC  │
  │ node A               │   ╳╳   ║     │ node B           │ │ phone    │
  │ metaforge·flarevault │        ║     │ fksinv·babyhelp  │ │ laptop   │
  └──────────────────────┘        ║     └──────────────────┘ └──────────┘
        peer entry: the other node's address — correct address,
        unreachable network. Both boxes already list each other.

  BLOCKED                          NOT BLOCKED
  ─ cross-server backup            ─ each box backs up to its own device
    (one box's large backup volume    (Continuity's rule is *different physical
     and vice versa)                  device*, not *different box*)
                                    ─ /api/admit, registry, ack: per-server by
  ─ /api/heartbeat node→central       construction, never cross-server
  ─ /api/mesh/fleet as one view    ─ operator reaches BOTH from this PC — one
  ─ /api/peer/register federation     over each path. The operator is the only
  ─ Stage 3 cross-server regards      current link between them.
```

The fix is one command at the box and it needs sudo, so it is the operator's
step and nothing routes around it.

**Nothing in the two-server design depends on the link.** Cross-server arrives
free later *because* the heartbeat carries a node's payload to central — no box
ever needs to reach the other's network. A split tailnet blocks the convenience,
not the architecture, and that distinction is worth holding onto: it is the
difference between a blocker and an inconvenience, and they were confused here
for weeks.

## I.5 Decomposition — one owner per thing

No component does two jobs. Where two exist for one question, that is named as the defect.

| Thing | Sole owner |
|---|---|
| *(the owner column is the doctrine; the status column that stood beside it is `atlas.py`'s job)* | |

**One owner per thing. Where two exist for one question, that is the defect**,
and it is named as one rather than reconciled by hand:

- a hand-maintained route list beside the route table
- two readers of the same disks, with different allowlists and different units
- a hardcoded service roster beside the machine that could be read
- a markdown intake board beside the SQLite table doing the same job
- a port band answered by two modules that disagreed

```bash
python3 hub/tools/atlas.py --parts    every part and what it owns
python3 hub/tools/edges.py            every external joint and its single owner
```

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
                        │  ack(1, PIN₁)  │  ──>
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

```bash
python3 hub/tools/step.py      whether any rung has ever been traversed
python3 hub/tools/matrix.py    every row of every sequence, against the machines
curl -s <hub>/api/registry     who is registered, and what they have acknowledged
```

**The staged-change notice must never be a constant.** A `_pending()` that
returns a literal, gated on one band value, will report that one change forever
and will never report the next one — and a project reading it cannot tell the
difference between "nothing is pending" and "this function has stopped
knowing". **Empty must be reported as `none`, not omitted:** silence and
nothing-pending are different answers, and only one of them is information.

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

**The retention guard, and it is the reason the rest is safe to build on:**

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

```bash
python3 hub/tools/install-preflight.py    is a backup running, and on a different device
python3 hub/tools/matrix.py               sequence B2, asserted against both machines
```

**The cheapest real edge here is `deploy -> checkpoint`:** the release path
already fires on the event, so the checkpoint is a label on an artifact that is
already being produced, not a new producer.

**And a backup nobody has restored is a belief.** Proving a restore is the one
row on this page whose failure is unrecoverable, and it is the row no schedule
can assert for you.

## II.4 Ticket / self-fix — ordered, not optional

```
   PROJECT observes a symptom  ("my container will not start")
              │
              ▼
   ┌─────────────────────────┐   POST /api/ticket/<project>
   │  FILE TICKET            │   ──>  the ticket store
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

**Tickets and diffs are different objects and must not share a table.** A diff
is machine-derived and re-derivable on every verify. A ticket is a project's
own observation and is **not derivable at all** — it is half of a picture the
machine never had. Collapsing them loses exactly the half that cannot be
recovered.

Whether the ticket store exists yet: `curl -s <hub>/api/sitemap`.

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

**The staleness engine and the thing it should measure staleness against are
two separate builds**, and having one without the other is the trap: a stale
list keyed on a code ref answers *"has this project been told about the
build"*, which is not the question. Repointing it at a bulletin number is the
work; rebuilding it is not.

Whether the bulletin store exists yet: `curl -s <hub>/api/sitemap`, and
`grep -rn bulletin hub/ --include=*.py` for the tree. Quote the command with the
claim — a grep result asserted without its command was wrong once in exactly
this document.

## II.6 Vector inventory — every edge, one owner each

The vector table that stood here carried a **State** column — LIVE / CODE-ONLY /
DESIGN per edge, with line numbers. The From/To, Verb and Owner columns are the
doctrine; the State column was the rot, and it is what the commands answer.

**The invariant the table existed to enforce, which needs no table:**

- **No edge is owned twice, and no owner holds two verbs.** Two owners on one
  edge is the bug — it is a split brain, and it is the failure this whole
  architecture is shaped to prevent.
- **The reverse leg reports; it never writes what it does not own.** That is the
  only reason a flow may safely run in both directions.
- **A write keyed by something the caller supplied is not bound.** Bind it to
  something already recorded, or refuse. The correct pattern is already in this
  repo: `outbox.acknowledge` refuses a mismatched name and
  `registry.post_registry_dispose` scopes its UPDATE. Copy those; do not invent
  a third style.

```bash
python3 hub/tools/edges.py    every external joint, its single owner, and what binds each write
```

**An edge that exists and has been traversed zero times is not a working edge.**
It is an untested one. The distinction matters more than the count.

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

# PART III — THE SURFACE

**The route surface is derived, and this document does not restate it.**

Roughly 150 lines of route tables stood here: every route by module, with a
per-server LIVE / HEAD / UNCOMMITTED column, a gate histogram, a sitemap-drift
census and a per-command 404 grid. All of it was a snapshot of one probe.

```bash
curl -s <hub>/api/sitemap             the surface, generated from the route table
python3 hub/tools/edges.py            parses ROUTES and reports what it found
python3 hub/tools/matrix.py           sequence A row 8: gates declared vs applied
python3 hub/tools/situation.py        what answers, per node, and what did not
```

What does not change, and is the reason this part existed:

**A prefix route cannot be declared past the variable part.** `resolve()` matches
the longest literal prefix, so a path with the project name in the middle cannot
have its sub-routes declared — they are dispatched inside the handler instead.
That is a real constraint on the route table's shape, not a defect, and anyone
auditing "which routes exist" by reading `ROUTES` alone will miss every one of
them.

**A hand-maintained sitemap is a second route table.** Its drift is
omission-only, which is the quiet direction: a project is told about the
endpoints someone remembered to add, and never about the ones they did not, so
it builds against a surface smaller than the real one and nothing errors.

**Reserve module numbers before both servers ship.** A telescope-code collision
discovered after deployment costs a migration; reserved and unimplemented costs
nothing. `python3 hub/tools/atlas.py --codes` says which are free, and which are
duplicated — and a duplicated code means *"go to this function"* has two
answers, which is the one thing the scheme exists to prevent.

**Five separate files once stated the route count, and all five disagreed** —
with each other and with `ROUTES`. That is why there is no number on this page.
A number maintained in prose beside the thing it describes is the drift this
project exists to remove.

---

# PART IV — MODULE MAP (NON-MONOLITHIC)

A file and line census stood at the head of this part. It is gone; `atlas.py`
and `wc -l` answer it, and neither can be stale.

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

## IV.2 / IV.3 — what each module OWNS

Two tables stood here giving, per module, its line count, its route count and
who imports it. The line and route columns rotted on contact; the **OWNS**
column is the part that matters and it is stated as a rule instead:

**One module, one thing it owns.** A module with two owners on one question is
the defect — `/api/sitemap` hand-maintaining a second route list beside `ROUTES`
is the canonical case, and the drift was omission-only, which is the quiet
direction: a caller told about the endpoints someone remembered is never told
about the ones they did not.

**A clean seam looks like exactly one importer.** A module imported by one thing
can be moved or deleted on its own; a module imported by ten is a dependency of
the whole system and every change to it is a fleet-wide change.

```bash
python3 hub/tools/atlas.py --parts    every module, and whether it runs unasked or answers when called
python3 hub/tools/edges.py            what each one touches outside this box
```

**Engines run unasked. Wrong in an engine means wrong continuously**, with no
caller to notice. Modules are inert until called. `atlas.py` classifies by what
the code does, not by which directory the file sits in, because the directory is
a convention and the behaviour is the fact.

## IV.4 `kernel/collect.py` — the remaining monolith

A table of line ranges mapped to concerns stood here. **Line numbers are the
fastest-rotting fact in any document** — every edit above them invalidates every
row below.

The durable statement is the shape: **one module owns several unrelated
concerns**, which is Law I of §I.5 — no component does two jobs. What each
concern is, and where it belongs, is §IV.7.

```bash
python3 hub/tools/atlas.py --parts    what the module is classified as, and its code
wc -l hub/kernel/*.py                 the sizes, at the moment you ask
```

Receipt, context, manifest and the cutsheet are **four renderers of the same facts living inside the reader of those facts.** That is FABRIC.md Law A stated as a file layout: four shapes, one source, nobody removed the previous one.

## IV.5 The two readers of the disks

**This is the defect class the whole cleanup was about**, and it is worth one
table because the table is the argument: two readers of one question do not
disagree by accident, they disagree **by construction**.

| | the derived reader | the ad-hoc reader |
|---|---|---|
| reads | `findmnt -J -b` — bytes, structured | `df -BG` — whole gigabytes, parsed from text |
| filters | an **allowlist** of real filesystems | a **substring denylist** |
| dedupe | yes — one device bind-mounted twice counts once | no |
| units | rounded from bytes | truncated from a pre-rounded string |
| cache | derivation cached | none; shells out repeatedly per call |

**An allowlist and a denylist are not two spellings of one filter.** A denylist
admits everything nobody thought of — which is how a read-only snap image
becomes "the largest mount", and how a machine carrying hundreds of gigabytes
reports the size of its root filesystem alone. Every new kind of pseudo-filesystem
is a silent bug in the denylist and a no-op in the allowlist.

The fix is a deletion, not an addition: one reader delegates to the other, and
the second implementation goes. Two readers for one question will disagree
forever, because they were never the same question.

## IV.6 Doctrine violations — `server -> router -> handlers -> kernel`

The named defect classes. **Whether a given one is still open is a question for
a command, not for a status column here** — a status column is what this
document is being drained of.

| # | Violation |
|---|---|
| V1 | a kernel module importing a web-server module — a collector has no business knowing about HTTP |
| V2 | a handler reaching back into `server.py`, which makes the split cosmetic |
| V3 | two readers for one question, disagreeing by construction |
| V4 | one module owning several unrelated concerns |
| V5 | a handler carrying a second implementation of something `kernel/` already owns |
| V6 | a route table with a second, hand-maintained copy of itself |
| V7 | a gate declared and never applied |
| V8 | a fact written by two owners |
| V9 | a write keyed on something the caller supplied |
| V10 | an assertion that cannot fail, standing in for one that can |
| V11 | the UI as one large file, with its registry and its successor both existing beside it |

```bash
python3 hub/tools/atlas.py --parts    every module, classified by what its code does
python3 hub/tools/atlas.py --codes    duplicated telescope codes: one name, two answers
```

## IV.7 Target decomposition — one module per dimension

`kernel/` becomes seven owners, one per FABRIC dimension, plus three support modules and a separate projection layer. **Nothing below is built. It is a target decomposition, and it is here to be
argued with before anything moves.**

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

**What each move costs, and why the order is what it is.**

The expensive part of every one of these is never the file move. It is the
**reconciliation** underneath it: several severity vocabularies that have to
become one scale before anything composes, two disk readers that disagree *by
construction* before one can be deleted, and four renderers of the same facts
that have to agree on a single source before three can go.

A file split that does not do that reconciliation first is a rename, and a
rename leaves both sources of truth in place.

Ordering follows FABRIC's cleanup order, not file size: **Continuity has no module at all** — it exists only as `tools/backup.sh` — and Authority has 59 declared gates and zero enforcement. Those two are unbuilt dimensions, not messy ones. `collect.py` is merely untidy, and untidy is cheaper than absent.

---

# PART V — BILL OF MATERIALS

**There is no bill of materials in this document, and there must never be one.**

`hub/CONSTITUTION.md` §4: *a BOM may never be prose. The moment a bill of
materials is typed into a table, it is wrong and nobody knows.*

Roughly two hundred lines of file counts, line counts, route histograms, tool
inventories, unit tables, database row counts, document censuses and a
three-column per-server status grid stood here. They were the largest single
block of rot in this repo, and Part VII below is the record of them being wrong.

```bash
python3 hub/tools/atlas.py        what exists, and which planes the installer produces
python3 hub/tools/atlas.py --parts  every part, classified by what the code does
python3 hub/tools/edges.py        every external joint, and what binds each write
python3 hub/tools/step.py         which step of the build order we are on
python3 hub/tools/tracks.py       which track is next, and what gates it
python3 hub/tools/matrix.py       the five checklists, asserted against the machines
python3 hub/tools/situation.py    what is serving, exposed, and what could not be seen
bash bootstrap.sh --check         is this node at the installer's standard
curl -s <hub>/api/sitemap         the route surface, generated from the route table
```

```bash
curl -s <hub>/api/receipt    this machine, completely — the real BOM
curl -s <hub>/api/ports      what is actually bound
curl -s <hub>/api/storage    mounts, volumes, Docker usage, log size
```

**Re-run them. Do not trust a number anyone typed** — including one typed here.

Two findings the deleted section earned, kept because they are the evidence for
the rule and not because they are current:

- **A tool nothing calls is a document with a shebang** — but an *invoker
  column* is worse. One script was recorded as "invoked by nothing" while it was
  `ExecStartPost=` in a **user** unit, firing the fleet's wrongest alert on every
  restart. The audit had read only `/etc/systemd/system`. Check both unit paths,
  or do not keep the column.
- **Different units from different generations of the installer is not
  "values differ because disks differ".** That is drift, and it is the thing a
  converging installer exists to end.

---

# PART VI — UI LANDSCAPE

## VI.1 What exists today — before any of the design below

A table of what exists, where, and its status stood here. It is gone for the
reason the rest of this document's tables are gone.

```bash
python3 hub/tools/atlas.py        what exists, and which planes the installer produces
python3 hub/tools/atlas.py --parts  every part, classified by what the code does
python3 hub/tools/edges.py        every external joint, and what binds each write
python3 hub/tools/step.py         which step of the build order we are on
python3 hub/tools/tracks.py       which track is next, and what gates it
python3 hub/tools/matrix.py       the five checklists, asserted against the machines
python3 hub/tools/situation.py    what is serving, exposed, and what could not be seen
bash bootstrap.sh --check         is this node at the installer's standard
curl -s <hub>/api/sitemap         the route surface, generated from the route table
```

**None of the four screens below exists yet.** They are design, and they are
described so the decisions in them can be argued with before anything is built
— mockups before any build, which `hub/tools/tracks.py` enforces as an order and
not a preference.

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
│  CONGRUENCE  ⟨state⟩   refs: ⟨ref⟩, ⟨ref⟩                   │
│              the ref is the test. Different data roots and  │
│              bands below are the system WORKING.            │
│  ┌── ⟨node⟩ ────────────────┐ ┌── ⟨node⟩ ─────────────────┐ │
│  │ ref        ⟨ref⟩ ⟨n back⟩│ │ ref        ⟨ref⟩ ⟨n back⟩ │ │
│  │ hub        ⟨state⟩ ⟨code⟩│ │ hub        ⟨state⟩ ⟨code⟩ │ │
│  │ preflight  ⟨n of n⟩      │ │ preflight  ⟨n of n⟩       │ │
│  │ identity   ⟨state⟩       │ │ identity   ⟨state⟩        │ │
│  │ ─────────────────────────│ │───────────────────────────│ │
│  │ OS disk    ⟨size⟩ ⟨n%⟩   │ │ OS disk    ⟨size⟩ ⟨n%⟩    │ │
│  │ data root  ⟨path⟩        │ │ data root  ⟨path⟩         │ │
│  │            ⟨size⟩ ⟨n%⟩   │ │ backup vol ⟨path⟩ ⟨size⟩  │ │
│  │ ─────────────────────────│ │───────────────────────────│ │
│  │ band       ⟨range⟩       │ │ band       ⟨range⟩        │ │
│  │ projects   ⟨n⟩ | n/a     │ │ projects   ⟨n⟩ | n/a      │ │
│  │ stale      ⟨n of n⟩      │ │ stale      ⟨n of n⟩       │ │
│  │ ─────────────────────────│ │───────────────────────────│ │
│  │ backup     ⟨state⟩       │ │ backup     ⟨state⟩        │ │
│  │ reclaim    ⟨state⟩       │ │ reclaim    ⟨state⟩        │ │
│  │ ─────────────────────────│ │───────────────────────────│ │
│  │ here       ⟨projects⟩    │ │ here       ⟨projects⟩     │ │
│  └──────────────────────────┘ └───────────────────────────┘ │
│  FLEET TOTALS — stated separately, NEVER summed             │
│    ⟨n⟩ projects · ⟨n⟩ registered · ⟨n⟩ acknowledged         │
│    a node whose registry did not answer is UNKNOWN,         │
│    never current, and never a zero.                         │
└─────────────────────────────────────────────────────────────┘
```

**Every cell above is `⟨ ⟩` on purpose.** An earlier draft of this same card
hardcoded commit refs, disk sizes, a preflight score and a band — inside the
section that states the rule that it must not. That is how literal a habit this
is.

Three rules this card enforces, carried straight from `fleet-status.py`:

- **`n/a` and `0` are different answers and only one is information.** `_registry_cells()` (`tools/fleet-status.py:112`) refuses to print `0` for a node whose registry did not answer. The card must refuse the same way — a grey `n/a`, never a green `0`.
- **Never one fleet-wide stale total.** Summing a node that answered with a node that did not produces a number that reads as though both were checked.
- **A blank ref cell reads as "no drift".** `ref=${REF:-?}` exists because `echo` succeeds whether or not `git` printed. The card renders `?`, and `?` is a red state.

## VI.4 Project view — one standing record

Source: `GET /api/registry/<project>`, its `/diffs`, and tickets. Which of
those answer on a given node is `curl -s <hub>/api/sitemap`, not this line.

```
┌─ ⟨project⟩ ──────────────── home: ⟨node⟩ ⟨server_id⟩ ───────┐
│ state  ⟨state⟩          status  ⟨dev|staging|production⟩    │
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
│   band offered   ⟨from /api/admit⟩                          │
│   actually bound ⟨read from the machine⟩                    │
│   neighbours     ⟨other projects on this box⟩               │
│   MIGRATION not cutover. Neither is urgent. Neither is a    │
│   violation.                                                │
│                                                             │
│ ─ DATA ─────────────────────────────────────────────────── │
│   ⟨data root⟩/⟨project⟩/  db/ media/ cache/ releases/       │
│                           public/ private/                  │
│   anything under public/ is open; everything else needs a   │
│   session. The filesystem declares intent; the serving      │
│   layer enforces it.                                        │
│                                                             │
│ ─ CONTINUITY ───────────────────────────────────────────── │
│   ⟨volume or path⟩  ⟨size⟩  ⟨in the nightly set?⟩           │
│   baseline    ⟨last restore proved, or NEVER⟩               │
│               A backup nobody has restored is a belief.     │
│                                                             │
│ ─ ACKS (append-only) ───────────────────────────────────── │
│   ref            answer                          at         │
│   ⟨ref⟩          ⟨answer⟩                        ⟨ts⟩       │
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
│   filed BEFORE self-fixing. An unrecorded self-fix is       │
│   indistinguishable from drift six weeks later.             │
└─────────────────────────────────────────────────────────────┘
```

Left half is derived and re-read every load. Right half (claim, acks, dispositions) is stored because it is not re-derivable. The panel border is where that line falls, deliberately.

## VI.5 Bulletin view — the read/unread matrix

The single most useful screen here, and none of it is built.

```
┌─ BULLETINS ─────────────────────────────────────────────────┐
│           ⟨project⟩  ⟨project⟩  ⟨project⟩  ⟨project⟩        │
│  #⟨n⟩ ⟨subject⟩   ⟨●⟩      ⟨○⟩       ⟨○⟩       ⟨·⟩          │
│  #⟨n⟩ ⟨subject⟩   ⟨○⟩      ⟨○⟩       ⟨·⟩       ⟨·⟩          │
│                                                             │
│  ● acknowledged   ○ delivered, unread   · not a recipient   │
└─────────────────────────────────────────────────────────────┘
```
```

**The PIN is masked on the operator's screen on purpose.** Its whole value is that it proves a project read the text; an operator who can see it can hand it over, and then it proves nothing. Reading the PIN out to a project is being the messenger again.

## VI.6 Port map — 12 lanes, fleet-wide

Lanes verbatim from `PORT_LANES`, `hub/kernel/collect.py:398`.

The lane table and the band allocations are **not written here.** Two copies of
a port table in this repo disagreed with each other and with the machines, and
admission handed out ports inside another stack's reserved lane for months
because two places answered one question.

```bash
curl -s <hub>/api/ports              every bound port, with lane and owner
curl -s "<hub>/api/admit?project=X"  the band a project may bind inside, derived live
```

`/api/admit` scans the live port map at the moment you ask and returns a band
with nothing bound in it. A table cannot do that.
│                                                             │
│ ─ OFFSET inside a band — suggested, NEVER enforced ──────── │
│   x00-x19 UI      x20-x39 API     x40-x59 data              │
│   x60-x79 workers x80-x99 dev/preview/debug                 │
│   The band is the boundary. The split inside it belongs to  │
│   the project. Outgrowing 100 is a ticket, not a violation. │
│                                                             │
│ ⚠ UNRESOLVED, shown on this screen and never hidden:        │
│   a band was DEPLOYED to one box before any project was     │
│   told. A second band replaced it on a branch, also untold. │
│   No project knows either number.                           │
│   Showing the unresolved state IS the screen's job. A card  │
│   that hides a contradiction is worse than no card.         │
└─────────────────────────────────────────────────────────────┘
```

Collision detection is not new work: `/api/ports` already scans the sockets and
classifies by lane. This screen is that projection, plus an allocation store.

**Reading the sockets rather than the container list is the point.** A service
installed outside Docker never appears in `docker ps`; only the socket view sees
it, so only the socket view can tell you a port is taken.

## VI.7 What the operator ACTS on from here

Four buttons. Every one goes to the **server**. None goes to a project.

```
ACTION                 WRITE VECTOR
─────────────────────  ────────────────────────────────────────────
trigger a project      renders the exact sentence the operator says
to read                out loud, plus which server. Emits NOTHING.
                       The UI is a teleprompter, not a transmitter.

publish a bulletin     POST -> bulletins store. Scope broadcast or
                       targeted. Mints the PIN per (bulletin,
                       project), pins the version, and REFUSES to
                       publish without "the one thing they do".

promote a release      stage -> promote, with rollback recorded as
                       its own state rather than as an absence.

release a checkpoint   WHAT A CHECKPOINT IS, IS UNDECIDED. A ref, a
                       backup, or both pinned together. This button
                       must not ship before that word means one
                       thing — a control whose label is ambiguous
                       makes the ambiguity permanent.
```

**Two absences are deliberate, and both are operator decisions, not tasks:**
whether gate enforcement is ever armed, and whether admission **rejects** an
out-of-band claim or merely **records** a violation. **A UI button is not the
place to decide either.** `python3 hub/tools/atlas.py` lists them among the
operator decisions; nothing proceeds on them by itself.

## VI.8 Read vectors — one panel, one owner, one source

Non-monolithic means each panel is a separate file under `hub/ui/views/`, one registry entry each, and none fetches on behalf of another.

| Panel | Owner file | Source | Dimension |
|---|---|---|---|
| fleet cards | `views/fleet.js` | `fleet-status.py --json` | all seven |
| congruence banner | `views/fleet.js` | ref set comparison | Identity |
| disk / data root | `views/storage.js` | `/api/receipt` | Substrate |
| standing record | `views/project.js` | `/api/registry/<p>` | Tenancy |
| diffs + dispose | `views/diffs.js` | `/diffs`, `/dispose` | Tenancy |
| rung ladder | `views/rungs.js` | acks table | Account |
| bulletin matrix | `views/bulletins.js` | bulletins store | Account |
| port lanes | `views/ports.js` | `/api/ports` | Substrate |
| band allocation | `views/bands.js` | the allocation store | Admission |
| backup state | `views/continuity.js` | timers + manifest | Continuity |
| actions drawer | `views/act.js` | writes only | — |

Which of these exist is `python3 hub/tools/check-views.py`, which asserts the
registry and the renderer against each other **in both directions** — the
status column that stood here could only ever assert one.

One panel, one owner. The failure this avoids is the one `ui/registry.js` already documents: a view that lived in four places drifted — `survey` had a renderer and no metadata, `_browser_old` was dead code in a switch. Adding a panel here is one file plus one line.

## VI.9 `hub/ui-next/` — stated plainly

`hub/ui-next/` is a **clone of another app's shell**, copied byte for byte from
that app's UI source on its own server: the shell components, the UI primitives,
the layout components and only the stores those reference, plus its config, plus
an emptied registry and widget stubs written here.

**The source app was not modified, and that was verified rather than assumed** —
its containers still running with zero restarts, zero files changed under its
directory, its newest source mtime unchanged. Law XII: read to describe, never
change; and when you have to prove you did not change it, prove it.

Sizes are not recorded here. `git ls-files "hub/ui-next/*"` — two earlier
statements of them in this repo disagreed with each other.

Whether anything imports it yet is a `grep`, not a status line — it has been
wrong here before. It still carries the source app's shape in two places:
`useUserStore` is that app's auth model, not ServerHub's sessions, and
`useScannerStore` is a barcode toggle ServerHub has no use for. Both must be
replaced before it ships; both stay until then, because a template that does not
build is not a template.

**`ui-next` is adopted as the direction; *when* is not settled.** The trade is
legible: the existing frontend is one global script scope with a legacy switch
that `ui/registry.js` is mid-way through dismantling; `ui-next` is a modern shell
with no content and a borrowed auth model. Adopting it means the screens above land in React; not adopting means they land as `ui/views/*.js` files behind the existing registry, which is the path already half-walked and already reversible per view. Both are defensible. Neither has been chosen, and the four screens above are written to be buildable either way — they are panel boundaries and data vectors, not components.

---

# PART VII — CORRECTIONS APPLIED, 2026-09-24

**This part is HISTORY and is the most useful thing in the document.** It is a
dated record of sixteen claims this repo made about itself that were wrong, and
what re-deriving each one from the tree produced instead.

**The corrected values are deliberately not reprinted.** They were facts on
2026-09-24 and several are already wrong again — which is the whole point. What
is kept is **the class of error**, because those recur:

| Class of error | What it looked like |
|---|---|
| **One number, several copies, all different** | five files stating the route count; three stating how many routes declared a gate. Every copy disagreed with every other and with the route table |
| **A number measured once and cited forever** | a file census and a line count quoted in three documents, all tracing to one afternoon's `git ls-files` |
| **Two correct numbers for two different things, read as a contradiction** | a file's total line count vs the line count of the script block inside it. Both right; neither wrong; the document treated one as an error |
| **A count read from a stale local ref** | a commit-distance figure taken against a local `master` that had not been fetched, overstating the gap by roughly double. It was then quoted twice more before anyone re-ran it |
| **A grep result quoted without its command** | a claim that a term appeared once in the codebase. It appeared zero times — the one hit was a different word in a comment |
| **Status asserted for code that was neither committed nor routed** | three endpoints tabulated as live. They existed only in an uncommitted working tree and had no route entry, so they were on no server at all |
| **A constant standing in for a derived value** | a staged-change notice hardcoded and gated on one band number, so it announced a move already completed on one box and announced nothing at all on the other |
| **A document contradicting the code it documents** | an acknowledge endpoint that reads a code ref while the document told projects to post a bulletin and a PIN. A project following the document would have posted a PIN, received `ok:true`, and acknowledged nothing |

That last one is the worst kind, and it is worth stating on its own:

> **A call that succeeds while doing nothing is the exact failure mode this
> whole system exists to remove, reproduced inside it.** A refusal is
> information. A false `ok` is not.

The method, which does not expire: **where two sources disagreed, the tree
decided.** Not the older document, not the more confident one, not the one that
had been quoted most.

**Deduplication is the editing rule, and it is why the corrections above were
findable at all.** Each statement lives in exactly one place and is referenced
from everywhere else:

- the premise and the `PROJECT ↔ HUB` non-edge — **I.1**
- the ladder, in full — **II.1**
- the congruence rule — **I.2**; its display rules — **VI.3**
- the two-readers defect — **IV.5**
- the project-facing command surface — `hub/SERVER-COMMANDS.md`, once

**A fact stated twice is a fact that will disagree with itself.** Every entry in
the table above is an instance of that, and the fix is never to reconcile the
copies — it is to delete all but one, and then to replace that one with a
command.

---

# PART VIII — WHERE THIS STANDS, AND THE SEQUENCE OUT

## VIII.1-VIII.3 — the three inventories are gone

Three lists stood here: what is LIVE, what is CODE-ONLY, what is DESIGN. Each
was a snapshot of one afternoon, and each rotted at a different speed. Keeping
them was the same defect this document spends Part VII cataloguing in other
files.

```bash
python3 hub/tools/atlas.py        what exists, and which planes the installer produces
python3 hub/tools/atlas.py --parts  every part, classified by what the code does
python3 hub/tools/edges.py        every external joint, and what binds each write
python3 hub/tools/step.py         which step of the build order we are on
python3 hub/tools/tracks.py       which track is next, and what gates it
python3 hub/tools/matrix.py       the five checklists, asserted against the machines
python3 hub/tools/situation.py    what is serving, exposed, and what could not be seen
bash bootstrap.sh --check         is this node at the installer's standard
curl -s <hub>/api/sitemap         the route surface, generated from the route table
```

Every one of those ends by naming **what it could not see**. A section skipped
by a flag registers as a blind spot, and a clean report with a hole in it is
more dangerous than a failure, because nobody investigates a pass.

**The three categories are still worth naming**, because they are different
kinds of nothing and get confused constantly:

| | Means | The mistake it invites |
|---|---|---|
| **live** | deployed and answering on at least one node | assuming "at least one" is "both" |
| **code-only** | in the tree, not deployed, not routed, or on one box only | reading a merged branch as a shipped feature |
| **design** | prose with nothing executable behind it | citing a document as evidence the thing exists |

A handler with no route entry is code-only, not live — one was written, given a
telescope code and documented, and the route line was never added, so the single
address that answers *"what runs where, and is it the same build"* returned 404
on both servers while every document said it existed.

## VIII.4 The sequence to running on both servers

**Ordered by what unblocks the most, not by effort.** Every step is verifiable
by a command, and **nothing in a later stage should start before the stage
before it is true.** That ordering is the doctrine; `python3 hub/tools/step.py`
and `python3 hub/tools/tracks.py` say where the work actually is.

No counts appear below. Two earlier drafts of this list gave two different
commit totals for the same merge, and neither was re-derived before being
quoted again.

**Stage 0 — stop the bleeding in the tree. No server changes.**

1. **Collapse the two readers of the disks into one.** Until this lands, two
   endpoints can give a project two different pictures of the same machine, and
   neither is marked as the lesser. The fix is a deletion, not an addition.
2. **Commit what is only in the working tree.** Nothing below can be deployed
   while it exists on one laptop. *"Every code change commits and pushes
   immediately, no batching"* is a standing rule and this is what breaking it
   costs.
3. **Route the orphan handlers, or delete them.** A handler with no route entry
   is not a feature; it is a 404 with a telescope code. Deciding its gate level
   is part of routing it, not a follow-up.
4. **Generate the sitemap from the route table** through the seam that already
   exists for it. This kills the second, hand-maintained route list outright —
   and with it the omissions nobody could see, because the drift was
   omission-only.

**Stage 1 — make the two servers the same build.**

5. **Put both boxes on one tailnet.** Needs sudo, at the box. It is the operator's
   step and nothing routes around it.
6. **Merge and deploy to both.** After this the project-facing routes exist on
   both servers and both derive the same band floor. Before it, one box answers
   questions the other 404s, and a project's answer depends on which it asked.
7. **Run the installer on the box that was not produced by it**, so it gets the
   backup and reclamation timers. A node holding the trust root and no backups
   is the one combination that must not persist.
8. **Verify congruence.** Refs must match; data roots must not. A check on
   values cries wolf and is ignored within a week.

**Stage 2 — make an acknowledgement mean something.**

9. **Add the PIN to the acknowledgement.** Until it lands, an ack proves only
   that a project was *told* — not that anyone read anything. It is a field
   change, not a subsystem.
10. **Build the bulletin store and its routes.** The staleness engine already
    exists and is pointed at a code ref; repoint it at a bulletin.
11. **Fix or delete the staged-change notice.** A hardcoded `_pending()`
    announces a move already completed on one box and announces nothing on the
    other. Drive it from the release records as its own docstring promises, or
    remove it — a notice that cannot report the next change is worse than none,
    because it looks like one.
12. **Reconcile the project-facing document with the code.** The endpoints it
    named must be the endpoints that exist. *A call that succeeds while doing
    nothing is the exact failure this project exists to remove, reproduced
    inside it.*

**Stage 3 — turn the mechanism on.**

13. **Publish the first bulletin** — *"you are already in this server"* — to both
    boxes, and point the projects at it **one at a time, out loud.** The operator
    is the trigger by design; a trigger that fires itself is a poll.
14. **Take the first acknowledgement.** The number that matters is not a route
    count or a line count. It is the acks table going from zero rows to one.
15. **Then, and only then**, build the ticket store, the backup labels and the
    deploy-to-checkpoint emitter — each a table plus one emitter, none of them a
    new subsystem.

**The honest close.** The project-facing surface is largely built and has been
used zero times. The four things that would make it mean anything — the PIN, the
bulletin, the ticket, the gate — are four tables and the edges that write to
them.

**Nothing on this page is blocked by difficulty.** It is blocked by work sitting
uncommitted, by two servers on different networks, and by no project having ever
been told any of it. Those are three different kinds of blocker and only one of
them is engineering.
