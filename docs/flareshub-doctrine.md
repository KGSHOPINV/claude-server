# FlareSHub — Doctrine

> Binding. Where this document and the machine disagree, **the machine wins and
> this document is wrong** — but where this document and a *preference*
> disagree, the document wins. That is what makes it doctrine rather than notes.

Companion to `hub/CONSTITUTION.md`, which governs ServerHub as a whole. This one
is narrower: what FlareSHub *is*, the entry it sits behind, the console it
serves, the unison it has not finished, and what "done" means for each.

---

## 0. The rule this document obeys about itself

**It contains no counts, no statuses, and no ticks.**

Not as a style choice. `docs/flareshub-checklists.md` was hand-marked on
2026-09-21; five days later **23 of its 68 rows were wrong, in both
directions** — and one row that was marked correctly got contradicted anyway,
because its stated *reason* compared the wrong two things. Five separate files
state the route count. All five disagree and all five are stale. `TASKS.md` has
been stale since 2026-09-16. `CAPABILITIES.md` claims a route count and a module
count that are both materially wrong.

So every question of fact here is answered by **a command, not a sentence**:

| Question | What answers it |
|---|---|
| What plane are we on, and what is hand-built? | `python3 hub/tools/atlas.py` |
| Where is the build order? | `python3 hub/tools/step.py` |
| What do the five checklists actually say today? | `python3 hub/tools/matrix.py` |
| What is serving, what is exposed, what could I not see? | `python3 hub/tools/situation.py` |
| What external systems do we touch, and what binds each write? | `python3 hub/tools/edges.py` |
| Is this node at the installer's standard? | `bash bootstrap.sh --check` |
| Which track is next? | `python3 hub/tools/tracks.py` |
| Is a telescope code free? | `python3 hub/tools/atlas.py --codes` |

If you want to add a fact to this document, add a check to a tool instead.

---

## 1. What FlareSHub is

Not a hub. **A regional manager.**

```
FlareVault    THE AUTHORITY    who, and whether
FlareSHub     THE OPERATOR     where, how much, and what is actually true
```

FlareVault still owns it. FlareVault simply does not have to *operate* it.
Different toolset, same chain of command.

FlareSHub does five things, and each one is checkable:

| Verb | Meaning |
|---|---|
| **OBSERVES** | console monitor — containers, storage, drift, health |
| **RUNS** | its own services, host-level, never inside Docker |
| **ADMITS** | the authority for projects — ports, lanes, bands, receipts |
| **REPORTS** | feedback-oriented — bulletins, tickets, the exchange |
| **REPLICATES** | the facilitator for new servers — the template, one to one |

Anything that is not one of those five is not FlareSHub's job. When in doubt
about a proposed feature, name which verb it serves. If it serves none, it
belongs to FlareVault, to Metaforge, or to nobody.

---

## 2. The laws

`hub/CONSTITUTION.md` holds the original set. These were added or sharpened by
what broke, and each one is here because something failed without it.

### I. Derive, don't maintain
A number that is typed is a number that will be wrong. The route count,
the module list, the plane table, the fleet register — all derived.

### II. Assert, don't describe
A document has no failure mode. A check does. This is why the tools exist and
why `docs/` is being drained into them.

### III. Report, never repair
Every instrument reports. None of them fixes anything. The operator decides.
An instrument that repairs becomes a writer, and writers need owners.

### IV. One writer per fact
A node is the only writer of its own state. FlareVault is the only writer of
identity. The registry is the only writer of admission. Two writers for one
fact is a split brain, and it is the failure this whole architecture is shaped
to prevent.

### V. A plane is not done until the installer produces it
Something that works on both servers because both servers were configured **by
hand** is *applied*, not built. The third server is what proves which — and by
then whoever typed it has forgotten. `atlas.py` scores every plane twice and
prints `HAND-BUILT` for the gap.

### VI. Bound is not authenticated
`machine_id` binds a beat to a record. It does not prove the sender *is* that
machine, because the payload carries it. Say `bound_by`, never `authenticated`,
until a join token exists. **Renaming a weak guarantee into a strong one is a
lie you will have to un-teach.**

