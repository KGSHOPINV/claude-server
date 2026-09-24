# ServerHub — Bill of Materials

**What this machine's source tree is made of.**

Provenance: working tree at `HEAD = db07c5e`, branch `fix/project-port-band`,
derived 2026-09-24T02:15Z. The cleanup of 2026-09-23 is **present in the working
tree and not yet committed** — 10 files deleted, 16 modified, `-11,998 / +1,436`.
Every number here is the working tree, not `HEAD`.

Per `hub/CONSTITUTION.md` §4, **a BOM may never be prose.** This file is prose
under protest: the derivation does not yet exist as a single command, so what
this file does instead is pair every count with the command that produced it.
Section 9 is the whole list. If a section cannot be checked by running
something, it does not belong here.

> **The honest caveat.** This document is a snapshot of a derivation, which is
> exactly the artifact §4 warns about. It starts rotting the moment it is saved.
> Treat §9 as the real BOM and this file as its cached output. The fix is
> `GET /api/receipt` emitting these sections; until then, re-run §9.

---

## 1. Counts

113 files, 25,472 lines, excluding `.git/` and gitignored files
(`CLAUDE.md`, `db/server.db`, `__pycache__/`).

| Type | Files | Lines | What it is |
|---|---:|---:|---|
| Python | 32 | 6,781 | the hub runtime, its tools, the maintenance agent |
| Markdown | 32 | 4,523 | blueprint + knowledge (§7) |
| HTML | 6 | 8,671 | two frontends, a docs site, a manual |
| Shell | 17 | 1,487 | installer, enrol, backup, reclaim, alerting |
| JSON | 5 | 3,547 | telescope code map + generated registry |
| Batch | 11 | 123 | Windows launchers for the work PC |
| JS | 3 | 120 | the view registry served at `/ui/` |
| systemd | 4 | 49 | 3 `.service`, 1 `.timer` |
| SQL | 1 | 147 | `knowledge/decisions.sql` |
| TOML | 1 | 9 | `netlify.toml` |
| `.gitignore` | 1 | 15 | |

**Prose-to-code.** Two honest readings, because "code" is a choice:

- Markdown vs executable code (py + sh + js + bat = 8,511): **0.53 : 1**
- Markdown vs all non-prose, non-data (+ html, sql, toml, units = 17,387): **0.26 : 1**

Neither is alarming. The number that *is* alarming is in §7: of 32 markdown
files, **3 can be falsified by running something**. The rest are assertions with
no failure mode — Law II of the constitution, violated 29 times.

`hub/app.html` alone is 5,774 lines: larger than the entire Python runtime it
talks to.

---

## 2. Runtime parts

Entry point: `hub/server.py` (152 lines). It does four things — bootstrap the
DB, start two daemon threads (port scanner, Docker event watcher), start the
heartbeat emitter if this node is not central, and hand every request to
`kernel.router.dispatch`. There is no route logic in it.

### Kernel — `hub/kernel/` (11 files, 3,089 lines)

| Module | Lines | Owns | Imported by |
|---|---:|---|---|
| `collect.py` | 1,457 | Docker, ports, storage, system-state collectors; the port-scan loop | 5 handlers + `server.py` |
| `router.py` | 283 | `ROUTES` (73 entries), the exact/prefix index, dispatch, gate evaluation | `server.py` only |
| `storage.py` | 284 | the storage landscape derived from the machine (module 20200013) | `handlers/node`, `kernel/collect`, 2 tools |
| `identity.py` | 207 | `server.identity.json`, node/central mode, HS256 tokens | 3 handlers, `heartbeat`, `server.py`, `install-preflight` |
| `fleet.py` | 195 | central-side fleet registry + status state machine | `handlers/mesh` **only** |
| `heartbeat.py` | 184 | node-side 30s emitter and its fallback chain | `server.py` only |
| `auth.py` | 174 | sessions, gate tokens, TOTP | 10 handlers + `router` |
| `log.py` | 165 | activity log, ntfy push, Docker event watcher | 8 handlers + `collect` + `server.py` |
| `db.py` | 102 | the only SQLite connection; schema bootstrap | 11 handlers + `collect` + `server.py` + `install-preflight` |
| `ssh.py` | 38 | the SSH bridge (`ssh_run`, `SSH_HOST`) | 7 handlers + `collect` + `server.py` |
| `__init__.py` | 0 | | |

