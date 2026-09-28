# FlareSHub — Blueprint

**The gain:** one address, one login, any server, on desktop or phone — and it
can tell you when something happens.

**This is a blueprint: why FlareSHub is shaped the way it is.** It carries no
counts, no status marks and no hostnames. Every question of fact is answered by
a command — see §6, and `docs/flareshub-doctrine.md` §0 for the full table.

---

## 0. Requirements (stated, non-negotiable)

These are the user's constraints. Any design that fails one of them is wrong,
however elegant.

**ONE DOMAIN ENTRY.** The domain is configured once, fleet-wide — not per
server. Every node derives its hostname from it. After the first time, the
domain is never typed again.

**BILATERAL FRONTEND.** One frontend works against any server. Not a UI per
node — the same build talks to whichever node.

**THE INSTALLER FINISHES THE JOB.** Running it ends with the server already
having a live domain name. Not "installed, now go configure Cloudflare."
`install → hostname → reachable` is one operation from the user's point of view.

**How a build fails these**, so the failure is recognisable rather than
argued: the enrolment step asking for the zone on every run violates one-entry;
enrolment being a separate step a human must remember violates
installer-finishes; a UI built per node violates bilateral. Target: one flow,
zone from fleet config, node name derived from machine-id.

Whether today's build clears all three is a question for
`bash bootstrap.sh --check` and `python3 hub/tools/step.py`, not for this page.

---

## 1. The three layers

Each owns something the others cannot do well. Put the seam anywhere else and
you get drift.

| Layer | Owns | Why it must be here |
|-------|------|---------------------|
| **Node** (ServerHub) | Its own machine-id, containers, ports, activity | Only the machine can read its own Docker daemon and `/etc/machine-id` |
| **Entry** (FlareSHub) | One address, one session, the aggregated view | The browser needs one origin; N origins means N logins and CORS |
| **Authority** (FlareVault) | Credentials, DNS, tunnels, port bands, the gate | Only thing outside the blast radius. Survives losing every server |

ServerHub doctrine, verbatim: *"Credentials — never stored here. Pointers only."*
and *"FlareVault configures DNS and tunnels. I just run the containers those
tunnels point to."* The node never holds a key and never creates a hostname.

---

## 2. How a node joins

```
  bootstrap.sh              hub running on :8765, admin seeded
       │
       ▼
  enroll.sh --zone Z
       │  reads /etc/machine-id            → the stable key, AND the node's name
       │  verifies CF token                → refuses if invalid
       │  refuses if hub not answering     → never publish a dead endpoint
       ├─ create/reuse tunnel  (idempotent)
       ├─ DNS  <derived name>.Z → <tunnel>.cfargotunnel.com
       ├─ Access app on that hostname      → nothing public without a gate
       ├─ attach the policy                → a warning is not a step
       ├─ cloudflared as a HOST service    → survives Docker dying
       └─ ~/.flare/node.json               → facts only, no credentials
       │
       ▼
  node is addressable by that name and describes itself at /api/node
```

The name is **derived, never supplied.** A label a human types is a label a
human gets wrong, and the wrong one becomes permanent DNS.

The API token is used during the run and discarded. The only persisted
credential is cloudflared's, scoped to that one tunnel.

**Changing domain = changing the zone, once, fleet-wide.** Adding a server is
the same command on a different box. That is the whole turnkey property, and it
holds only because no hostname is hardcoded anywhere — including in this file.

---

## 2b. What a node must be true about itself

Enrolment publishes a hostname. It should not publish a machine that cannot
hold what gets put on it — so the same run that creates DNS has to settle the
storage question first.

This section exists because it was missing. **Recorded 2026-09-22, as the
evidence for the rule and not as a current reading** — a node had run for weeks
with tens of gigabytes of reclaimable Docker build cache on a nearly full OS
disk, a second disk of several hundred gigabytes sitting 99% empty, no backups
of any kind, and a hub reporting the root filesystem's size as the machine's
total disk.

None of that was broken code. `MASTER.md` listed *"7. Backup — set up before
adding data"* as a step; the installer implemented no storage or backup step at
all. The intention was recorded and never executed, and nothing compared the
two.

For today's reading: `python3 hub/tools/storage-preflight.py` and
`python3 hub/tools/install-preflight.py`.

### Storage is derived, never assumed

`kernel/storage.py` (module `20200013`) reads the machine:

| | |
|---|---|
| `mounts()` | real filesystems only — squashfs/tmpfs/overlay excluded, or the largest "mount" is a read-only snap image |
| `docker_storage()` | images **and** build cache, which live in different places: 40GB hid in `/var/lib/containerd` while `/var/lib/docker` showed 1.6GB |
| `data_root()` | largest non-OS mount ≥50GB, else the OS disk labelled honestly as the fallback |
| `findings()` | each carries the command that fixes it — and never runs it |

Read-only by design. An installer that silently repartitions a server is a
worse outcome than a full disk.

### Storage profile — hardware decides, not convention

| Drives | Data | Backups |
|--------|------|---------|
| 1 | `/srv/docker` | same disk, flagged: *a backup on the same disk is not a backup* |
| 2 | the large one | **must be a different physical device** |
| 3+ | largest non-OS | second-largest non-OS |

Convention is exactly what failed here: fks-services uses `/mnt/storage`,
ksgcohub uses `/srv/data`, the docs say `/srv/backups`. Three names for one
idea, and no single constant is correct on both machines.

### Three data classes, one location

A project gets one directory so isolation holds — `rm -rf` takes everything and
disturbs nothing else, which is the acceptance test `/api/admit` already
publishes. Inside it, three classes, because value differs:

```
/srv/data/<project>/
  db/       small · changes constantly · irreplaceable   → nightly, keep 30
  media/    large · write-once-read-many                 → weekly,  keep 4
  cache/    disposable · regenerable                     → never backed up
```

The evidence for classifying rather than lumping, from ksgcohub's volumes:

```
netdata_netdata-cache   1.606GB    worth backing up: zero
babyhelp-data           1.024MB    irreplaceable
```

A naive "back up every volume" job copies 1.6GB of cache nightly and 1MB of the
thing you would actually mourn.

**No shared media pool.** It breaks the acceptance test, it makes orphans
nobody owns, and the contract already answers it: *cross-project data moves
over HTTP.* Media is not an exception. If two projects need one asset, one owns
it and serves it.

### Why this belongs to the mesh, not beside it

Storage is not a side quest. `attention.storage` rides in `/api/node`, which is
the payload every node heartbeats to central and the payload FlareSHub
aggregates. So the same one address that shows you which nodes are up shows you
which nodes are quietly filling their disks — **fleet-wide, without visiting
one of them.**

That is the point of one entry for many: the node reports what is true about
itself, and the entry point makes N nodes answerable in one look. A disk
silently filling on server seven is exactly the class of thing that is
invisible until you have one place to see it from.

### One receipt, four depths

Several endpoints answer *"what is true about this machine"* — `/api/status`,
`/api/storage`, `/api/receipt`, `/api/context`, `/api/node`, `/api/admit` and
more — in as many shapes, across two modules, overlapping, with no shared
source. Same disease as `VIEW_DEFS` vs the render switch, larger organ.
`python3 hub/tools/atlas.py` counts the overlapping shapes; do not count them
here.

Target: one builder, four projections.

```
GET /api/receipt                  the machine: disks, ports, containers, health
GET /api/receipt?for=project      + your band, your data paths, the contract
GET /api/receipt?for=fleet        + identity, mode, peers
GET /api/receipt?for=authority    + what FlareVault needs to provision
```

A project asks one URL and is told where to bind, where data goes, where media
goes, and how to prove it complied. That is what should have happened with
babyhelp, which was built by someone who knew nothing about this server and had
no way to ask.

---

## 3. How a request flows

```
phone / desktop
   │  the apex, path-scoped        ONE address. PWA installs from here.
   ▼
Cloudflare Access ── Google ──► one login covers every node in the same Access org
   │
   ▼
FlareSHub  ─── service tokens ───┬──► a node's derived hostname → that node's hub
   aggregates /api/node          └──► another node's derived hostname → its hub
   from every node
```

**Node hostnames are never typed by a human**, and none is written on this page.
A node's name is derived from its `machine_id` by `enroll.sh` — because a name a
human types is a name a human gets wrong, and one such typo became permanent DNS
pointing at a tunnel nothing runs. Print the live names with
`python3 hub/tools/situation.py` or `python3 hub/tools/cf-check.py`.

Their Access policies are service-token only, so a person browsing to one is
refused outright and only FlareSHub can reach them. Add a tenth server and the
human-facing surface does not grow.

**Why server-side aggregation and not browser-side:** one origin means no CORS,
one Access session, one service worker, one push subscription. The extra hop
buys all of that.

---

## 4. Two doors — the auth model