### VII. A blind spot is not a pass
Every instrument ends with *what I could not see*. A section skipped by a flag
registers as a blind spot. A clean report with a hole in it is more dangerous
than a failure, because nobody investigates a pass.

### VIII. Only projects are containers
FlareSHub's own services run host-level. `cloudflared` is a host systemd
service for a stated reason: **if Docker dies, the way in must survive.** This
is not a preference — a monitor inside the thing it monitors dies exactly when
it is needed. It is also why "what does nothing claim?" has a clean answer:
containers belong to projects, so anything unclaimed is drift.

### IX. Congruence is same code ref, never same values
Two servers legitimately differ in container counts, disks and uptimes —
*because each was read correctly*. A check on values cries wolf and is ignored
within a week.

### X. Key on what does not change
Peers keyed by URL made every moved peer a dead peer. Register engines and
records against `machine_id`, with the mutable thing as an attribute.

### XI. Merge, never replace, on a shared surface
A tunnel's ingress, a zone's DNS. Refuse the write if a hostname would vanish.

### XII. Never touch another project
fksinv, babyhelp, keynox/metaforge, FlareVault. Read to describe. Never change.
**"We stopped using it" is not "it is dead."** Check whose it is before removing
anything.

---

## 3. The entry chain — five rungs

```
flarevault.dev/            splash. PUBLIC. login at the top right.        FV
  │ login
FlareVault internal hub    FV's own lobby and its utilities               FV
  │ select FlareSHub   (a PIN gate here is viable — it is layer 3)
FlareSHub MAIN CONSOLE     the topography console                        OURS
  │ select a server
that server's console      more toolsets, because now you are inside     OURS
```

**Ownership is not negotiable per-rung.** FlareVault builds the landing page,
`login.<zone>`'s Access policy, the layer-3 step-up and layer 4. ServerHub
builds login layers 1 and 2, the dashboard rendered by JWT role, the console
drill-in, and **layers 3 and 4 as empty hooks only.**

An empty hook **refuses**. A hook that returns true is an open door wearing a
hook's name.

### The layers

| Layer | What it gates | What satisfies it |
|---|---|---|
| 1 | read the fleet | a session |
| 2 | console, containers | an **admin role** — what logging in earns |
| 3 | destructive | a **step-up**, proved at the moment of use |
| 4 | vault, kill switch | FlareVault's |

Deeper means prove more. **Google gets you in the building, not into the safe.**

Level 2 and level 3 are different questions and must never be asked of the same
check. One call answering both got both wrong at once.

### Names that are not ours
`dashboard.flarevault.dev` belongs to FlareVault. So does the apex landing page
we currently hold with a placeholder. Do not delete, repoint, or "tidy" either.

---

## 4. Two consoles

- **Topography console** — the whole mesh. Manages the entry. Manages projects
  **from the reverse of all servers**: project-first across the fleet, not
  server-first.
- **Per-server console** — inside one box, with the tools that only make sense
  there.

They are different products sharing one file. See §5.

---

## 5. One UI, and it is stateless

**The console is stateless. The server is stateful.**

One UI artifact, byte-identical on every server. Nothing in it knows which
server it is on. What you see differs because the *underneath* differs, not
because the file differs. Per-server difference is **derived at runtime from
the modules and engines that box actually has** — which traces straight back to
what the installer put there. §5 and Law V are the same rule seen from two ends.

### Same-origin is not a preference

The lobby originally fetched its data and broke. A page served from one origin
calling a server behind a *different* Cloudflare Access app gets a cross-origin
redirect, which the browser reports as CORS. It was fixed by rendering the data
into the page server-side — which only works **because the same box serves
both**. A centrally-hosted UI hits that wall on every call, not once.

Four differently-shaped bugs — a CORS error, a dead card click, a login loop,
and a 404 through the lobby — were all that one wall.

