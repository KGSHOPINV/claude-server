# babyhelp — standing record

**Home server: ksgcohub** (`fvn_685a59`). This record is meaningless away from
that machine: every rule below is derived from ITS disks and ITS bound ports.

Last verified 2026-09-24 against the machine, not against a claim.
Intake state: `awaiting` — no claim filed yet. Everything here is observed.

---

## Acknowledgement — the part the project owes

A project is not a thing the server observes. It is a party to an agreement,
and this is the line that proves it.

```
server master    5ca90f6          what ksgcohub is running RIGHT NOW
acknowledged     none             the last master babyhelp confirmed it read
stale            YES — never acknowledged
```

**Rule:** when a server's master moves, every project on it goes `stale` until
it acknowledges the new one. Stale is not a failure — it is "this project has
not been told, so do not assume it knows."

Acknowledging means three things, and the third is the one that matters:

1. read this record
2. read PENDING below
3. **record what it will DO about PENDING** — even if the answer is "nothing,
   it does not affect me." An unanswered pending change is how a project ends
   up bound to a port that moved.

Nothing is enforced. A project can sit stale forever. But the server will say
so, out loud, every time anyone asks what is on it — and that is the point:
silence stops being mistaken for agreement.

## Status points

| | | |
|---|---|---|
| running | ✅ | `Up`, `restart=unless-stopped`, never restarted during any of this work |
| backed up | ✅ | in the daily 03:00 job since 2026-09-24, restore-verified |
| labelled | ❌ | 0 of 3 containers carry `com.ksg.project` |
| in band | ❌ | publishes 12080, outside any assigned band |
| data placed | ❌ | named volume on the OS disk, not the data disk |
| declared | ❌ | no claim filed |
| acknowledged | ❌ | has never acknowledged a server master |

**Reconciled: no.** Four differences, none of them disposed.

Note what is NOT a problem here: it works, it has never fallen over, and its
data is now protected. The gaps are all *legibility* — the machine cannot say
what belongs to babyhelp, so babyhelp is invisible to everything that reasons
about the server.

## What the machine observes

```
containers   babyhelp          babyhelp:latest             12080 -> 8080
             babyhelp-redis    redis:7-alpine              (internal)
             babyhelp-tunnel   cloudflared:latest          (egress only)
network      babyhelp
compose      /home/ksgco/babyhelp/compose.yaml
data         volume babyhelp-data   → babyhelp.db + sessions.lmdb   ~1MB
             volume babyhelp-redis  → 358 bytes
backups      /backups/<date>/vol-babyhelp-data.tar.gz   daily, different device
```

## Differences, and why each matters

| # | Machine says | Contract says | Why it matters | Disposition |
|---|---|---|---|---|
| 1 | no `com.ksg.*` labels | `project`/`owner`/`role`/`data` | `docker ps --filter label=com.ksg.project=babyhelp` returns **0 of 3**. Nothing can attribute these containers | — |
| 2 | publishes 12080 | band assigned from free space | outside any band. Collides with nothing today; nothing prevents it tomorrow | — |
| 3 | data in a named volume on `/` | `/srv/data/babyhelp/{db,media,cache}` | 1MB today. At 40GB of uploads this stops being cheap to move | — |
| 4 | compose at `~/babyhelp/` | `/srv/docker/babyhelp/` | the host has no record it exists; the compose is only in a home directory | — |

All four need a container recreate — labels are immutable on a running
container. **None of them need to be fixed.** `accept` is a valid disposition
and costs nothing.

**Cheapest real fix, if wanted:** add the labels to `compose.yaml` now. They do
nothing until the next restart, so the next time babyhelp restarts for any
reason it comes back legible — zero extra downtime, ever.

## Pending — what moves underneath it

```
band moves 10020-10990 -> 7100-7899 on the next deploy
  why: 10000-10999 is the Supabase stack's reserved lane
  effect on babyhelp: none today — 12080 is outside both. Difference #2
                      stands either way.
  babyhelp's answer: — NOT RECORDED
```

The last line is what acknowledgement produces. Blank means nobody has said
whether this matters to babyhelp — which is different from it not mattering.

## History

```
2026-09-24  first backup captured (86K, babyhelp.db + sessions.lmdb verified)
2026-09-24  verified against the machine; 4 differences recorded
2026-09-23  observed during storage work; never touched
```

---

*Derived sections are regenerated from the machine and are disposable.
Dispositions and history cannot be re-derived and are backed up.*