| Path | Already proved | Login it asks for |
|------|----------------|-------------------|
| LAN / Tailscale | you are on an enrolled device in a private network | hub username + password |
| Cloudflare | nothing — it is the open internet | Access → Google |

The local login **always works, is never disabled, and depends on nothing
external.** When Cloudflare, Google or your domain is having a bad day, you get
on Tailscale or walk to the machine. That is why you do not collapse to
Google-only.

Access grants a user-level session. Gate 2/3 routes — vault, shell, TOTP —
still demand the stronger proof regardless of which door you came through.
Google gets you in the building, not into the safe.

`HUB_CF_TRUST_IP` names which source address may assert the Access header. The
header is trusted **only** from the tunnel's address, because anything on the
tailnet can forge a header. **The trust is the path, not the header.**

Note the shape of the trap: the allowlist is tested as `if CF_EMAILS and ...`,
so an *empty* list admits any address Access approved. Absent is not off. Which
nodes set which of these is `python3 hub/tools/matrix.py`, sequence A.

---

## 5. Notifications

**The principle: emit before you transport.** Which events are emitted, and
whether the push path delivers them, are two separate claims and must be checked
separately — *built and delivering nothing is not the same as built.*

```bash
python3 hub/tools/matrix.py       sequence A rows 6 and 7
curl -s <hub>/api/events/self     the notification unit's own self-check
```

`hub/NOTIFY.md` holds the design of the events stream and its known limits.

**Order that respects reality:**

1. Emit the events first — login, failed login, deploy, drift, incident → `activity_log`
2. Route them to ntfy, which already works and already has apps on your phone
3. Only then Web Push in the PWA: real service worker, VAPID keys, subscription
   storage. On iOS the PWA must be installed to the home screen (16.4+), no
   exceptions.

Web Push makes alerts arrive *as FlareSHub* rather than as ntfy. That is a
polish step, not the win. The win is step 1.

---

## 6. Where it stands — not written here

This section used to be a two-page status inventory: built, built-not-deployed,
built-never-executed, not built, known wrong. Every category rotted at a
different speed and several rows were false within days of being written — rows
marked "never executed against the live API" that had since been proven against
the edge, and rows marked broken that had been fixed.

A design document does not get to hold a status board. Ask:

```bash
python3 hub/tools/atlas.py        which planes exist, and which were typed rather than installed
python3 hub/tools/step.py         which step of the build order we are on
python3 hub/tools/matrix.py       all five checklists, asserted against the machines
python3 hub/tools/situation.py    what is serving, what is exposed, what could not be seen
python3 hub/tools/tracks.py       which track is next, and what gates it
bash bootstrap.sh --check         is this node at the installer's standard
```

Each of those ends by naming **what it could not see**. A clean report with a
hole in it is more dangerous than a failure, because nobody investigates a pass.

---

## 7. Build order — delegated, not restated

The ordering *rules* are doctrine and are stated where they belong:

- **`hub/tools/tracks.py` enforces the order**: unison, then mockups, then UI.
  Mockups before any build.
- **`hub/tools/step.py` names the current step.** It is the authority on this,
  not a table in a document.
- Work that needs nothing from anyone runs in parallel with everything else;
  work that needs a credential or a decision from the operator is an operator
  decision, not a task, and `atlas.py` lists those separately.
- **The storage track is additive and disrupts nothing.** Anything that would
  recreate a container or restart every container is parked, by choice, and
  stays parked until it is the cheapest remaining move.
## 8. The standing rule

Every failure found in the week of 2026-09-10 was a **record disagreeing with
the machine**, not a code bug: an installer that copied the app where its
imports failed, a service unit pointing at a deleted file, docs describing an
already-split monolith, a memory declaring a live server dead, a compose
fallback to a domain that does not exist.

The week of 2026-09-22 added a second rule, learned the same way. `MASTER.md`
listed *"7. Backup — set up before adding data"*; `bootstrap.sh` never
implemented it, and nobody noticed for months. A checklist item cannot fail,
because nothing executes it.

So: **assert, do not describe.** `tools/check-views.py` and
`tools/install-preflight.py` exist because they can *fail*. Every other page in
this repo, including this one, is prose that can quietly stop being true — and
the only defence is keeping the number of such pages small and the number of
executable assertions growing.

And: **derive, do not maintain.** `/api/node` reads the machine every call and
holds no opinion about what should be there. Intent lives with the authority;
the node reports only what is. When those two disagree, that is drift — and
drift you can see is the entire point.
