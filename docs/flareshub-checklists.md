# FlareSHub — Checklists

**Five sequences this system must perform, and why each step is in the list.**
Companion to `flareshub-blueprint.md` and `flareshub-doctrine.md`.

---

## This page carries no status marks

It used to. It was hand-marked on 2026-09-21 and five days later **23 of its 68
rows were wrong, in both directions** — rows marked built that were not, rows
marked missing that had shipped. One row was marked correctly and got
contradicted anyway, because the *reason* written beside it compared the wrong
two things: it reported `/` had 68.1GB free, which says nothing about whether
the backup target is a different device from the data it protects.

A tick is a memory, and a memory cannot fail. So the ticks are gone and one
command answers all five sequences against the live machines:

```bash
python3 hub/tools/matrix.py
```

It prints, per row, **what the document claims** and **what the machine said**,
and flags the rows that have FLIPPED since the last hand-marking — in both
directions. `matrix.py` carries its own transcription of the old marks
internally, precisely so this page does not have to.

What stays here is the part a command cannot supply: **what each sequence is
for, and why each step earns its place.**

Related instruments:

| Question | Command |
|---|---|
| Is this node at the installer's standard? | `bash bootstrap.sh --check` |
| Which storage rows pass on this box? | `python3 hub/tools/install-preflight.py` |
| What is serving, exposed, or unseen? | `python3 hub/tools/situation.py` |
| Which step of the build order are we on? | `python3 hub/tools/step.py` |

---

## A. Login — what happens when someone arrives

| # | Step | Why it is a step |
|---|------|------------------|
| 1 | Record which **door** the request came through | LAN, tailnet and open internet have proved different amounts. The door is evidence and has to survive into the session |
| 2 | **Cloudflare door:** trust `Cf-Access-Authenticated-User-Email` *only* from the tunnel address | Anything on the network can forge a header. The trust is the path, never the header |
| 3 | Email checked against an allowlist → session, role | An allowlist tested as `if CF_EMAILS and ...` admits **anyone Access approved** when the list is empty. Absent is not off |
| 4 | **Local door:** username + SHA-256 password vs the `users` table | The break-glass. It must work when Cloudflare, Google or the domain is having a bad day |
| 5 | Session issued, and **survives a restart** | A session in a process's memory logs everyone out on every deploy, which trains people to expect the login screen and stop reading it |
| 6 | Write the login to `activity_log` | On a box reachable from the internet, "who got in, when, through which door" has to be answerable afterwards |
| 7 | **Notify** — normal on a sign-in, high on repeated failures | Built and delivering nothing is not the same as built. The push path is a separate claim from the call site |
| 8 | Per-route gate enforced (0 public / 1 user / 2 admin / 3 TOTP) | A declared gate that is never applied is decoration. `HUB_ENFORCE_GATES` is the switch; the router shadow-records what it *would* have refused |
| 9 | Dangerous routes demand more than the front door gave | Google gets you in the building, not into the safe. **Rows 8 and 9 are different questions** — if 8 fails open, 9 fails open with it, and a TOTP check that returns true when no secret is configured opens every gate-2 and gate-3 route to anyone past the front door |

---

## B. Installer — what a new node gets

**The test for every row here is the INSTALLER, not the machine.** A thing that
is true of both servers because a human typed it on both is *applied*, not
built. The third server is what proves which, and by then whoever typed it has
forgotten.

### `bootstrap.sh` — hub running

| # | Step | Why it is a step |
|---|------|------------------|
| 1 | OS detect, packages (curl, git, python3, ufw) | Refusing a non-Debian family box is better than half-installing on one |
| 2 | Docker installed, enabled, started | Everything a project owns is a container |
| 3 | Clone/update hub to `~/hub` | One checkout, one place, updatable without a reinstall |
| 4 | `db/` created, admin user seeded | Seeded **through `kernel.db`**, so there is one schema and not two |
| 5 | systemd **user** service, journald | A restart policy of `on-failure` does not restart a hub that exited cleanly. The policy is part of the row, not a detail under it |
| 6 | Hub answering on `:8765` | Probe the port. "The unit started" is not "the hub answers" |
| 7 | Force the default password to be changed | A default advertised on the login screen is not a default, it is a published credential |
| 8 | Register its port block | Deriving a free band on request is not the same as claiming one. Two nodes bootstrapped the same day can still collide |

### `enroll.sh` — node joins the fleet

