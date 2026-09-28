# flarevault — port migration packet (fks-services)

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
> curl -s <hub>/api/registry/flarevault           the standing record
> curl -s <hub>/api/registry/flarevault/diffs     differences + dispositions
> curl -s "<hub>/api/admit?project=flarevault"    the rules, derived live
> ```

---

## What the machine says

| | |
|---|---|
| host | `fks-services` (admin1@192.168.1.229) |
| classified | **project** |
| grouped by | derived |
| containers | 2 (0 carry `com.ksg.project`) |
| compose | *none on the host* |
| published ports | 7777 |
| stopped containers | none |

## Where each port stands

| port | verdict | what that means |
|---|---|---|
| 7777 | `old-band` | the band this replaced (7100-7899) |

## The offer

**Proposed block: `12100–12199`** — first wholly-free block

Per-port mapping. The last two digits follow the role
convention in `kernel/collect.py`, which that file marks
**suggested, never enforced** — the block is the boundary, the
split inside it belongs to the project.

| now | proposed | note |
|---|---|---|
| 7777 | 12120 | rebind |

- no compose file on the host — the `fix` commands are incomplete by construction, not by oversight

## The differences, and why each is one

### 1. binds inside this server's project band

- **machine:** publishes 7777, outside 12000-18999
- **why it matters:** the band is the one lane this server promises not to hand to anything else. Outside it the port belongs to whoever got there first, and nothing announces the day that changes. This is a difference, not a fault: the band moved on 2026-09-24 and existing projects keep their ports until they choose to move.
- **if `fix`:** nothing, if the answer is `accept`. To move: rebind to 12100-12199 in the compose file, `docker compose up -d`, then re-file the claim.

### 2. binds inside the current project band

- **machine:** publishes 7777, inside the PREVIOUS band 7100-7899
- **why it matters:** this is the band /api/admit advertised until 2026-09-24. A port here is a project that complied with the contract of the day, so the deviation is the contract moving, not the project drifting.
- **if `fix`:** nothing is required. To move, see the commands in this project's packet under hub/intake/working/.

### 3. com.ksg.project=flarevault on every container

- **machine:** 2 container(s) match by derived, 0 carry the label
- **why it matters:** Constitution VI: `docker ps --filter label=com.ksg.project=flarevault` returns 0 of 2. Nothing on the host can attribute these containers, so this tool had to derive the grouping -- and a port table built on a derived grouping is only as good as the guess underneath it.
- **if `fix`:** add `labels: ["com.ksg.project=flarevault"]` to each service in the compose file. Labels are immutable on a running container, so it takes effect on the next recreate -- with no extra downtime ever, if it waits for one that was going to happen anyway.

### 4. a named project on fks-services

- **machine:** no label and no compose project; the name "flarevault" was derived from the container names
- **why it matters:** this project exists in this report because a tool split a container name on a hyphen. That is a guess, and it is the only thing holding these containers together as one thing. If the guess is wrong every row above is wrong with it.
- **if `fix`:** confirm or correct the name, then declare it with com.ksg.project so nothing has to guess again.

## If the disposition is `fix` — the exact commands

Nothing below has been run and nothing in this repo will run it.
It is here so the work is not research.

```bash
# on fks-services  (ssh admin1@192.168.1.229)
#
# THERE IS NO PLAN HERE YET, AND THAT IS THE FINDING.
# flarevault carries no compose project and no config_files label, so
# there is no file to edit and this tool will not invent a path.
# 2 container(s) are running with nothing on disk that is known
# to reproduce them. Rebinding is the second question; the first
# is whether this survives the host being rebuilt.
#
# Establish that first -- all three are reads:
docker inspect flarevault-node flarevault-monitor --format '{{json .Config.Labels}}'
docker inspect flarevault-node flarevault-monitor --format '{{.Name}} {{.HostConfig.RestartPolicy.Name}} {{json .HostConfig.PortBindings}}'
grep -rl "flarevault" /srv/docker ~/ --include="*.yml" --include="*.yaml" 2>/dev/null
#
# Once a file is found, re-run:
#   python3 hub/tools/migrate-ports.py --write
# and this section becomes the port table it should have been.
#
# Proposed block, for when there is somewhere to write it: 12100-12199
#   7777 -> 12120
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
