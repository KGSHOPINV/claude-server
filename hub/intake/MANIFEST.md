# Intake manifest — reconciling every project against its home server

One row per project. The ball moves left to right. Nothing moves without
evidence from the machine that project actually runs on.

## States

| State | Means | Who moves it |
|---|---|---|
| `awaiting` | template sent, no reply yet | the project's session |
| `claimed` | reply received, stored, unverified | you (paste it here) |
| `verified` | checked against the home server, diff written | me |
| `reconciled` | every diff either fixed or accepted as a declared deviation | you decide, I record |

A claim is never trusted. `claimed → verified` is me running `docker ps`, reading
the disk and the compose on that project's home server and writing what actually
is. The gap is the deliverable.

## The board is not here

A table stood here: one row per project, with its home server, its state, the
master it had acknowledged, whether it was stale, and how many diffs were open.
Beside it sat a box giving each server's current code ref.

**That is `control.db`'s job, and having both is two sources of truth for one
fact** — the precise disease this system exists to remove. The markdown board
and the SQLite `projects` table were built four days apart and both were live.

```bash
curl -s <hub>/api/registry              every project on THIS server
curl -s <hub>/api/registry/<project>    one project's standing record
curl -s <hub>/api/mesh/registry         what runs where, and whether it is the same build
python3 hub/tools/step.py               whether any intake has started at all
```

**Scoped to one server by construction.** The rules a project is given are
derived from THIS host's disks and THIS host's bound ports, so the same project
on the other machine is a different record with different values — which is
correct, not duplication.

**Staleness is a marker, never a gate.** It means *"has not been told"*, so
nothing may assume the project knows. It is information for the operator, not
an enforcement.

## Layout

```
hub/intake/
  MANIFEST.md              this board
  projects/<name>.md       THE STANDING RECORD — what a project refers back to
  claims/<project>.yaml    what the project SAID   (pasted verbatim, never edited)
  verified/<project>.json  what the MACHINE says   (derived, regenerable)
  diffs/<project>.md       one reconciliation event
```

### The standing record

`claims/`, `verified/` and `diffs/` are *events* — they happen once and are
dated. `projects/<name>.md` is the **thing that persists**: the project's own
ServerHub page, with its status points, its open differences and their
dispositions, what is pending underneath it, and its history.

A project asks one question forever — *what is my state on my home server* —
and this is the answer. Intakes come and go; the record accumulates.

It is scoped to ONE server by definition. `babyhelp.md` is a ksgcohub document;
the same project on the other machine would be a different record with
different derived values, and that is correct, not a duplicate.

`claims/` is append-only and never corrected. A claim that turned out wrong is
evidence, not a mistake to clean up — the whole point is the distance between
what was intended and what is.

`verified/` is derived, so it is disposable and never backed up. `claims/` and
`diffs/` cannot be re-derived, so they are.

## Why the project does almost nothing

It answers one template from `hub/INTAKE.md` and stops. It does not audit
itself, does not fix anything, does not need to know the server's conventions.
Verification happens here, against the machine, by the thing that already reads
every container, port and disk on both boxes.

A project that had to verify itself would need the server's whole model — which
is exactly the tribal knowledge this removes.

---

# The protocol — what each side acknowledges, and what they agree

One project at a time. Nothing proceeds until both sides hold the same record.

## Step 1 — the project acknowledges (its side)

Answers the template from `hub/INTAKE.md`. That is all it does.

It is stating: *this is what I am, this is what I run, this is what I keep, and
these are the deviations I already know about.*

It is NOT asserting the server's conventions, auditing itself, or fixing
anything. `unknown` is a valid answer and better than a guess.

## Step 2 — ServerHub acknowledges (my side)

I go to that project's home server and write down what is actually true:
`docker ps`, the disk, the compose file, the ports, the labels.

I am stating: *this is what the machine says, independent of what you claimed.*

Neither side is trusted over the other here. The claim is intent; the machine is
fact; both are recorded.

## Step 3 — consensus (the agreement)

Every difference gets exactly one disposition, and it is written down:

| Disposition | Means | Who decides |
|---|---|---|
| `fix` | the project will change to match | the project |
| `accept` | the deviation is deliberate and stays | the owner |
| `defer` | real, not now, with a reason | the owner |
| `hub-wrong` | the contract is wrong, not the project | me — and I change the contract |

That last row matters. A project pushing back is a finding about ServerHub, not
insubordination. The contract has been wrong before — it handed out ports inside
Supabase's lane for months.

The agreed file is `diffs/<project>.md`. Both sides point at it. Nothing is
remembered, nothing is relayed, no one has to be in the room.

## What "done" means

A project is `reconciled` when every difference has a disposition — NOT when
every difference is fixed. A project with four accepted deviations is fully
reconciled. An undeclared deviation is the only failure state.

## Sequence

**One at a time, each fully reconciled before the next starts.** Four half-done
intakes tell you less than one finished one.

Which project goes first is an **operator decision**, not a task — nothing
proceeds on it by itself, and the order is not written down here because it
changes with what the operator learns. `python3 hub/tools/atlas.py` lists it
among the operator decisions; `python3 hub/tools/step.py` says whether the
first one has started.
