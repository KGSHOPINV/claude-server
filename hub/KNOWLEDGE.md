# Knowledge base — things learned the hard way

Only entries that changed a decision. Each one states what was believed, what
was true, and what it cost — because a lesson without its cost gets re-learned.

---

## Backups

### A container can read a root-owned volume without host sudo

**Believed:** named volumes under `/var/lib/docker/volumes` need passwordless
sudo, so a host without it cannot back them up.

**True:** `docker run --rm -v <vol>:/src:ro <image> tar czf ...` mounts the
volume as root *inside the container*. Only docker-group membership is needed —
which the hub user already has, because reading `docker ps` is its job.

**Cost:** this was rejected once, on the grounds that spawning a container
pollutes the container list the hub reports about itself. That traded two months
of unbacked FlareVault state for a tidy `docker ps` for the length of one tar.
fks-services went 5.0MB → 1.1GB the moment it was used.

**Rule:** prefer an image already pulled (`alpine`, `busybox`). A node that
cannot reach a registry must still be able to protect its data.

### What the container trick cannot reach

Bind mounts. `/srv/docker` still fails without filesystem read access, because
there is no volume to mount — it is a host path. Those remain a real gap and
must be reported, not skipped.

### Retention must only prune after a successful run

An unconditional `find -delete` removes the last good copy during a streak of
failures. Found in another project's script, then shipped in this one anyway.

### `tar` exit 1 ≠ exit 2

1 means a file changed while being read — the archive exists but a live database
copied that way may not restore. 2 is a real failure. Conflating them either
discards a usable backup or reports a hot copy as clean. SurrealDB's
write-ahead log is the live case.

### A backup target must be a different physical device

`findmnt` reports the source device, so this is checkable rather than assumed.
A copy on the same disk survives a bad `rm` and nothing else.

### Named volumes are not the whole picture

Backing up only named volumes missed every project that bind-mounts its data.
Worse: orphaned volumes with matching names were captured instead, so the run
*looked* complete while backing up dead copies and skipping live ones.

---

## Storage

### Intent beats size

A 4.4TB disk mounted at `/backup` is a declaration. Nominating it as the data
root because it is the largest mount overrules an operator who was already
right. Mounts named `backup`/`archive`/`snapshots` are excluded from data-root
selection however large.

### Derive the layout; never hardcode it

ksgcohub resolves to `/srv/data`, fks-services to `/srv/docker` with backups on
`/backup`. One constant is correct on one machine and wrong on the other.

### Build cache hides where you are not looking

40GB accumulated in `/var/lib/containerd` while `/var/lib/docker` reported a
harmless 1.6GB. Images and build cache live in different places.

---

## Ports

### Lanes are a declaration, not a policy

`PORT_LANES` describes the floor; nothing enforces it. `/api/admit` handed out
10020–10990 for months — inside the Supabase stack's reserved lane — because two
places answered "what may a project bind" and disagreed.

### One band per project, and make it big enough

fksinv holds 10100 and 10101; babyhelp holds 12080. Ports picked one at a time
from whatever was free that day, leaving projects scattered with no way to see
where one starts and ends. 100 ports per project, allocated **fleet-wide**, so a
band is unique across both servers and a project can move machines without
renumbering.

---

## Process

### Projects must be made aware BEFORE the server changes

The port band was deployed to ksgcohub before a single project was told. The
instruction had been to sideline it until projects were aware. Inverting that
order is the single most expensive mistake in this repo's history.

### The server is the medium

The operator tells a project to go talk to its server. The project and the hub
each read and write the server, and never each other. Messaging a project
session directly bypasses the entire mechanism.

### Neither side holds the whole picture

The machine knows containers, ports, labels, disks. Only the project knows its
Cloudflare zone, tunnel, Access policy, DNS, where its secrets live and what it
plans. So `hub-wrong` is structurally necessary — half the picture was never the
hub's to hold — and the intake must never ask for what the machine can read.

### Prose has no failure mode

`MASTER.md` listed "7. Backup — set up before adding data" and could not be
wrong, because nothing executed it. A server ran for months with no backups
while the document looked correct. Anything that must stay true gets an
assertion that can fail.

### Two machines are the cheapest reviewer available

Every wrong assumption here was invisible on one machine and obvious on two.

---

# How a project comes online

## New project — nothing deployed yet

It needs **allocation**, not verification. Verifying a project that does not
exist reports every container missing and reads as total failure.

```
1  claim a name        unique fleet-wide; it is the key for everything
2  receive a band      100 ports, e.g. 12200-12299, reserved before deploy
3  receive its paths   /srv/data/<name>/{db,media,cache,releases,public,private}
4  receive the rules   labels, naming, network, forbidden list, acceptance test
5  receive the floor   the 12 port lanes, every bound port, every neighbour
6  build to it         nothing is enforced; this is what good standing means
7  deploy, then verify now there is something to compare
8  file its claim      the half the hub cannot see — Cloudflare, DNS, auth
9  acknowledge         PIN, and it is on the ladder
```

**Held to the band from day one.** New projects are how the lane fills up
correctly.

## Existing project — already running

It needs **alignment**, not allocation.

```
1  "you are already here"    what the machine sees: containers, ports, data,
                             compose, labels — or that it has none
2  the floor                 lanes, neighbours, disks, what is backed up
3  its band, offered         migration, not cutover. it moves when it suits.
4  its claim                 the half only it knows
5  the diffs                 each with a disposition:
                               fix · accept · defer · hub-wrong
6  acknowledge               PIN
```

**Reconciled means every difference has a disposition — not that every
difference is fixed.** Four accepted deviations is fully reconciled. An
undeclared deviation is the only failure state.

## Both, from then on

```
bulletins     broadcast to every project, or targeted at one. never blocking.
              the operator triggers a read; the server records who read what.
tickets       filed BEFORE self-fixing — the project sees "container won't
              start", the hub sees the disk at 96% or a neighbour on its port
self-fix      allowed, but declared. an unrecorded self-fix is
              indistinguishable from drift six weeks later.
staleness     a marker, never a gate. it means "has not been told", so nothing
              may assume it knows.
```

## Status carries weight

```
dev          drift expected, reported quietly, not backed up by default
staging      backed up, drift reported
production   backed up, drift raised, removal needs a reason
```

A project declares its own status. It is what stops a dev project's drift from
waking anyone, while a production project's does.
