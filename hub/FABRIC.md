# The Fabric — ServerHub by dimension

If this were started fresh tomorrow, this is the shape it would take.

It is also the cleanup plan, because every mess in the current build is the same
mistake: **a dimension with two sources of truth, or none.**

---

## How to read this

There are **seven dimensions**. A machine is fully described when all seven are
answered. Each one has exactly four things, and the fourth is the one that was
always missing:

| | |
|---|---|
| **Question** | what it answers about the machine |
| **Source** | the *one* place the answer comes from — usually the machine itself |
| **Projection** | how it is rendered for a human, a project, or another node |
| **Assertion** | the executable check that fails when it stops being true |

> **One source, one projection, one assertion.**
> Two sources is the bug. No assertion is the bug that hides the bug.

---

## The seven dimensions

### 1. Identity — *what am I?*

A machine must be nameable across reboots, renames, reimages and IP changes.

- **Source** `/etc/machine-id` (hardware) → `server_id` (authoritative, reissuable)
- Two identifiers on purpose: a reimaged box keeps its `machine_id` and gets a new `server_id`, which makes the reimage *detectable*. One identifier cannot tell you that.
- Identity also carries **which fleet this machine belongs to** — mesh, zone, role, and the trust root that signs its claims.
- **Projection** `/api/receipt?for=fleet`
- **Assertion** identity file exists, `machine_id` non-empty, mesh declared

### 2. Substrate — *what am I made of?*

Disks, ports, memory, network. The physical facts.

- **Source** the machine, read at call time — `findmnt`, `ss`, `/proc`, the Docker daemon
- Never a constant. Hardware varies: one disk, two, a large empty mount, none. A hardcoded path is a guess about hardware, and it is wrong on the second machine.
- **Projection** `/api/receipt` (the default depth)
- **Assertion** no mount unaccounted for; reported totals equal the sum of real filesystems

### 3. Tenancy — *what lives here, and who owns each thing?*

Every running thing belongs to exactly one project, and that ownership is readable from the machine.

- **Source** container labels — `com.ksg.project`, `owner`, `role`, `data`
- Ownership is declared *by the thing itself*, not recorded in a registry beside it. A registry drifts; a label travels with the container.
- **Projection** projects grouped, plus everything nothing claims
- **Assertion** `docker ps --filter label=com.ksg.project=X` returns exactly that project's containers — and nothing on the host is unclaimed

### 4. Admission — *what may a newcomer take?*

The rules handed to something that has just arrived and knows nothing.

- **Source** derived from Substrate and Tenancy — free ports from the live port map, data paths from the live disk map
- The newcomer **asks**; it does not read a document and hope. This is the dimension that makes a server usable by someone who has never seen it.
- **Projection** `/api/receipt?for=project`
- **Assertion** the band it hands out collides with no reserved lane; the data path it names exists and is writable

### 5. Continuity — *what survives losing something?*

Backups, retention, reclamation. What is still here after a disk, a container, or a mistake.

- **Source** Substrate decides where — a backup target must be a **different physical device** from the data it protects, and that is checkable, not assumed.
- Data has classes, because value differs: `db` is irreplaceable, `media` is large and static, `cache` is regenerable and should never be copied.
- Retention prunes **only after a successful run**. Otherwise a streak of failures quietly deletes the last good copy.
- **Projection** a backup manifest; findings in the attention block
- **Assertion** a backup exists, is recent, restores, and does not share a device with its source

### 6. Authority — *who may act, and through which door?*

- **Source** the request path proves as much as the credential does. Arriving over the tailnet is not the same as arriving from the open internet, and the trust is the *path*, not a header — anything on the network can forge a header.
- Two doors: local login always works and depends on nothing external; the public door is Access + SSO. Getting in the building is not getting into the safe.
- **Credentials are never stored here.** Pointers only. The node holds no key and creates no hostname.
- **Projection** which door, which role, what that permits
- **Assertion** every route's declared gate is actually applied; sessions survive a restart

### 7. Account — *what happened, and how much does it matter?*

- **Source** every other dimension emits when something changes. One event stream, one severity scale.
- An observation becomes an event, an event is **weighed**, and weight composes upward: a node is as hot as its worst finding, a fleet as hot as its worst node.
- This is what makes N machines answerable in one look. Without a shared scale, "is this node worse than that one" cannot be asked.
- **Projection** one number, decomposing into exactly what made it hot
- **Assertion** every emitter uses the one scale; nothing emits a severity the compiler does not know

---

## The two laws that cut across all seven

**A. One projection, requested at a depth.**
Not one endpoint per audience. Six endpoints answering *"what is true about this
machine"* is six things that drift.

```
/api/receipt                  the machine          (Substrate + Tenancy)
/api/receipt?for=project      + Admission
/api/receipt?for=fleet        + Identity
/api/receipt?for=authority    + what the vault must provision
```

The same rule governs the interface: one registry, one entry per view, nav is
data. Adding a view must never mean editing four places.

**B. Every dimension owns an assertion that can fail.**
A dimension without one is a dimension nobody is checking. `MASTER.md` said
*"7. Backup — set up before adding data"* and could not be wrong, because nothing
executed it — so a server ran for months with no backups while the document
looked correct.

**C. Universal by default, specialised by recognition.**

Every dimension must work on a service the hub has never heard of. Recognising a
service adds what cannot be observed; it never gates what can.

