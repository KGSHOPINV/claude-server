# babyhelp — standing record

**This project is not ours.** Read to describe; never change. Nothing in this
file is an instruction to touch anything belonging to babyhelp, and nothing
here has ever been changed on its behalf.

**It has one home server**, and this record is meaningless away from that
machine: every rule below is derived from ITS disks and ITS bound ports.

> **No observed values are written in this file, and none should be.**
> `control.db` already holds this record, and a markdown copy beside it is two
> sources of truth for one fact — the precise disease this system exists to
> remove. The observed half is re-derived on every verify and is disposable.
>
> ```bash
> curl -s <hub>/api/registry/babyhelp           the standing record
> curl -s <hub>/api/registry/babyhelp/diffs     the differences and dispositions
> curl -s "<hub>/api/admit?project=babyhelp"    the rules, derived live from the host
> ```
>
> What stays here is what a command cannot supply: **what this record is for,
> and why each difference is a difference.**

---

## Acknowledgement — the part the project owes

A project is not a thing the server observes. It is a party to an agreement,
and the acknowledgement is the line that proves it.

**Rule:** when a server's master moves, every project on it goes `stale` until
it acknowledges the new one. **Stale is not a failure** — it means *"this
project has not been told, so do not assume it knows."*

Acknowledging means three things, and the third is the one that matters:

1. read this record
2. read PENDING
3. **record what it will DO about PENDING** — even if the answer is *"nothing,
   it does not affect me."* An unanswered pending change is how a project ends
   up bound to a port that moved underneath it.

**Nothing is enforced.** A project can sit stale forever. But the server will
say so, out loud, every time anyone asks what is on it — and that is the point:
**silence stops being mistaken for agreement.**

---

## Why this project is the case the whole system exists for

babyhelp was built by someone who knew nothing about this machine, and **there
was nothing to ask.** No endpoint told it where to bind, where data goes, what
labels to carry, or what was forbidden — and there would have been no answer if
there had been.

It works. It has never fallen over. **None of that is the builder's fault**, and
none of the gaps below are failures of the project.

---

## The four differences, and why each is one

Stated as classes, because the values are derived and the dispositions live in
`control.db`.

| Difference | Why it matters |
|---|---|
| **no `com.ksg.*` labels** | `docker ps --filter label=com.ksg.project=babyhelp` returns **none of its containers**. Nothing on the host can attribute them, so the project is invisible to everything that reasons about the server. Ownership must be declared *by the thing itself* — a label travels with the container; a registry beside it drifts |
| **publishes outside any assigned band** | It collides with nothing today. Nothing prevents it colliding tomorrow, and nothing would tell anyone when it did |
| **data in a named volume on the OS disk** | Cheap to move while it is small. It stops being cheap, and the moment it stops being cheap is not announced |
| **compose file in a home directory** | The host has no record the project exists. A machine cannot read a file it was never told about |

**All four need a container recreate — labels are immutable on a running
container. None of them need to be fixed.** `accept` is a valid disposition, it
needs no justification beyond being deliberate, and it costs nothing.

**Reconciled means every difference has a disposition — not that every
difference is fixed.** Four accepted deviations is fully reconciled. **An
undeclared deviation is the only failure state.**

**The cheapest real fix, if wanted:** add the labels to the compose file. They
do nothing until the next restart, so the next time the project restarts for
any reason it comes back legible — with zero extra downtime, ever.

---

## Pending — what moves underneath it

The PENDING block is the answer to *"is anything about to change under me"*, and
its rules are:

- **Empty is reported as `none`, never omitted.** Silence and nothing-pending
  are different answers and only one of them is information.
- **It must be derived from the release records, not hardcoded.** A constant
  reports one change forever and never reports the next one.
- **A blank answer line is not "it does not matter."** It means nobody has said
  whether it matters, which is a different and less comfortable state.

---

## History

```
2026-09-23  observed during storage work; never touched
2026-09-24  verified against the machine, not against a claim; differences recorded
2026-09-24  first backup captured and restore-verified
```

---

*Derived sections are regenerated from the machine and are disposable.
Dispositions and history cannot be re-derived, so they are what gets backed up.*