`collect.py` is 47% of the kernel and is the obvious next split. `fleet.py` and
`heartbeat.py` each have exactly one importer, which is what a clean seam looks
like.

### Handlers — `hub/handlers/` (13 files, 2,518 lines)

Every handler imports from `kernel/`, and nothing imports a handler except
`server.py` (`handlers.node.node_payload`) and the router's `importlib` by name.
The layering holds.

| Module | Lines | Routes | Owns |
|---|---:|---:|---|
| `proxy.py` | 419 | 4 | reverse proxy, guide listing/content, file listing |
| `status.py` | 330 | 21 | Docker status, ports, storage, receipt, sync, sitemap |
| `users.py` | 323 | 10 | login/logout, user CRUD, TOTP setup/verify/disable |
| `node.py` | 287 | 2 | this node's full self-description; `/api/admit` |
| `identity.py` | 222 | 10 | serves both frontends, manifest, sw.js, identity, access |
| `ai.py` | 194 | 3 | AI chat + config (stack stays off by default) |
| `ops.py` | 165 | 4 | run, update, service install — all gate 2 or 3 |
| `federation.py` | 163 | 3 | peer mesh, peer registration |
| `config.py` | 131 | 7 | vault pointers, config, journal, issues |
| `mesh.py` | 98 | 3 | heartbeat receiver, mesh register, fleet view |
| `tunnel.py` | 98 | 2 | Cloudflare tunnel start/stop |
| `events.py` | 87 | 4 | incidents, activity |
| `__init__.py` | 1 | 0 | |

**Assertion that passes:** all 73 routes name a handler function that exists in
the module the route claims. 0 missing. (§9.2)

---

## 3. Routes

**73 routes, 65 unique paths** (8 paths carry both GET and POST), declared in
`hub/kernel/router.py:ROUTES`. 46 GET, 27 POST. 3 are prefix matches:
`/ui/`, `/api/docker/action/`, `/proxy/`. All 73 telescope codes are unique.

| Module | Routes |   | Gate | Routes |
|---|---:|---|---|---:|
| status | 21 | | 0 — public | 18 |
| identity | 10 | | 1 — user | 37 |
| users | 10 | | 2 — admin | 14 |
| config | 7 | | 3 — TOTP | 4 |
| events / proxy / ops | 4 each | | | |
| mesh / federation / ai | 3 each | | | |
| node / tunnel | 2 each | | | |

### How many are enforced: **zero**

55 of 73 routes declare a gate above 0. `ENFORCE_GATES` reads
`HUB_ENFORCE_GATES`, defaults to `'0'`, and **nothing in this repo sets it** —
only prose mentions it. Denials are appended to `_shadow_denials` (cap 500) and
the request proceeds. `kernel.router.shadow_report()` returns them; no route
exposes it, so the diagnostic is unreachable over HTTP.

The reason it is off is honest and stated in the source: the UI sends a token on
15 of its calls (`X-Hub-Token` ×13, `X-Gate-Token` ×2 in `app.html`; ×1 each in
`mobile.html`). Arming the gate today locks the app out of itself.

### Three counts of the same thing, all different

| Claim | Where | Actual |
|---|---|---|
| "52 of 65 routes gated" | `hub/kernel/router.py:180` | **55 of 73** |
| "52 of 73 routes declare a gate" | `hub/FABRIC.md:168` | **55 of 73** |
| "app.html sends a token on 16 calls" | `AGENTS.md:126` | **15** |

Three prose copies of a number that `ROUTES` already knows. This is Law I in
miniature, and the cheapest thing in this document to fix.

### `/api/sitemap` is a second, drifting route table

`handlers/status.py:get_sitemap` hand-maintains its own list: **50 of the 65
paths**. Missing 15: `/api/admit`, `/api/auth/provider`, `/api/docker/action/`,
`/api/heartbeat`, `/api/incidents`, `/api/mesh/fleet`, `/api/mesh/register`,
`/api/node`, `/api/setup/status`, `/desktop`, `/manifest.json`, `/mobile`,
`/proxy/`, `/sw.js`, `/ui/`. Nothing in it is fictional — the drift is one
direction, omission only. `kernel.router.routes_by_module()` exists with no
callers precisely as the seam for generating this instead.