```
observable  →  handled generically, always
                 name · image · ports · labels · health · logs · volumes

recognised  →  enrichment, when the image matches something known
                 which port is the UI · health path · docs link
                 what its data directory means · how to back it up safely
```

The current build has this inverted. `kernel/collect.py:338` carries **18
hardcoded services** with real metadata, and everything else falls through to:

```python
'name': cname,
'description': f"Auto-discovered — {info['image']}",
'group': 'Discovered',
```

So a service the hub knows is a first-class citizen and a service it does not is
a stub — which makes every `keynox-*` container on fks-services second-class on
its own machine. Worse, that list is a record maintained *alongside* the machine,
which is Law I of the constitution violated in the one place it is most visible.

The inversion: **generic treatment is the floor, not the fallback.** Recognition is
a lookup keyed by something observable (the image), returning only what cannot be
derived. Miss the lookup and you lose a docs link, not a citizen.

This matters most for Continuity. "Back up a Postgres volume" and "back up a
Redis volume" are not the same operation — one wants `pg_dump`, one wants an RDB
snapshot, and copying the data directory of a running database produces a file
that looks fine until you need it. Recognition is how a generic backup job does
the right specific thing, without a list of every database anyone might install.

---

## Where the current build violates this

Every row was verified against a running machine in September 2026.

| Dimension | The violation | Evidence |
|---|---|---|
| **Identity** | no `mesh`/`zone` field, so two meshes look like one fleet with unreachable members | `kernel/identity.py`; ksgcohub reports `"nodes": 0` with no central and no explanation |
| **Substrate** | **six** sources for one question; reported `98G` on a machine carrying `557G` | `/api/status`, `/storage`, `/receipt`, `/context`, `/node`, `/admit`; fixed in `b704e97` |
| **Tenancy** | 12 projects carry no label; babyhelp's acceptance test returns **0 of its 3** containers | `docker ps --filter label=com.ksg.project=babyhelp` |
| **Admission** | handed out ports inside Supabase's reserved lane, and named a data path on the wrong disk | two contradicting bands, `collect.py` vs `node.py`; fixed in `09f3a6a`, `dfe4d67` |
| **Continuity** | did not exist. Then existed on the same device as the data. On the other machine, a backup script deletes old dumps even when the dump failed | `fdc4276`, `c7042a7`; `/srv/backups/metaforge/backup.sh` has no `set -e` and an unconditional `find -delete` |
| **Authority** | 52 of 73 routes declare a gate, **none are enforced**; sessions are an in-memory dict; logins are never recorded | `HUB_ENFORCE_GATES`; `post_auth_login` never calls `log_activity` |
| **Account** | **five** severity vocabularies, no shared scale, so nothing composes | `storage.py` high/warn/info · `fleet.py` five states · `users.py` a failure counter · `log.py` a level · container events |
| **(Law C)** | 18 services hardcoded; everything else is a `'Discovered'` stub on its own machine | `kernel/collect.py:338`, plus 8 hardcoded port→name lines |

Read down the *violation* column: it is the same sentence seven times.

---

## The cleanup, in dimension order

Dimensions are not equally urgent. Order by what is *unrecoverable* if wrong,
then by what everything else depends on.

| # | Dimension | Do |
|---|---|---|
| 1 | Continuity | prove a restore. A backup nobody has restored is a belief |
| 2 | Authority | persist sessions, record logins, then arm the gates |
| 3 | Substrate | six endpoints → one receipt at four depths |
| 4 | Identity | `mesh` and `zone` in the identity file; zone from fleet config, not a per-run flag |
| 5 | Tenancy | label the 12 unclaimed projects; make the acceptance test pass for babyhelp |
| 6 | Account | one severity scale, then the weight compiler |
| 7 | Admission | folds in free once 3 and 5 are done — it is derived from them |
| — | *Law C* | invert the service table: generic floor, recognition as enrichment keyed by image. Do it inside Continuity (1), where getting it wrong corrupts a database backup |

Then delete: dead code, dead docs, dead tools. A project that carries dead
weight into its next phase is how the next phase fails.

---

## What a fresh build would do differently

Five things, and none of them are about code quality.

**1. Assertions before features.** The first file would be the preflight, not the
server. Every capability added afterwards brings its assertion with it, or it does
not land.

**2. One receipt from day one.** The six shapes did not arrive by decision — each
was added for a caller, and nobody ever removed the previous one. Projections are
free; sources are expensive.

**3. Continuity before content.** Backups configured before the first byte of user
data exists. `MASTER.md` already knew this — *"set up before adding data"* — and it
still did not happen, because knowing is not asserting.

**4. Recognition never gates.** The service table would be an enrichment lookup
from the first commit, not a roster of citizens. Every list of known things is a
record maintained beside the machine, and those drift by definition — so the only
safe list is one whose absence costs nothing.

**5. Two machines from the start.** Every wrong assumption this project made was
invisible on one machine and obvious on two. A 4.4TB disk mounted at `/backup`
broke a heuristic that had looked perfectly reasonable for weeks. Hardware
disagreement is the cheapest reviewer available.

---

## The test this document must pass

If a dimension in this file has no assertion in `hub/tools/`, this file is
describing an intention rather than a system — and by its own second law, that is
the failure mode. Today:

```
Identity      partial   install-preflight: identity
Substrate     yes       storage-preflight, check-views
Tenancy       no
Admission     partial   asserted by hand, not by a tool
Continuity    partial   backup target checked; a restore never is
Authority     no
Account       no
```

**Three of seven.** That number is the honest measure of this project, and it is
the number to move.
