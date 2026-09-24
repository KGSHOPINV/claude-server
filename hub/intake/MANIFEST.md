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

## Board

| Project | Home | State | Claim | Verified | Open diffs |
|---|---|---|---|---|---|
| fksinv | ksgcohub | `awaiting` | — | — | — |
| metaforge | fks-services | `awaiting` | — | — | 4 SQL migrations missing (found already) |
| babyhelp | ksgcohub | `awaiting` | — | — | 4 known (labels, port, data path, compose location) |
| flarevault | fks-services | `awaiting` | — | — | volume never backed up since 2026-07-27 |

## Layout

```
hub/intake/
  MANIFEST.md              this board
  claims/<project>.yaml    what the project SAID   (pasted verbatim, never edited)
  verified/<project>.json  what the MACHINE says   (derived, regenerable)
  diffs/<project>.md       the reconciliation      (the actual deliverable)
```

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

```
1  fksinv      ksgcohub      most of its blueprint is already in hand
2  metaforge   fks-services  4 missing SQL migrations — urgent
3  babyhelp    ksgcohub      4 known deviations
4  flarevault  fks-services  volume unbacked since 2026-07-27
```

One at a time, each fully reconciled before the next starts. Four half-done
intakes tell you less than one finished one.