---

## 4. Interface

### `hub/app.html` — 5,774 lines, 318 KB, one `<style>` block, 662 CSS rules, 182 `id=` attributes

One external script: `/ui/registry.js`. Everything else is inline.

- **27 views render** (`case` arms in `mountPaneContent`)
- **28 views registered** in `hub/ui/registry.js`
- **24 offered in nav** (4 carry `hidden:true`: `iframe`, `blank`, `platform`, `tasks`)
- The one registered-but-unrendered entry is `blank`, the intentional fallback

`hub/tools/check-views.py` asserts both directions and **exits 0 today**. Before
2026-09-22 nine views rendered with no registry entry — a third of the app
reachable only by already knowing the view key.

### API coverage

Of 65 declared paths, **45 appear in a frontend file** and 19 appear in none
(`/` excluded — not testable by substring):

`/api/admit` `/api/auth/provider` `/api/heartbeat` `/api/identity`
`/api/incidents` `/api/journal` `/api/manifest` `/api/mesh/fleet`
`/api/mesh/register` `/api/node` `/api/peer/register` `/api/refresh`
`/api/service/install` `/api/sitemap` `/api/sync` `/api/vault` `/mobile`
`/proxy/` `/sw.js`

Most are machine-facing by design (heartbeat, mesh register, peer register,
admit) and should never appear in a frontend. `/api/vault`, `/api/journal` and
`/api/incidents` are the ones worth a look — user-facing endpoints with no user.

`app.html` references 39 distinct `/api/` paths.

### The second frontend — `hub/mobile.html`, 771 lines, 37 KB

A separate implementation. Shares no CSS, no registry and no JS with
`app.html`: its own `:root` token block, 115 CSS rules, 61 `id=` attributes,
zero external scripts.

Served by `handlers/identity.py:serve_app`, which sniffs the User-Agent for
`Mobile|Android|iPhone|iPad|iPod|BlackBerry|Windows Phone` and 302s `/` to
`/mobile`. `/desktop` forces `app.html`.

Five screens — Status, Servers, Actions, Shell, AI — against **9 API paths**:
`/api/status` `/api/containers` `/api/integrations` `/api/auth/login`
`/api/auth/check` `/api/totp/verify` `/api/run` `/api/ai/config` `/api/ai/chat`.

So the mobile client reaches **14% of the API** the desktop client reaches.
That is a design decision nobody wrote down; it is recorded here so it can be
argued with.

---

## 5. Tools — and what actually invokes them

This is the section that matters. A tool nothing calls is a document with a
shebang.

### `hub/tools/` (7 executables, 981 lines)

| Tool | Lines | Invoked by | Live? |
|---|---:|---|---|
| `backup.sh` | 200 | `bootstrap.sh:256` installs it to `~/.local/bin/hub-backup.sh`; `hub-backup.timer` daily 03:00 | **timer** |
| `reclaim.sh` | 25 | `bootstrap.sh:257`; `hub-reclaim.timer` Sun 04:00 | **timer** |
| `install-preflight.py` | 248 | `bootstrap.sh:41` (`--check` mode) and `:306` (end of install) | **installer + human** |
| `storage-preflight.py` | 88 | `bootstrap.sh:246`, step 6 | **installer + human** |
| `check-views.py` | 56 | nothing | **human only** |
| `flare-mode.sh` | 85 | nothing | **human only** |
| `registry_gen.py` | 279 | nothing | **human only** |

`check-views.py` and `registry_gen.py` are the two assertions in the repo that
nothing runs on a schedule or in CI. `check-views.py` costs about 0.2s. It
should be a pre-commit hook; the only reason it is not is that nobody wired it.

### `hub/scripts/` (4 shell scripts, 191 lines) — **nothing invokes any of them**

`alert-check.sh` (57), `alert-ai-explain.sh` (59), `alert-load.sh` (39),
`daily-summary.sh` (36). The only reference anywhere is `docs-site/index.html`
telling a reader to run two of them by hand.

### `scripts/` (4 shell scripts, 257 lines) — **nothing invokes these either**

`alert-check.sh` (47), `daily-summary.sh` (31), `check-in.sh` (58),
`verify-project.sh` (121).

