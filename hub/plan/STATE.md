# The exchange — the model, and what was got wrong reaching it

**Written 2026-09-24**, because that session went long and most of it was the
plan being got wrong. What is kept here is the *model* and the *errors*, both of
which are true forever. **Every "where we are" reading has been removed** — this
page asserted a live state, and a page that asserts a live state is wrong within
days and looks exactly as authoritative as it did on day one.

For where anything actually stands:

```bash
python3 hub/tools/step.py      the current step of the build order
python3 hub/tools/tracks.py    which track is next, and what gates it
python3 hub/tools/atlas.py     what exists, and what was typed rather than installed
python3 hub/tools/matrix.py    the checklists, asserted against the machines
```

---

## The thing, in one line

The server publishes what it is and what it's doing. Projects read it,
acknowledge with a PIN that proves they read it, and comply on their own
schedule. **The operator stops being the messenger.**

## Who talks to whom

```
OPERATOR  →  tells a PROJECT: go talk to your server
PROJECT   →  SERVER: reads the bulletin, acks with PIN, files its claim,
                     files tickets before self-fixing
ME        →  SERVER: read what projects left, publish the next bulletin
```

I never talk to a project directly. Everything goes through the server. I broke
this once by messaging a session and it was the wrong instinct, not a shortcut.

## TWO servers. Everything applies to both.

Their disks, RAM, projects and containers are **not written here** — ask
`python3 hub/tools/situation.py` or `curl -s <hub>/api/receipt`. The rule is:

Same code everywhere. Different derived values — different disks means
different data roots, and that difference is **the system working, not drift.**
**Congruence is the code ref matching, never the values.** A check on values
cries wolf and is ignored within a week.

One server holds the authority layer, which makes it the candidate for central
— and it was the box neglected all day, which is error 3 below.

---

## The ladder — gated, each rung unlocks the next

```
1  "You are already in this server."   here is what we see of you
   ack with PIN ↓
2  "Here is where this server is going."   roadmap, restructuring
   ack with PIN ↓
3  "Here is what that means for you."      their diffs, their dispositions
   agree ↓
4  maintained — bulletins against a standing agreement
```

A project that has not confirmed what it **is** cannot evaluate what is
**changing** — it has no baseline. That is why the rungs are gated, and it is
exactly what I got wrong by moving the port band with the ack list empty.

## The PIN

Embedded in the readout. To advance you post it back, which means you cannot
acknowledge something you did not read. Per rung, per project.

When they are pointed at an address they do nothing else — the focus is what
makes the PIN mean absorption rather than a skim. So each readout must be
self-contained: no links out, no "see also".

## Bulletins

- **Broadcast** — every project on that server, same text.
- **Targeted** — one project, about its own correction. Same mechanism.

**Nothing blocks.** Bulletins sit on the server. The operator calls a session
to go read. The server publishes and records who read what; it never enforces.
The stale list is information for the operator, not a gate.

Every bulletin ends with **the one thing they do**, and *"nothing right now"* is
a common and valid answer. If every bulletin demands work they stop reading
them.

## The download is a snapshot

A project holds bulletin N. The server moves. That project is now holding a
stale readout and comes back for the delta.

Version bumps only on things a project could have to **act** on — bands, data
paths, isolation rules, a project arriving or leaving, direction. Not on live
readings like current port usage or disk percent, which are in the readout as
information and change constantly. Otherwise everyone is permanently stale and
the PIN stops meaning anything.

## Alignment, not audit

Neither side holds the whole picture.

```
ONLY THE MACHINE KNOWS        ONLY THE PROJECT KNOWS
containers, ports, labels     Cloudflare zone, hostname, tunnel
disks, mounts, compose        Access policy, DNS
what is actually bound        where secrets live, who its users are
                              what it believes it is, what it plans
```

So `hub-wrong` is structurally necessary, not a courtesy — half the picture was
never mine to hold. The intake must **not** ask for containers or ports; I read
those, and a guess there is worse than a gap.

---

## Ports — the allocation rule (decided 2026-09-24)

```
LANE      12000-18999      moved off 7100-7899 (only 16 projects)
PER PROJECT   100          70 projects per fleet
ALLOCATION    fleet-wide   a band is unique across BOTH servers, so a project
                           can move machines without renumbering
```

Offset carries meaning inside a band — suggested, never enforced:

```
x00-x19  UI / frontend        x60-x79  workers, jobs, queues
x20-x39  API / services       x80-x99  dev, preview, debug
x40-x59  data — db, cache, search
```

**Migration, not cutover.** New projects are held to it. Existing ones move when
it suits them. Outgrowing 100 is a ticket, not a violation. Neither is a
violation, and saying so is what makes `accept` a real disposition rather than a
concession.

Which band any project holds is derived, not proposed in a document:
`curl -s "<hub>/api/admit?project=X"`.

The full lane library goes in the first readout — the map before their position
on it.

## Storage template — proposed, does not exist yet

```
/srv/data/<project>/
  db/         backed up nightly      media/    backed up weekly
  cache/      never backed up        releases/ keep N, never backed up
  public/     no auth                private/  auth required
```

One rule for auth: **anything under `public/` is open, everything else needs a
session.** The filesystem declares intent; the serving layer enforces.

Public downloads should go to Cloudflare, not the box — anything served
publicly off the server is attack surface on the server.

**Undecided:** whether projects get host uids. Without them `/srv/data` has no
isolation between projects, only inside containers.

## First admit hands over an operating set

Saved in the project's own repo: band, data paths, labels, naming, forbidden
list, acceptance test, and the seven commands. After that the operator says
*"pull up our server commands"* and names one — no re-explaining.

`hub/SERVER-COMMANDS.md` is that file.

---

## Live state — deliberately absent

A five-line box stood here giving each server's commits-behind, preflight score,
backup state, and a count of projects registered. It was a status board inside a
design document. Every line rotted at a different speed and the page went on
looking correct.

```bash
python3 hub/tools/step.py         where the build actually is
python3 hub/tools/situation.py    what is serving, exposed, and unseen
python3 hub/tools/matrix.py       every checklist row against both machines
```

Each ends with **what it could not see**. A blind spot is not a pass.

---

## Open, yours to answer

- rung 2 granularity: one bulletin for the whole restructuring, or one per change
- the trigger word, and the filename projects save in their repo
- host uids for project isolation
- does admission **reject** a claim outside its band, or record a violation
- which server a new project lands on — nothing answers this yet

## What was got wrong on 2026-09-24, so it is not repeated

1. Deployed the port band before any project was told. You had said sideline it
   until projects were aware. That inversion caused most of this.
2. Messaged a project session directly, bypassing the server, which is the
   entire mechanism.
3. Tunnel-visioned on ksgcohub and treated fks-services as an afterthought when
   it is half the system and holds the authority layer.
4. Built markdown when the answer was endpoints; a project cannot POST to a
   document.
5. Asked projects for what I can already read instead of what only they know.
