# fksinv — port migration packet (ksgcohub)

**This project is not ours to change.** Read to describe; never touch.
Nothing in this file is an instruction to anyone but the project's own
owner, and nothing in it has been run against anything.

> **This is a `working/` file, not a standing record.** MANIFEST.md
> defines `working/` as the claim being verified against its host, so
> unlike `projects/<name>.md` this one DOES carry observed values —
> it is regenerated on every run and is disposable by construction.
> The standing record stays in `control.db`:
>
> ```bash
> curl -s <hub>/api/registry/fksinv           the standing record
> curl -s <hub>/api/registry/fksinv/diffs     differences + dispositions
> curl -s "<hub>/api/admit?project=fksinv"    the rules, derived live
> ```

---

## What the machine says

| | |
|---|---|
| host | `ksgcohub` (ksgco@100.107.234.9) |
| classified | **project** |
| grouped by | compose |
| containers | 2 (0 carry `com.ksg.project`) |
| compose | `/srv/docker/fksinv/docker-compose.yml` |
| published ports | 10100, 10101 |
| stopped containers | none |

## Where each port stands

| port | verdict | what that means |
|---|---|---|
| 10100 | `reserved-lane` | inside the Supabase stack lane 10000-10999, which /api/admit used to hand out |
| 10101 | `reserved-lane` | inside the Supabase stack lane 10000-10999, which /api/admit used to hand out |

## The offer

**Proposed block: `12300–12399`** — first wholly-free block

Per-port mapping. The last two digits follow the role
convention in `kernel/collect.py`, which that file marks
**suggested, never enforced** — the block is the boundary, the
split inside it belongs to the project.

| now | proposed | note |
|---|---|---|
| 10100 | 12320 | rebind |
| 10101 | 12300 | rebind |

## The differences, and why each is one

### 1. binds inside this server's project band

- **machine:** publishes 10100, 10101, outside 12000-18999
- **why it matters:** the band is the one lane this server promises not to hand to anything else. Outside it the port belongs to whoever got there first, and nothing announces the day that changes. This is a difference, not a fault: the band moved on 2026-09-24 and existing projects keep their ports until they choose to move.
- **if `fix`:** nothing, if the answer is `accept`. To move: rebind to 12300-12399 in /srv/docker/fksinv/docker-compose.yml, `docker compose up -d`, then re-file the claim.

### 2. binds in a lane no other stack owns

- **machine:** publishes 2 port(s) inside 10000-10999: 10100, 10101
- **why it matters:** THIS ONE IS PROBABLY OURS. /api/admit declared the project band as 10020-10990 while kernel/collect.py already gave 10000-10999 to the Supabase stack, so a project that bound here did what it was told. `hub-wrong` is the likely disposition and it is a finding about ServerHub, not about this project.
- **if `fix`:** record the disposition. If `hub-wrong`, the contract is what changes, not the project.

### 3. com.ksg.project=fksinv on every container

- **machine:** 2 container(s) match by compose, 0 carry the label
- **why it matters:** Constitution VI: `docker ps --filter label=com.ksg.project=fksinv` returns 0 of 2. Nothing on the host can attribute these containers, so this tool had to derive the grouping -- and a port table built on a derived grouping is only as good as the guess underneath it.
- **if `fix`:** add `labels: ["com.ksg.project=fksinv"]` to each service in /srv/docker/fksinv/docker-compose.yml. Labels are immutable on a running container, so it takes effect on the next recreate -- with no extra downtime ever, if it waits for one that was going to happen anyway.

## If the disposition is `fix` — the exact commands

Nothing below has been run and nothing in this repo will run it.
It is here so the work is not research.

```bash
# on ksgcohub  (ssh ksgco@100.107.234.9)
# nothing below has been run. Read it, then run it yourself.

# 1. confirm this is the file that is actually live
docker compose -f /srv/docker/fksinv/docker-compose.yml config | head -40

# 2. the port lines to change, in /srv/docker/fksinv/docker-compose.yml
#    fks-api                       "10100:8000"  ->  "12320:8000"   (api)
#    fks-ui                        "10101:80"  ->  "12300:80"   (ui)

# 3. apply -- recreates only what changed.
#    -p is required: the directory is `fksinv`, the compose project is
#    `fksinv`, and a bare `up -d` would use the directory name.
docker compose -f /srv/docker/fksinv/docker-compose.yml -p fksinv up -d

# 4. prove it, from the host
# the contract's acceptance test would return 0 rows here --
# this project carries no com.ksg.project label. Using the
# channel that does answer, and this substitution is itself
# one of the differences above:
docker compose -f /srv/docker/fksinv/docker-compose.yml ps --format '{{.Name}} {{.Ports}}'
ss -tln | grep -E ":(12320|12300)\b"

# 5. tell the hub, so /api/admit stops believing the old numbers
curl -s -X POST http://127.0.0.1:8765/api/registry/fksinv -d '{"ports": [12300, 12320]}'

# ROLLBACK: git checkout the compose file and `docker compose up -d`.
#   The old ports are released the moment the new ones bind, so a
#   rollback that is not immediate can find them taken. Do it in one
#   sitting or not at all.
```

## The dispositions, and who gives them

| | |
|---|---|
| `fix` | the project will move. **The project decides, never the hub.** |
| `accept` | deliberate, and it stays. Needs no justification beyond being deliberate. |
| `defer` | real, not now, with a reason. |
| `hub-wrong` | the contract is wrong, not the project. ServerHub changes. |

**Reconciled means every difference has a disposition — not that
every difference is fixed.** A project that answers `accept` to
all of the above is fully reconciled and its migration is over.
An undeclared deviation is the only failure state.

---

*Regenerated by `python3 hub/tools/migrate-ports.py --write`.
Dispositions are not stored here and cannot be re-derived; they
live in `control.db` and are what gets backed up.*
