# Session Log — 2026-09-10 → 2026-09-16

What happened, in order, so a new session can pick up without re-deriving it.
Every commit is on `master` unless noted.

---

## The one-line summary

Phase 2 finished and deployed to **both** servers, the deploy path that had been
silently broken since Phase 1 got repaired, Phase 3 started, and a public
credential leak was found. **Every failure encountered was documentation
disagreeing with the machine — not one was a code bug.**

---

## Timeline

### Sep 10 — Phase 2 wiring

- **Why the project vanished from the sidebar:** the session was auto-archived
  when PR #9 merged ("Auto-archive on PR close"). Nothing was deleted.
- `9062b8b` — wired `kernel/router.py` dispatch to `handlers/`. Auditing all 64
  annotated branches against the route table found four things that would have
  failed at runtime:
  - `/desktop` routed in `server.py`, missing from the table
  - `/mobile` pointing at `identity.serve_mobile`, which does not exist
  - an ops route name not matching its function
  - **16 handler signatures wrong** — `users`, `tunnel`, `ops` were extracted as
    `fn(handler, body)` while the other seven used `fn(handler, path, params, body)`
- `f441ad2` — `kernel/collect.py`. The handler split had been cosmetic: handlers
  imported `server.py` back 22 times (`status.py` 19, `identity.py` 2, `ai.py` 1),
  so the graph was `server → router → handlers → server`, a cycle.
  **server.py: 2,890 → 122 lines.**
- `48e12b1` — repaired the deploy path (see below).
- `c6525e5` — `AGENTS.md` + `refactor-plan.md` still described the monolith.
- PR #10 merged as `ab02c2f`; deployed to fks-services and verified.

### Sep 11 — security, ksgcohub, the tailnet split

- `ecfd5e3` — **`CLAUDE.md` was tracked despite being in `.gitignore`.** Ignore
  rules do not apply to already-tracked files, so real IPs and the SSH user were
  in a **public** repo. Untracked; history still contains them.
- `065aa1b` — two-door auth + `HUB_LOG_REQUESTS`.
- `71a9cd7` — two-door model and the ntfy trap documented in `remote-access.md`.
- ksgcohub found **24 commits behind**, pulled forward to `ab02c2f`, verified
  41/41 routes.
- **Tailnet split discovered:** fks-services sits alone on `kyle@`
  (`tail912c87.ts.net`); this PC, ksgcohub, phone and laptop are on
  `ksg.co.hub@gmail.com` (`tail4142b4.ts.net`). The two servers cannot reach each
  other. Both nodes are healthy — they are on different networks.

### Sep 13–14 — Phase 3 begins

- `74e1fef` — two blockers cleared first: the hub could serve **no JavaScript at
  all** (only `app.html`, `manifest.json`, `sw.js`), and `app.html`'s script is one
  5,248-line global scope where `type="module"` would break everything. Added a
  `/ui/` route (traversal + extension allowlisted; `../server.py`,
  `../../../etc/passwd` and encoded traversal all verified blocked) and
  `registry.js` as a classic script.
- `2d38ed1` — `issues` and `browser` migrated to `ui/views/`, plus a loader.
  Adding a view is now **one file + one registry entry**; `app.html` is untouched.
  Verified in a real browser on a preview instance: registry live, 19 views,
  2 migrated, no console errors.
- `33258c7` — `deployment.md` guide + 6 architecture decisions.

### Sep 15–16 — the fksinv detour

Investigated for a parallel session that believed the server was offline.

- `fks.ksgdev.com` resolves to **Cloudflare**, which does not carry SSH. SSH to it
  hangs forever and looks exactly like a dead host. The app is on **ksgcohub** at
  `/srv/docker/fksinv` (not `/opt/fksinv`, not fks-services), user `ksgco`.
- `fks-ui` has **no bind mounts** — the React app compiles into the image, so
  `scp` alone changes nothing until `docker compose build`.
- The dashboard's 401s were **a logged-out browser**, not a break:
  `auth_middleware.py` requires `X-Session-Id`, the UI reads it from
  `sessionStorage` (per-tab, empty in a fresh tab). Only 2 of N endpoints are
  gated, so a logged-out visitor gets a half-working page instead of a redirect.

---

## The recurring pattern

Five separate failures, one cause — **the record stopped matching the machine:**

| Record said | Reality |
|---|---|
| `update.sh` copies the app and restarts it | copied it where its imports failed; broken for weeks |
| `hub.service` ExecStart | pointed at a deleted file |
| `AGENTS.md`: "this is a monolith" | already split into kernel + handlers |
| memory: "fks-services is DOWN, do not SSH to it" | up the whole time, 34 containers |
| `docker-compose.yml`: `DOMAIN=…ksgdev.us` | real domain is `.com` |

Corollary seen three times: a **transport** problem looking like an outage — SSH
into Cloudflare ("server is off"), an Access login screen ("Cloudflare is down"),
and a dropped SSH session ("task failed") while the process it started kept
running.

**Rule:** prefer things *derived* from the machine (`/api/status`, `/api/ports`,
`registry.json`) over things maintained alongside it.

---

## State at close

| | fks-services | ksgcohub |
|---|---|---|
| Commit | `ab02c2f` | `ab02c2f` |
| `server.py` | 122 lines, 11 handlers, 7 kernel modules | same |
| Routes | 41/41 | 41/41 |
| Service | systemd **user** service, active | same |
| Tailnet | `kyle@` (alone) | `ksg.co.hub@` |
| Public | none | `hub.ksgco.app`, `ntfy.ksgco.app`, `fks.ksgdev.com` |

Unmerged: PR #11 (7 commits — the security fix, two-door auth, docs, Phase 3).

---

## Open items

**Needs the user (sudo or a browser):**
1. **Rotate `1234qwerR`** — public in git history (`a34a8f1`). Check reuse on
   Portainer, NPM, n8n, Uptime Kuma.
2. Merge PR #11.
3. `sudo tailscale up --force-reauth` on fks-services, as `ksg.co.hub@gmail.com` —
   fixes the mesh. Its address changes; ksgcohub's peer entry needs the new one.
4. Remove the stale system unit: `sudo systemctl disable --now hub.service &&
   sudo rm /etc/systemd/system/hub.service`.

**Ready to build:**
- Phase 3 — 17 views left. The next ones are not static stubs; `dashboard`,
  `network`, `terminal`, `logs` call helpers still in `app.html`.
- Enable two-door auth — needs `HUB_CF_TRUST_IP` on ksgcohub's unit.
- Login events → `activity_log` → ntfy. **The hub records no logins at all.**
- UUID in `/api/identity`; key peers by machine-id, not URL.
- Fix `_users_list()` — returns `[]` on any exception, so `/api/users` lies.
- Persist sessions — in-memory dict, so every restart logs everyone out.

**Deliberately not done:**
- Gate enforcement stays **off**. 52 of 66 routes gated in the table; `app.html`
  sends a token on 16 calls. Arming it locks the UI out.
- Vault view hardcodes `192.168.1.229:7779` — wrong on ksgcohub.
- `_browser_old` is dead code; `survey` has a render case but no registry entry.