| # | Step | Why it is a step |
|---|------|------------------|
| 1 | Read `/etc/machine-id` → stable node key | The only identifier that survives a rename, a reimage and an address change |
| 2 | Validate node label; require `--zone` | A name a human types is a name a human gets wrong — which is how `hub-ksgco`, a typo, became permanent DNS pointing at a tunnel nothing runs. The name is derived from machine-id for exactly this reason |
| 3 | **Refuse if the hub is not answering** | Never publish a dead endpoint. A hostname that resolves to nothing is worse than no hostname |
| 4 | Load token from `$CF_API_TOKEN` / `~/.cf-token` / `/etc/flare/token` | Three sources, in that order, none of them this repo |
| 5 | Verify the token **before changing anything** | Verified against `/zones`, not `/user/tokens/verify`, which returns 401 for tokens that work |
| 6 | Resolve zone + account | Both, before any write |
| 7 | Create **or reuse** the tunnel | Idempotent, or re-running the installer multiplies tunnels |
| 8 | Ingress: this hostname → local hub, plus catch-all 404 | **Merge, never replace.** A shared surface where a write could make another hostname vanish must refuse instead |
| 9 | DNS CNAME → `<tunnel>.cfargotunnel.com`, proxied | The record is what makes the node exist to the fleet — the zone *is* the register |
| 10 | Access app on the hostname | Nothing public ungated, ever |
| 11 | Attach the policy | **A warning is not a step.** The policy is `any_valid_service_token` and not an "allow" policy for a person: a human who finds a node hostname gets nothing, by design |
| 12 | `cloudflared` as a **host** systemd service | If Docker dies, the way in must survive. A monitor inside the thing it monitors dies exactly when it is needed |
| 13 | `~/.flare/node.json` — facts only, no credentials | The node holds no key and creates no hostname |
| 14 | Verify the public hostname answers | An enrolment that did not prove its own result is a belief |
| 15 | Announce itself to a sponsor node | So a new server can be admitted from a known server, with no ISO and no central |
| 16 | **Decommission path** | Enrolment gives a node a hostname, a DNS record, an ingress rule, an Access app and sometimes a tunnel. Something has to be able to take all five back, or the zone fills with names answering 401 for machines that no longer exist. This is the row people skip. It lives in a **sibling script**, not behind a flag on `enroll.sh`, deliberately: `--decommission` is a few characters from `--dry-run` on a line that removes the way IN to a node, and dry-run is its default with no short way past it |

---

## B2. Storage — what a node must settle before it is finished

This sequence exists because `MASTER.md` listed *"7. Backup — set up before
adding data"* and `bootstrap.sh` never implemented it. The step was recorded,
looked correct for months, and was never done — **because prose has no failure
mode.**

So this one is executable and nothing about it is written down here:

```bash
python3 hub/tools/install-preflight.py            report
python3 hub/tools/install-preflight.py --strict   exit 1 if anything is missing
bash bootstrap.sh --check                         assert the installer's standard
bash bootstrap.sh --check --strict                warns and unknowns fail too
```

`--check` derives what to expect from `bootstrap.sh`'s **own heredocs** rather
than restating them, so the check cannot drift from the installer, and it hands
the storage rows to `install-preflight.py` instead of re-implementing them.

The rows it asserts, and why each one:

| Row | Why it is a row |
|---|---|
| Hub enabled as a systemd **user** service | Runs without root, restarts itself, survives the SSH session ending |
| Identity issued from `/etc/machine-id` | Two identifiers on purpose — a reimaged box keeps `machine_id` and gets a new `server_id`, which makes the reimage *detectable* |
| Data root designated | Largest non-OS mount, with `backup`/`archive`/`snapshots` names **excluded however large**: a disk mounted at `/backup` is a declaration, and overruling it is the machine overruling a human who was right |
| Backup target on a **different physical device** | `findmnt` reports the source device, so this is checked, not assumed. A copy on the same disk survives a bad `rm` and nothing else. On a one-disk machine the preflight says so plainly instead of pretending |
| Backups actually running | The only row on this page whose failure is unrecoverable |
| Cache reclamation scheduled | 40GB of build cache accumulated in `/var/lib/containerd` while `/var/lib/docker` reported a harmless 1.6GB |
| Storage sound — no `high`/`warn` findings | Each finding carries the command that fixes it, and never runs it |
| Layout — the DB is where the hub thinks it is | A rival `server.db` beside the one the hub opens is two schemas and one of them is invisible |
| Admin password changed | See B/7 |
| Enrolled — reachable by name | A node nothing can reach is not in the fleet, whatever the register says |