### The cost, stated so nobody is surprised
A server on an old commit shows an old console. Nothing about the page reveals
it. `congruence` exists to make that visible; **that is what congruence is
for**, and it must never be allowed to answer `unknown` quietly again.

### Like Kubernetes, and not
**Like:** one identical artifact everywhere, a declared standard, convergence —
run the installer on any box and it comes to standard rather than needing a
rebuild.
**Not like:** there is no control plane. No etcd holding cluster state, no
scheduler placing work, no controller reconciling toward a spec. Every node is
its own source of truth.

So this is not orchestration. It is **convergence plus attestation**: every node
converges to the standard and attests what it is. Nothing reconciles on your
behalf. You see the drift and you decide.

### Central is a role, not a box
The topography console is stateless too — it assembles the fleet picture from
the zone's DNS records (*who exists*) and each node's own attestation (*what is
alive*). It does not own it. Whichever node you entered through is simply
holding the pen. **Every row must declare its source**: a DNS-sourced row means
*this server exists*; a heartbeat-sourced row means *this server is alive, and
here are its numbers*. Collapsing those two showed a dead box as healthy.

---

## 6. Identity — three identifiers

| Identifier | Source | Mutable? |
|---|---|---|
| `machine_id` | `/etc/machine-id` | no — the hardware anchor |
| `server_id` | `fvn_` + sha256(machine_id)[:6] | yes — reissuable |
| FlareVault ID | FlareVault mints it | account / tenant identity |

Two of them on purpose: a reimaged box keeps its `machine_id` and gets a new
`server_id`, **which makes the reimage detectable.** One identifier could not
tell you that.

There is no label to type. A name a human types is a name a human gets wrong —
that is how `hub-ksgco`, a typo, became permanent DNS pointing at a tunnel
nothing runs.

HS256, not RS256: the hub is stdlib-only by recorded decision, and FlareVault
agreed to issue HS256 so this code does not change when the issuer flips from
`self` to `flarevault`.

---

## 7. The DAG pairs

Flows run in opposite directions and pair up:

```
ADMISSION    ↓   server → /api/admit → project gets band, ports, receipt
EXCHANGE     ↑   project → outbox → bulletins/tickets → server records it

INSTALL      ↓   GitHub installer → Tailscale → registry admit → Cloudflare
REPORT       ↑   heartbeat → fleet record → topography console

AUTHORITY    ↓   FlareVault mints IDs, sets Access policy, grants credentials
ATTESTATION  ↑   node describes itself via /api/node
```

**THE INVARIANT: the reverse leg reports, it never writes what it does not
own.** That is Law IV, and it is the only reason a DAG may safely run both
ways. If both legs could write, one fact would have two sources of truth.

A corollary learned the hard way: **a write keyed by something the caller
supplied is not bound.** Bind it to something already recorded, or refuse.
The correct pattern is already written in this repo — `outbox.acknowledge`
refuses a mismatched name, and `registry.post_registry_dispose` scopes its
UPDATE. Copy those. Do not invent a third style.

---

## 8. Admitting a new server

```
1  GitHub installer     bootstrap.sh — hub running, at standard
2  Tailscale            mesh membership
3  registry admit       a known server admits it
4  Cloudflare           tunnel adopted, ingress merged, DNS, Access
```

Nothing public exists before the hub answers locally — `enroll.sh` already
refuses to publish a dead endpoint. Cloudflare admission is close to
self-healing: the box coming online is most of the event.

No ISO is required. A new server can be admitted from a known server. **But the
ISO is only possible once the installer converges**, because otherwise an ISO is
a snapshot of one box's luck. So the order is forced: `--check`, then converge,
then ISO.

### What the installer owes, and what it now has
Both were owed when this was written on 2026-09-27; both landed the same day,
and the entries stay because the *rule* each one serves is the doctrine — the
status is not.

- **A converging mode.** `bash bootstrap.sh --converge`. It repairs only what
  `--check` reports missing, prints every action before taking it, and refuses
  to touch anything `--check` calls a local addition. Without it, Law V can
  only be satisfied by hand — and a person maintaining sameness is an
  intermediary record stored where no tool can read it.
