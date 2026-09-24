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
