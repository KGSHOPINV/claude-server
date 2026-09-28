# keynox — port migration packet (fks-services)

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
> curl -s <hub>/api/registry/keynox           the standing record
> curl -s <hub>/api/registry/keynox/diffs     differences + dispositions
> curl -s "<hub>/api/admit?project=keynox"    the rules, derived live
> ```

---

## What the machine says

| | |
|---|---|
| host | `fks-services` (admin1@192.168.1.229) |
| classified | **project** |
| grouped by | compose, name |
| containers | 18 (0 carry `com.ksg.project`) |
| compose | `/srv/docker/metaforge/docker-compose.yml` |
| published ports | 7700, 10001, 10003, 10004, 10005, 10006, 10007, 10008, 10009, 10011, 10012, 10013, 10014, 10015, 10016, 10018 |
| stopped containers | none |

## Where each port stands

| port | verdict | what that means |
|---|---|---|
| 7700 | `old-band` | the band this replaced (7100-7899) |
| 10001 | `reserved-lane` | inside the Supabase stack lane 10000-10999, which /api/admit used to hand out |
| 10003 | `reserved-lane` | inside the Supabase stack lane 10000-10999, which /api/admit used to hand out |
| 10004 | `reserved-lane` | inside the Supabase stack lane 10000-10999, which /api/admit used to hand out |
| 10005 | `reserved-lane` | inside the Supabase stack lane 10000-10999, which /api/admit used to hand out |
| 10006 | `reserved-lane` | inside the Supabase stack lane 10000-10999, which /api/admit used to hand out |
| 10007 | `reserved-lane` | inside the Supabase stack lane 10000-10999, which /api/admit used to hand out |
| 10008 | `reserved-lane` | inside the Supabase stack lane 10000-10999, which /api/admit used to hand out |
| 10009 | `reserved-lane` | inside the Supabase stack lane 10000-10999, which /api/admit used to hand out |
| 10011 | `reserved-lane` | inside the Supabase stack lane 10000-10999, which /api/admit used to hand out |
| 10012 | `reserved-lane` | inside the Supabase stack lane 10000-10999, which /api/admit used to hand out |
| 10013 | `reserved-lane` | inside the Supabase stack lane 10000-10999, which /api/admit used to hand out |
| 10014 | `reserved-lane` | inside the Supabase stack lane 10000-10999, which /api/admit used to hand out |
| 10015 | `reserved-lane` | inside the Supabase stack lane 10000-10999, which /api/admit used to hand out |
| 10016 | `reserved-lane` | inside the Supabase stack lane 10000-10999, which /api/admit used to hand out |
| 10018 | `reserved-lane` | inside the Supabase stack lane 10000-10999, which /api/admit used to hand out |

## The offer

**Proposed block: `12200–12299`** — first wholly-free block

Per-port mapping. The last two digits follow the role
convention in `kernel/collect.py`, which that file marks
**suggested, never enforced** — the block is the boundary, the
split inside it belongs to the project.

| now | proposed | note |
|---|---|---|
| 7700 | 12240 | rebind |
| 10001 | 12241 | rebind |
| 10003 | 12242 | rebind |
| 10004 | 12243 | rebind |
| 10005 | 12220 | rebind |
| 10006 | 12221 | rebind |
| 10007 | 12222 | rebind |
| 10008 | 12223 | rebind |
| 10009 | 12244 | rebind |
| 10011 | 12224 | rebind |
| 10012 | 12260 | rebind |
| 10013 | 12245 | rebind |
| 10014 | 12246 | rebind |
| 10015 | 12225 | rebind |
| 10016 | 12200 | rebind |
| 10018 | 12226 | rebind |

## The differences, and why each is one

### 1. binds inside this server's project band

- **machine:** publishes 7700, 10001, 10003, 10004, 10005, 10006, 10007, 10008, 10009, 10011, 10012, 10013, 10014, 10015, 10016, 10018, outside 12000-18999
- **why it matters:** the band is the one lane this server promises not to hand to anything else. Outside it the port belongs to whoever got there first, and nothing announces the day that changes. This is a difference, not a fault: the band moved on 2026-09-24 and existing projects keep their ports until they choose to move.
- **if `fix`:** nothing, if the answer is `accept`. To move: rebind to 12200-12299 in /srv/docker/metaforge/docker-compose.yml, `docker compose up -d`, then re-file the claim.

### 2. binds in a lane no other stack owns

- **machine:** publishes 15 port(s) inside 10000-10999: 10001, 10003, 10004, 10005, 10006, 10007, 10008, 10009, 10011, 10012, 10013, 10014, 10015, 10016, 10018
- **why it matters:** THIS ONE IS PROBABLY OURS. /api/admit declared the project band as 10020-10990 while kernel/collect.py already gave 10000-10999 to the Supabase stack, so a project that bound here did what it was told. `hub-wrong` is the likely disposition and it is a finding about ServerHub, not about this project.
- **if `fix`:** record the disposition. If `hub-wrong`, the contract is what changes, not the project.

### 3. binds inside the current project band

- **machine:** publishes 7700, inside the PREVIOUS band 7100-7899
- **why it matters:** this is the band /api/admit advertised until 2026-09-24. A port here is a project that complied with the contract of the day, so the deviation is the contract moving, not the project drifting.
- **if `fix`:** nothing is required. To move, see the commands in this project's packet under hub/intake/working/.

### 4. publishes from one contiguous range

- **machine:** 16 ports across 2 different ranges: old-band, reserved-lane
- **why it matters:** scattered ports have no start and no end, so nothing can say where this project begins or what it would collide with. This is the condition PROJECT_BAND_SIZE=100 exists to end.
- **if `fix`:** see the per-port mapping in the packet; it is one rebind per port and one `docker compose up -d`.

### 5. com.ksg.project=keynox on every container

- **machine:** 18 container(s) match by compose / name, 0 carry the label
- **why it matters:** Constitution VI: `docker ps --filter label=com.ksg.project=keynox` returns 0 of 18. Nothing on the host can attribute these containers, so this tool had to derive the grouping -- and a port table built on a derived grouping is only as good as the guess underneath it.
- **if `fix`:** add `labels: ["com.ksg.project=keynox"]` to each service in /srv/docker/metaforge/docker-compose.yml. Labels are immutable on a running container, so it takes effect on the next recreate -- with no extra downtime ever, if it waits for one that was going to happen anyway.

## If the disposition is `fix` — the exact commands

Nothing below has been run and nothing in this repo will run it.
It is here so the work is not research.

```bash
# on fks-services  (ssh admin1@192.168.1.229)
# nothing below has been run. Read it, then run it yourself.