- **A decommission path.** `bash decommission.sh`, dry-run by default. A
  sibling script rather than a verb on `enroll.sh`, deliberately: a destructive
  flag must not sit four characters from `--dry-run` on a line retyped out of
  shell history, and cleanup outlives provisioning. Without it every dead
  server leaves a tunnel, a DNS record and an Access app behind forever.
  It refuses any name that is not `flareshub-fvn-<6hex>.<zone>`, and it keeps a
  tunnel that still serves anyone else.

---

## 9. Project unison — unfinished, and what finishing means

The exchange exists so that **the operator stops being the transport.** Today a
human pastes values between sessions. That is the thing being abolished.

**Stage 1 — the ranged exchange.** Intake, the project's blueprint back, the
server receipt out, review, and as many rounds as it takes. Goalposts are
*allowed* to move inside Stage 1; that is what Stage 1 is for.
**What ends Stage 1:** agreements met and understood on both sides. Consensus,
acknowledged, recorded. Nothing else.

**Stage 2 — admitted.** The registry entry exists, the project carries its
server ID and receipt, it has recorded the master for its server, and it
receives broadcasts when the server changes.

**Stage 3 — cross-server.** Deferred until per-server works.

### Where it stopped
At **one intake, end to end** — the last item of the build order. Nothing
technical blocks it. It needs a project to be told to walk it.

`python3 hub/tools/step.py` names the current step. It is the authority on this,
not this paragraph.

### Done means
- A project registers, is admitted, and **acknowledges** what it was sent.
- The acknowledgement is bound — a project cannot acknowledge as another
  project. (The PIN is per `(bulletin, project)`; it is rendered **into** the
  readout and is never a JSON field.)
- The operator carried nothing by hand at any point.

### What is still missing around it
The exchange has **no screen**. Routes exist; nothing renders them. Until a
board exists, the operator is still the transport by another route — which is
the one thing Stage 1 was built to end.

---

## 10. The new UI

Settled:
- **`ui-next` is adopted.** Looking like fksinv is fine.
- **Build on the PC, commit the output.** Servers stay dumb and serve
  byte-identical assets.
- **Mockups before any build.**
- **Order: unison → mockups → UI.** `tracks.py` enforces it.

Retired when it lands: `mobile.html` (which implements none of the views it
advertises) and the `app.html` monolith. Mobile resolves **in the registry**,
not in a second file and not at a second URL.

`hub/ui-next/` is a copy of fksinv's shell, already in this repo. **Work on the
copy.** Never read or write another project's source.

---

## 11. What done looks like

When FlareSHub is finished, all of the following are true, and each is a
question a command can answer:

1. **A new server is one command.** Run the installer, and it ends holding a
   live hostname, at standard, in the register, backed up. No hand steps.
2. **Running the installer again is safe** and brings an existing box to
   standard instead of needing a rebuild.
3. **Removing a server is one command**, and it leaves no tunnel, no DNS
   record and no Access app behind.
4. **Every plane scores installed**, not hand-built.
5. **One login** carries you from `flarevault.dev` to inside any server. No
   second password anywhere.
6. **One UI file** serves every box, and a box running an old one says so out
   loud.
7. **A project is admitted without a human carrying anything**, and its
   acknowledgement cannot be forged.
8. **The exchange has a screen**, so nothing waits on a person reading a log.
9. **Every write is bound** to something already recorded, or refused.
10. **Layers 3 and 4 refuse** until FlareVault fills them.
11. **Drift is visible** — build, storage, config, and enrolment, fleet-wide,
    from one address, without visiting a machine.
12. **Every fact in this repo is derived**, and `docs/` holds doctrine only.

Point 11 is the point of the whole exercise: **drift you can see.**

---

## 12. The one-sentence version

> FlareVault decides who; FlareSHub operates where — one installer makes every
> server the same, one stateless UI shows what each one actually is, one login
> reaches all of them, and nothing writes a fact it does not own.