**A converging installer is what stops this recurring.** Running it on an
existing node must bring it to standard rather than needing a rebuild, so *"did
step 7 happen"* becomes a command instead of a memory.

### What `--check` found that months of prose had not

Recorded 2026-09-26, kept as history and not as status: neither box had been
produced by the installer as it stood. One had a hand-edited `hub.service` with
no `WorkingDirectory`, and a `~/.local/bin/hub-backup.sh` that was an older copy
of `hub/tools/backup.sh` not backing up `control.db`. The other had no backup
step at all and a rival `~/db/server.db`. Until that command existed, nothing
said so.

Re-run it for today's answer; do not read this paragraph as one.

---

## C. Cross-connect — node A acknowledges node B

How two nodes come to know about each other.

| # | Step | Why it is a step |
|---|------|------------------|
| 1 | New node holds a **one-time join token** + a sponsor address — never the CF token | The node must not hold the credential that could unmake the fleet |
| 2 | New node POSTs to the sponsor with its `machine_id` | The stable key, from the start |
| 3 | Sponsor verifies the join token and **burns it** | A reusable join token is a permanent key wearing a temporary name |
| 4 | Sponsor (or FlareVault) provisions tunnel/DNS/Access on its behalf | Today `enroll.sh` does this directly, which means the node holds the CF token. That is the model being moved away from |
| 5 | Sponsor records the node **by machine-id**, with URL as a mutable attribute | Keyed by URL, a moved peer is a dead peer. Keyed by machine-id, it has simply changed address |
| 6 | Sponsor returns tunnel token + assigned hostname | The authority names things; the node never does |
| 7 | Both sides reconcile from `/api/node` | The node's job is to describe itself accurately and let the authority reconcile |
| 8 | An address change re-announces the **same** machine-id | Which is the whole reason for step 5 |

**`machine_id` binds; it does not authenticate.** The payload carries it, so say
`bound_by`, never `authenticated`, until a join token exists. Renaming a weak
guarantee into a strong one is a lie you will have to un-teach.

**Ownership:** steps 1–6 are **FlareVault's** by doctrine — it holds credentials
and makes access decisions. ServerHub's part is step 7.

---

## D. Correcting a node's Cloudflare entry

The shape of the problem, which recurs on every box that had a tunnel before it
had this system:

A containerised tunnel serving several hostnames has **two defects**. It is a
container, so if Docker wedges the tunnel dies with it — the way in disappears
exactly when it is needed to diagnose the box. And its ingress lives only in the
Cloudflare dashboard, invisible from the server, so an outage cannot be
diagnosed from the machine.

**The correction is additive and reversible, in this order:**

| # | Step | Risk |
|---|------|------|
| 1 | `enroll.sh` creates a **second**, host-level tunnel serving only this node's derived hostname | none — additive. Tunnels coexist |
| 2 | Verify the new hostname reaches the hub | none |
| 3 | Attach the Access policy | none |
| 4 | Move the hub's old hostname onto the new tunnel **only after** the new path is proven | reversible |
| 5 | Leave every other project's hostname where it is | untouched |

**Never migrate another project's hostnames.** Law XII: *"We stopped using it"
is not "it is dead."* Check whose it is before removing anything — anything
under another project's zone is theirs.

**ntfy deliberately stays off Access.** It is an app endpoint, and Access would
silently kill push.

The node's own hostname is **derived from machine-id**, never typed. Do not
write a node hostname into this document; ask for it:

```bash
python3 hub/tools/situation.py      # what is serving and what is exposed
python3 hub/tools/cf-check.py       # the zone's records, read-only
```

---

## E. What the system will be able to state

Once A–D land, these become answerable in one call rather than by archaeology:

- Which nodes exist, by stable identity, and where each is reachable
- What runs on each node, grouped by owning project — and what nothing claims
- Which projects are publicly exposed and behind which policy
- Who logged in, when, through which door
- What has drifted from what was declared
- **Which nodes are quietly filling their disks** — `attention.storage` rides in
  `/api/node`, the same payload every node heartbeats, so one address answers it
  for the whole fleet without visiting a single machine

The last one is the point of the whole exercise: **drift you can see.**