**Two of these are near-duplicates of `hub/scripts/` files with the same name
and a different length** — `alert-check.sh` 47 vs 57, `daily-summary.sh` 31 vs
36. Neither pair is byte-identical; neither copy is invoked. The 2026-09-23
cleanup removed the duplicate `guides/` tree and missed this one.

### Root and elsewhere

| Tool | Lines | Invoked by |
|---|---:|---|
| `bootstrap.sh` | 337 | a human, once per node (§6) |
| `enroll.sh` | 232 | a human — **never executed against the live Cloudflare API** |
| `maintenance.py` | 222 | `hub-maintenance.timer`, 03:00 nightly |
| `update.sh` | 24 | a human; the deploy path this repaired was broken for weeks |
| `alert-startup.sh` | 19 | nothing |
| `server-kit/tools/boot-health-check.sh` | 69 | `boot-health-check.service`, oneshot at boot |
| `server-kit/tools/fix-netplan.sh` | 48 | a human, once |
| `hub/launcher.py` | 129 | `hub/build-exe.bat` (PyInstaller); Windows tray app |
| 11 `.bat` files | 123 | a human double-clicking on the work PC |

**Scheduled, total: 4.** `hub-backup.timer` (daily 03:00), `hub-reclaim.timer`
(Sun 04:00), `hub-maintenance.timer` (nightly 03:00),
`boot-health-check.service` (at boot).

**Invoked by nothing, total: 9** — 8 shell scripts plus `alert-startup.sh`.
That is 467 lines of alerting and check-in logic that has never run on a timer.

---

## 6. Install surface

### `bootstrap.sh` — 337 lines, 8 steps

| # | Step | What it does | Ends in an assertion? |
|---|---|---|---|
| — | `--check` | `exec`s `install-preflight.py --strict` and exits — convergence mode, installs nothing | n/a |
| 1 | Detecting OS | reads `/etc/os-release`, refuses non-Debian-family | inline |
| 2 | System packages | apt: python3, git, curl, sqlite3 etc. | no |
| 3 | Docker | official convenience script if absent | no |
| 4 | Setting up the hub | clone or `git pull` into `$HUB_DIR` | no |
| 5 | Starting hub service | writes and enables the user unit, waits for `:8765` | warns on failure |
| 6 | Checking storage | runs `tools/storage-preflight.py` | **yes** |
| 7 | Installing backups | installs `backup.sh` + `reclaim.sh` to `~/.local/bin`, writes `hub-backup.service`/`.timer` (03:00, 900s jitter) | no |
| 8 | Cache reclamation | writes `hub-reclaim.service`/`.timer` (Sun 04:00, 1800s jitter), `systemctl --user enable --now` both | no |
| — | Finished? | runs `install-preflight.py` non-strict and prints the verdict | **yes** |
| — | UFW | opens 22 and the hub port if `ufw` is present | no |

Steps 6–8 were `MASTER.md` steps 6–8 for months and did not exist. Commit
`fdc4276` wrote the scripts and `e0a9482` wired them in. The comment at
`bootstrap.sh:240` says so, in the file, next to the fix.

The installer does not declare itself finished. It asks.

### `hub/tools/install-preflight.py` — 248 lines, **10 assertions**

`hub/CAPABILITIES.md:96` still says 8. It is 10.

| Assertion | Asks the machine |
|---|---|
| hub service | is the unit active |
| identity | does `server.identity.json` exist and parse |
| data root | is the declared data root present |
| backup target | is there a backup device that is **not** the device holding the data |
| backups running | is `hub-backup` scheduled |
| cache reclamation | is `hub-reclaim` scheduled |
| storage sound | does the storage landscape derive cleanly |
| layout | is the hub's DB where the hub thinks it is |
| admin password | is the default password still in place |
| enrolled | does this node have a public hostname |

`--strict` exits 1 if any fail; a bare run prints `N of 10 complete`.
`check_reclamation` carries a comment recording that the assertion itself was
once wrong while the machine was right — which is the failure mode assertions
are supposed to prevent, documented where it happened.

**Constitution §5 gap, quantified:** the `MASTER.md` recipe has 11 steps,
`bootstrap.sh` implements 8, the preflight asserts 10. Three lists, not one map.

---

## 7. Documents — 32 markdown files, 4,523 lines

