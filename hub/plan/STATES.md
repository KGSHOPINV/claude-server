# The admission pipe, and the three states

Two drawings. Everything else in the plan hangs off these.

---

## 1. The admission pipe — where new and existing projects enter

```
                 ┌──────────┬──────────┬──────────┬──────────┬──────────┐
   NEW  ────────▶│ ALLOCATE │  BUILD   │  DEPLOY  │  VERIFY  │   ACK    │───▶ MAINTAINED
                 └──────────┴──────────┴──────────┴──────────┴──────────┘
                                                  ▲
   EXISTING ──────────────────────────────────────┘
                                          enters here — already built,
                                          already deployed, nothing to allocate
```

What crosses each divide:

```
│ ALLOCATE │   name reserved, unique fleet-wide
│          │   band assigned — 100 ports, e.g. 12200-12299
│          │   data paths: db / media / cache / releases / public / private
│          │   labels, naming, network, forbidden list, acceptance test
│          │   the floor: 12 port lanes, every bound port, every neighbour
│          │   NOTHING EXISTS YET, so there is nothing to compare
├──────────┤
│  BUILD   │   the project builds TO the rules. Not watched, not enforced.
├──────────┤
│  DEPLOY  │   first containers appear. The machine finally has something
│          │   to read.
├──────────┤   ◀── EXISTING PROJECTS JOIN HERE
│  VERIFY  │   claim vs machine, both directions
│          │     NEW      expect zero diffs — it was told before it built
│          │     EXISTING expect many — it predates every rule
├──────────┤
│   ACK    │   PIN. rung 1 -> 2 -> 3.
└──────────┘
```

**The asymmetry is the point.** A new project reaches VERIFY clean, so a diff
means it ignored what it was given. An existing project skips the first three
segments entirely — it took its ports and paths long before any of this existed,
so its diffs are HISTORY, not failures. That is why `accept` is a real
disposition and not a concession.

From VERIFY onward it is one pipe. Same ladder, same bulletins, same backup
model. After ACK you cannot tell where a project entered.

---

## 2. The three states, on both rows

```
               CURRENT              DRAFT MASTER          MASTER
               what is true now     being written         agreed, waiting

  SERVER       the running ref      the port lane, the    the set both servers
               the live band        storage template,     will run once applied
               who is registered    isolation rules       — FROZEN
                                    — still changing

  PROJECT      its real ports       its band offered,     what it agreed to
               its real data path   diffs raised but      but has not done yet
               its labels, or none  not yet disposed      — FROZEN
                                    — still negotiating
```

**MASTER is a holding space.** Nothing in it is live. It is what has been agreed
and is waiting to land. When it lands it becomes CURRENT, and DRAFT starts
filling again.

The vertical is identical on both rows, which is why one mechanism serves both:

```
SERVER    draft -> master -> current   =   stage -> promote -> running
PROJECT   draft -> master -> current   =   diffs -> dispositions -> done
```

### Why the middle column exists at all

On 2026-09-24 the project port band was moved on ksgcohub by pushing a DRAFT
straight to CURRENT. No master, no holding space, no acknowledgement, nothing
frozen. Four projects had the ground moved under them and none had been told.

The middle column is the thing that was skipped. It is the only column where
something can be true for both sides before it is true on the machine.

---

## Reading the two together

The pipe is how a project ARRIVES. The three states are how anything CHANGES
afterwards — for the server and for each project, using the same three tiers.

A bulletin is the server publishing its DRAFT and asking projects to move it to
MASTER by acknowledging. Only then does it become CURRENT.
