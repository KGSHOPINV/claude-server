# FlareSHub — Blueprint

**The gain:** one address, one login, any server, on desktop or phone — and it
can tell you when something happens.

Status as of 2026-09-21. Verified facts, not aspirations. Anything not built is
marked as such.

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

**Where the current build fails this:** `enroll.sh` takes `--zone` on every run
(violates one-entry) and is a separate step from `bootstrap.sh` (violates
installer-finishes). Target: one flow, zone from fleet config, node name derived
from machine-id/hostname.

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
  enroll.sh --node X --zone Z
       │  reads /etc/machine-id            → the stable key
       │  verifies CF token                → refuses if invalid
       │  refuses if hub not answering     → never publish a dead endpoint
       ├─ create/reuse tunnel  (idempotent)
       ├─ DNS  hub-X.Z → <tunnel>.cfargotunnel.com
       ├─ Access app on that hostname      → nothing public without a gate
       ├─ cloudflared as a HOST service    → survives Docker dying
       └─ ~/.flare/node.json               → facts only, no credentials
       │
       ▼
  node is addressable at https://hub-X.Z and describes itself at /api/node
```

The API token is used during the run and discarded. The only persisted
credential is cloudflared's, scoped to that one tunnel.

**Changing domain = changing `--zone`.** Adding a server = the same command with
a different `--node`. That is the whole turnkey property, and it holds only
because no hostname is hardcoded anywhere.

---

## 2b. What a node must be true about itself

Enrolment publishes a hostname. It should not publish a machine that cannot
hold what gets put on it — so the same run that creates DNS has to settle the
storage question first.

This section exists because it was missing. ksgcohub ran for weeks with:

| | |
|---|---|
| Docker build cache | **40GB**, reclaimable, unused, on a 98GB OS disk |
| A second disk | **458GB**, mounted at `/srv/data`, **99% empty** |
| Backups | **none** — no tool, no cron, no timer |
| What the hub reported as total disk | **98G** — root filesystem only |

None of that was broken code. `MASTER.md` lists *"7. Backup — set up before
adding data"* as a step; `bootstrap.sh` is 241 lines and implements five steps,
none of them storage or backup. The intention was recorded and never executed,
and nothing compared the two.

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

Six endpoints currently answer *"what is true about this machine"* —
`/api/status`, `/api/storage`, `/api/receipt`, `/api/context`, `/api/node`,
`/api/admit` — in six shapes, across two modules, overlapping, with no shared
source. Same disease as `VIEW_DEFS` vs the render switch, larger organ.

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
   │  https://flareshub.<zone>          ONE address. PWA installs from here.
   ▼
Cloudflare Access ── Google ──► one login covers every node in the same Access org
   │
   ▼
FlareSHub  ─── service tokens ───┬──► https://hub-fks.<zone>   → fks-services :8765
   aggregates /api/node          └──► https://hub-ksgco.<zone> → ksgcohub    :8765
   from every node
```

**Node hostnames are never typed by a human.** Their Access policies should be
service-token only, so a person browsing to one is refused outright and only
FlareSHub can reach them. Add a tenth server and the human-facing surface does
not grow.

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

Built, off by default: `HUB_CF_TRUST_IP` arms it. The Access header is trusted
**only** from the tunnel's address, because anything on the tailnet can forge a
header. The trust is the path, not the header.

---

## 5. Notifications

**What exists:** ntfy, working, with real mobile apps. It fires on container
start/die only.

**What does not:** the hub records **no logins at all** — successful or failed.
`post_auth_login` never calls `log_activity`. So the interesting events are not
being emitted, which matters more than the transport.

**The PWA today is a shell.** `manifest.json` is real and the install prompt
works. `sw.js` is one line:

```js
self.addEventListener('fetch', () => {});
```

No caching, no offline, **no push handler.**

**Order that respects reality:**

1. Emit the events first — login, failed login, deploy, drift, incident → `activity_log`
2. Route them to ntfy, which already works and already has apps on your phone
3. Only then Web Push in the PWA: real service worker, VAPID keys, subscription
   storage. On iOS the PWA must be installed to the home screen (16.4+), no
   exceptions.

Web Push makes alerts arrive *as FlareSHub* rather than as ntfy. That is a
polish step, not the win. The win is step 1.

---

## 6. Where it stands

**Built and deployed**

- Hub refactored: `server.py` 2,890 → 122 lines, 11 handlers, 7 kernel modules, 68 routes
- Both nodes ran identical code and verified 41/41 routes
- `/api/node` — live on ksgcohub. machine-id, reachability, projects grouped by
  label, and an `attention` block listing what is wrong with the node