The column that matters is the last one.

### Product (`hub/`) — the three that define the thing

| File | Lines | For | Falsifiable by |
|---|---:|---|---|
| `hub/CONSTITUTION.md` | 175 | what ServerHub is: 6 laws, 4 artifacts, what it refuses | nothing |
| `hub/CAPABILITIES.md` | 147 | what it does for you, tool by tool | nothing — and it already says 8 preflight checks where there are 10 |
| `hub/FABRIC.md` | 242 | seven dimensions, three laws, the honest score | nothing — states "52 of 73 gated" where it is 55 |

### Blueprint (`docs/`) — reasoning, correctly prose per §4

| File | Lines | For | Falsifiable by |
|---|---:|---|---|
| `docs/flareshub-blueprint.md` | 390 | why FlareSHub is shaped this way; the ordered plan | nothing |
| `docs/flareshub-checklists.md` | 211 | per-script checklists; explicitly defers to `install-preflight.py` | partly — the executable section hands off to the tool |
| `docs/flareshub-frontend-dag.md` | 159 | frontend dependency order | nothing |
| `docs/refactor-plan.md` | 187 | the 2890→122 line `server.py` split, by phase | partly — names `registry_gen.py` as the source of truth |
| `docs/session-log-2026-09.md` | 144 | what was found and fixed, 09-10 → 09-16 | n/a, it is a log |
| `hub/docs/flarevault-designator.md` | 97 | the FlareVault contract this node implements | nothing |

### Workspace (root) — the personal layer §6 says must never ship to a node

| File | Lines | For | Falsifiable by |
|---|---:|---|---|
| `MASTER.md` | 350 | complete system reference; the 11-step recipe | nothing — its "backup" step was prose for months |
| `SYSTEM.md` | 349 | the system map, on-disk layout | **partly** — `install-preflight.check_layout` asserts the DB path it claims |
| `AGENTS.md` | 189 | AI session entry point | nothing — states 16 token calls where there are 15 |
| `CLAUDE.example.md` | 173 | template for the gitignored `CLAUDE.md` | nothing |
| `TASKS.md` | 165 | the task docket | n/a |
| `PORTS.md` | 128 | port bands and lane definitions | **partly** — `/api/admit` derives bands, `/api/ports` reports collisions |
| `REPOS.md` | 108 | the two-repo split | nothing |

### Guides served by the hub — `hub/guides/`, read by `GET /api/docs`

`architecture.md` (116), `deployment.md` (141), `docker.md` (65),
`remote-access.md` (233), `services.md` (60), `ssh.md` (63),
`troubleshooting.md` (103). **781 lines, served live** from
`GUIDES_DIR = hub/guides` (`handlers/proxy.py:22`). Nothing can falsify any of
them; they are operator knowledge, which §4 permits.

### Reference and notes — human onboarding, nothing executes them

`reference/beginner-guide.md` (140), `reference/linux-survival.md` (80),
`reference/docker-basics.md` (72), `reference/server-map.md` (61),
`reference/installation-map.md` (34, **marked SUPERSEDED 2026-09-23**),
`notes/troubleshooting-ssh-2026-07-31.md` (68), `notes/quick-ref.md` (28),
`issues/known-issues.md` (35, **marked SUPERSEDED 2026-09-23**),
`scripts/README.md` (10).

**Score: 3 of 32 documents can be falsified by running something** —
`SYSTEM.md` (partly, via `check_layout`), `PORTS.md` (partly, via `/api/admit`
and `/api/ports`), and `docs/flareshub-checklists.md` (by deferring to the
preflight). 29 cannot fail. Law II says that is 29 surfaces that can quietly
stop being true, and §3 of this document has already caught three of them doing
exactly that.

---

## 8. What was just deleted

The 2026-09-23 cleanup, sitting uncommitted in the working tree:
**10 files removed, 16 modified, −11,998 / +1,436 lines.**