# 1. confirm this is the file that is actually live
docker compose -f /srv/docker/metaforge/docker-compose.yml config | head -40

# 2. the port lines to change, in /srv/docker/metaforge/docker-compose.yml
#    keynox-10-meilisearch-1       "7700:7700"  ->  "12240:7700"   (data)
#    keynox-01-postgres-17.6       "10001:5432"  ->  "12241:5432"   (data)
#    keynox-03-redis-7             "10003:6379"  ->  "12242:6379"   (data)
#    keynox-04-surrealdb-3         "10004:8000"  ->  "12243:8000"   (data)
#    keynox-05-kong-3.9            "10005:8000"  ->  "12220:8000"   (api)
#    keynox-05-kong-3.9            "10006:8443"  ->  "12221:8443"   (api)
#    keynox-api-1.0                "10007:8080"  ->  "12222:8080"   (api)
#    keynox-08-postgraphile-4.14   "10008:5000"  ->  "12223:5000"   (api)
#    keynox-09-pgbouncer-1         "10009:5432"  ->  "12244:5432"   (data)
#    keynox-14-gotenberg-8         "10011:3000"  ->  "12224:3000"   (api)
#    keynox-12-n8n-1               "10012:5678"  ->  "12260:5678"   (worker)
#    keynox-13-minio-1             "10013:9000"  ->  "12245:9000"   (data)
#    keynox-13-minio-1             "10014:9001"  ->  "12246:9001"   (data)
#    keynox-15-imgproxy-3          "10015:8080"  ->  "12225:8080"   (api)
#    keynox-16-studio-1            "10016:3000"  ->  "12200:3000"   (ui)
#    keynox-18-ai-mcp-1.0          "10018:8018"  ->  "12226:8018"   (api)

# 3. apply -- recreates only what changed.
#    -p is required: the directory is `metaforge`, the compose project is
#    `keynox`, and a bare `up -d` would use the directory name.
docker compose -f /srv/docker/metaforge/docker-compose.yml -p keynox up -d

# 4. prove it, from the host
# the contract's acceptance test would return 0 rows here --
# this project carries no com.ksg.project label. Using the
# channel that does answer, and this substitution is itself
# one of the differences above:
docker compose -f /srv/docker/metaforge/docker-compose.yml ps --format '{{.Name}} {{.Ports}}'
ss -tln | grep -E ":(12240|12241|12242|12243|12220|12221|12222|12223|12244|12224|12260|12245|12246|12225|12200|12226)\b"

# 5. tell the hub, so /api/admit stops believing the old numbers
curl -s -X POST http://127.0.0.1:8765/api/registry/keynox -d '{"ports": [12200, 12220, 12221, 12222, 12223, 12224, 12225, 12226, 12240, 12241, 12242, 12243, 12244, 12245, 12246, 12260]}'

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