- `machine_id` on `/api/identity` — peers can key on identity instead of address
- Two-door auth — written, trust boundary tested, off by default
- Phase 3 UI — `/ui/` static route, `registry.js`, 2 of 19 views migrated

**Built 2026-09-22/23, merged into PR #19, NOT yet deployed**

- `kernel/storage.py` — the storage landscape, derived. Verified on ksgcohub:
  ignored 8 snap loop devices, found the three real mounts, identified
  `/srv/data` as the data root, raised both real findings
- `/api/admit` port band — was `10020-10990`, **inside the Supabase stack lane**
  (`PORT_LANES` reserves `10000-10999`). Every project that asked where to bind
  was pointed at ports another service owns. Now 7100-7899, defined once
- `/api/admit` data path — was hardcoded `/srv/docker/<project>/data`, the
  SMALL disk. Now derived per machine
- `/api/status` — reported `98G` on a machine carrying **557G**, because it
  summed the root filesystem alone. Now reports both
- 9 views registered that rendered but were unreachable from the nav; 328 lines
  of dead frontend removed; `tools/check-views.py` fails on drift
- `tools/storage-preflight.py` — `--strict` exits 1, so a node is not enrolled
  onto storage that is already in trouble

Until PR #19 deploys, the live hub still answers every one of those wrongly.

**Built, never executed**

- `enroll.sh` — untested against the live Cloudflare API, because the token in
  fksinv's `.env` is revoked. `--dry-run` verifies token, zone and account and
  stops before mutating.

**Not built**

- FlareSHub itself — the aggregating entry point
- Service tokens, and service-token-only policies on node hostnames
- Login events → activity log → ntfy
- Real service worker; Web Push
- Phase 3 — 17 views remaining
- Session persistence — sessions are an in-memory dict, so every restart logs
  everyone out

**Known wrong**

- `_users_list()` returns `[]` on any exception, so `/api/users` lies
- Gate enforcement off: 52 of 66 routes gated in the table, `app.html` sends a
  token on 16 calls. Arming it locks the UI out
- 12 projects on ksgcohub carry no `com.ksg.project` label
- **ksgcohub has no backups.** No tool, no cron, no timer. babyhelp's data is a
  Docker named volume on the OS disk while 434GB sits empty. 1MB today, which
  is precisely why now is cheap and later is a migration
- No cache reclamation anywhere, which is how 40GB accumulated unwatched
- Two installers diverged: fks-services was built by the numbered script series
  (Script 09 = Backup, daily cron, `/srv/backups/`), ksgcohub by `bootstrap.sh`,
  which has no storage or backup step at all
- fks-services has an unlabelled Meilisearch on port 7700 that nobody can identify
- The sudo password is in public git history and needs rotating

---

## 7. Build order

| # | Step | Owner | Blocked by |
|---|------|-------|-----------|
| 1 | Valid scoped CF token at `~/.cf-token` | you | — |
| 2 | `enroll.sh --dry-run` on ksgcohub, then real | me | 1 |
| 3 | Same on fks-services | me | 1, box back online |
| 4 | Service tokens; node policies to token-only | you + me | 2, 3 |
| 5 | FlareSHub: poll every `/api/node`, one page | me | 4 |
| 6 | Login/deploy/drift events → activity log → ntfy | me | — |
| 7 | Real service worker, offline shell | me | 5 |
| 8 | Web Push | me | 7 |
| 9 | Phase 3 — remaining 17 views | me | — |

6 and 9 need nothing and can run in parallel with everything else.

### Storage track — runs alongside, blocks nothing, disrupts nothing

| # | Step | Owner | Disrupts |
|---|------|-------|----------|
| S1 | Deploy PR #19 — hub user service restart only | me | no container |
| S2 | Backup job → `/srv/data` — reads volumes, writes to the empty disk | me | nothing |
| S3 | Reclamation timer | me | nothing |
| S4 | `db`/`media`/`cache` in the admit contract | me | nothing |
| S5 | `bootstrap.sh` steps 6–9 + `--check` convergence mode | me | nothing |
| S6 | Receipt unification — six endpoints, one builder | me | nothing |
| — | babyhelp volume → bind mount | parked | recreates the container |
| — | Docker data-root → `/srv/data` | parked | restarts every container |

Everything above the line is additive. The two parked items are optimisations
and block nothing: babyhelp's data is 1MB and a backup job can read a named
volume without touching it.

---

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