| Removed | Bytes at `HEAD` | Why it was dead |
|---|---:|---|
| `backup/app.html.original` | 376,524 | pre-refactor snapshot; git is the backup |
| `backup/server.py.original` | 133,840 | the 3,119-line monolith `server.py` was split from |
| `__pycache__/server.cpython-314.pyc` | 67,472 | bytecode, already in `.gitignore` |
| `hub/maintenance.py` | 8,106 | **byte-identical** to root `maintenance.py`, which is the one `hub-maintenance.service` actually runs |
| `scripts/update-db.py` | 2,354 | superseded by `registry_gen.py` |
| `guides/services.md` | 2,184 | root copy of a guide; the hub serves `hub/guides/` |
| `guides/troubleshooting.md` | 2,091 | as above |
| `guides/docker.md` | 1,777 | as above |
| `guides/ssh.md` | 1,302 | as above |
| `hub.log` | 0 | an empty file tracked in git |

The four root `guides/*.md` were **not** byte-identical to their `hub/guides/`
namesakes — same topics, diverged content, and only the `hub/guides/` copies are
reachable over HTTP. The root set was unserved and unreferenced; that is why it
went.

Largest modifications: `knowledge/registry-live.json` (+1,226, regenerated by
`registry_gen.py` at 2026-09-24T01:33Z), `hub/kernel/collect.py` (551 lines
changed), `hub/app.html` (480), `knowledge/registry.json` (290),
`reference/installation-map.md` (187, reduced to a superseded pointer),
`SYSTEM.md` (106).

Generated registry state after that run: **141 codes matched, 69 shadow (in
source, not in the map), 11 dead (in the map, not in source), `clean: false`.**

---

## 9. How to regenerate this

Run from the repo root unless noted. Linux-only steps are marked.

**9.0 — the file list every other section uses**

```sh
git ls-files --cached --others --exclude-standard \
  | while read -r f; do [ -f "$f" ] && echo "$f"; done | sort > /tmp/live.txt
```

**9.1 — counts (§1)**

```sh
wc -l < /tmp/live.txt                               # 113
sed 's/.*\.//' /tmp/live.txt | sort | uniq -c | sort -rn
for e in py md html sh json js bat; do \
  printf "%-5s %3s files %6s lines\n" "$e" \
    "$(grep -c "\.$e$" /tmp/live.txt)" \
    "$(grep "\.$e$" /tmp/live.txt | tr '\n' '\0' | xargs -0 cat | wc -l)"; done
```

**9.2 — runtime parts and the import graph (§2)**

```sh
wc -l hub/kernel/*.py hub/handlers/*.py hub/server.py

for m in auth collect db fleet heartbeat identity log router ssh storage; do \
  echo "--- kernel.$m"; \
  grep -rln "kernel import.*\b$m\b\|kernel\.$m" --include=*.py hub/ \
    | grep -v "kernel/$m.py"; done
```

Every route resolves to a real function (expect `0`):

```sh
cd hub && python -c "
import ast, os
R = [v for n in ast.parse(open('kernel/router.py', encoding='utf-8').read()).body
     if isinstance(n, ast.Assign) and getattr(n.targets[0], 'id', '') == 'ROUTES'
     for v in [ast.literal_eval(n.value)]][0]
d = {f[:-3]: {x.name for x in ast.walk(ast.parse(open('handlers/' + f, encoding='utf-8').read()))
              if isinstance(x, ast.FunctionDef)}
     for f in os.listdir('handlers') if f.endswith('.py')}
print(sum(1 for r in R if r['handler'] not in d.get(r['module'], ())))"
```

**9.3 — routes (§3)**

```sh
cd hub && python -c "
import ast, collections
R = [v for n in ast.parse(open('kernel/router.py', encoding='utf-8').read()).body
     if isinstance(n, ast.Assign) and getattr(n.targets[0], 'id', '') == 'ROUTES'
     for v in [ast.literal_eval(n.value)]][0]
print('routes', len(R), 'unique paths', len({r['path'] for r in R}))
print('by gate', dict(sorted(collections.Counter(r['gate'] for r in R).items())))
print('gated', sum(1 for r in R if r['gate'] > 0))
print('by module', collections.Counter(r['module'] for r in R).most_common())"
```

Enforcement — expect one definition with the default `'0'` and no setter
anywhere outside prose:

```sh
grep -rn HUB_ENFORCE_GATES --include='*.py' --include='*.sh' --include='*.service' .
```

Sitemap drift:

```sh
cd hub && python -c "
import re, ast
s = open('handlers/status.py', encoding='utf-8').read(); i = s.find('def get_sitemap')
p = set(re.findall(r\"'(/[A-Za-z0-9/_?=.-]*)'\", s[i:i+9000]))
R = [v for n in ast.parse(open('kernel/router.py', encoding='utf-8').read()).body
     if isinstance(n, ast.Assign) and getattr(n.targets[0], 'id', '') == 'ROUTES'
     for v in [ast.literal_eval(n.value)]][0]
d = {r['path'] for r in R}
print(len(p), 'in sitemap;', len(d), 'declared; missing:', sorted(d - p))"
```

**9.4 — interface (§4)**

```sh
cd hub && python tools/check-views.py    # expect: 27 views, 28 registered, 24 in nav

grep -o "/api/[A-Za-z0-9/_-]*" hub/app.html    | sort -u | wc -l   # 39
grep -o "/api/[A-Za-z0-9/_-]*" hub/mobile.html | sort -u           # 9
grep -o "X-Hub-Token\|X-Gate-Token" hub/app.html | sort | uniq -c  # 13 + 2
grep -c "hidden:true" hub/ui/registry.js                           # 4
```

CSS rule blocks and `id=` attributes:

```sh
python -c "
import re, io
for f in ['hub/app.html', 'hub/mobile.html']:
    s = io.open(f, encoding='utf-8').read()
    css = ''.join(re.findall(r'<style[^>]*>(.*?)</style>', s, re.S))
    print(f, s.count(chr(10)) + 1, 'lines',
          len(re.findall(r'(?m)^\s*([^{}@/][^{}]*)\{', css)), 'rules',
          len(set(re.findall(r'id=\"([^\"]+)\"', s))), 'ids')"
```

**9.5 — tools and their invokers (§5)**

```sh
for t in backup.sh reclaim.sh install-preflight.py storage-preflight.py \
         check-views.py flare-mode.sh registry_gen.py maintenance.py \
         alert-check.sh alert-load.sh alert-ai-explain.sh daily-summary.sh \
         check-in.sh verify-project.sh enroll.sh update.sh alert-startup.sh; do
  echo "### $t"
  grep -rn -F "$t" --include='*.sh' --include='*.py' --include='*.service' \
    --include='*.timer' --include='*.bat' --include='*.html' . \
    | grep -v '^\./\.git/' | grep -v "/$t:"
done
```

An invoker is a `.service`, a `.timer`, a `.bat`, or a call site inside another
script. A mention in a `.md` or in `docs-site/` is **not** an invoker.

**9.6 — install surface (§6)**

```sh
grep -n "^step " bootstrap.sh                                    # 8 steps
sed -n '/^CHECKS = \[/,/^\]/p' hub/tools/install-preflight.py    # 10 assertions

cd hub && python3 tools/install-preflight.py     # Linux only
cd hub && python3 tools/storage-preflight.py     # Linux only
bash bootstrap.sh --check                        # Linux only: converge, install nothing
```

**9.7 — documents (§7)**

```sh
for f in $(grep '\.md$' /tmp/live.txt); do \
  printf "%5s  %-40s %s\n" "$(wc -l < "$f")" "$f" "$(grep -m1 '^#' "$f")"; done
```

"Falsifiable" is not derivable — it is the one judgement in this file. The test
applied: **does any script, unit or assertion read this document and fail?** For
29 of 32, the answer is no.

**9.8 — the cleanup (§8)**

```sh
git diff --stat HEAD | tail -5
git status --short | grep '^ D'
git ls-tree -r -l HEAD -- backup/ guides/ hub.log hub/maintenance.py \
  scripts/update-db.py __pycache__/ | awk '{printf "%10s  %s\n", $4, $5}'

python -c "
import json
d = json.load(open('knowledge/registry-live.json', encoding='utf-8'))
print(d['_meta']['generated'], d['summary'])"
```

**9.9 — regenerate the registry itself**

```sh
python hub/tools/registry_gen.py    # exit 0 clean, 1 if shadow or dead codes exist
```

---

## The one-line version

**113 files, 25,472 lines. 73 routes, of which 55 declare a gate and 0 enforce
one. 27 views, all registered. 7 tools a timer or the installer runs, and 9 that
nothing runs at all. 10 install assertions against an 11-step recipe and an
8-step installer. 32 documents, of which 3 can be proven wrong.**
