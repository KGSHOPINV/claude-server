# FlareSHub — Blueprint

**The gain:** one address, one login, any server, on desktop or phone — and it
can tell you when something happens.

Status as of 2026-09-21. Verified facts, not aspirations. Anything not built is
marked as such.

---

## 1. The three layers

Each owns something the others cannot do well. Put the seam anywhere else and
you get drift.

| Layer | Owns | Why it must be here |
|-------|------|---------------------|
| **Node** (ServerHub) | Its own machine-id, containers, ports, activity | Only the machine can read its own Docker daemon and `/etc/machine-id` |
| **Entry** (FlareSHub) | One address, one session, the aggregated view | The browser needs one origin; N origins means N logins and CORS |
| **Authority** (FlareVault) | Credentials, DNS, tunnels, port bands, the gate | Only thing outside the blast radius. Survives losing every server |

ServerHub doctrine, verbatim: *"Credentials — never stored here. Pointers only."*
and *"FlareVault configures DNS and tunnels. I just run the containers those
tunnels point to."* The node never holds a key and never creates a hostname.

---

## 2. How a node joins

```
  bootstrap.sh              hub running on :8765, admin seeded
       │
       ▼
  enroll.sh --node X --zone Z
       │  reads /etc/machine-id            → the stable key
       │  verifies CF token                → refuses if invalid
       │  refuses if hub not answering     → never publish a dead endpoint
       ├─ create/reuse tunnel  (idempotent)
       ├─ DNS  hub-X.Z → <tunnel>.cfargotunnel.com
       ├─ Access app on that hostname      → nothing public without a gate
       ├─ cloudflared as a HOST service    → survives Docker dying
       └─ ~/.flare/node.json               → facts only, no credentials
       │
       ▼
  node is addressable at https://hub-X.Z and describes itself at /api/node
```

The API token is used during the run and discarded. The only persisted
credential is cloudflared's, scoped to that one tunnel.

**Changing domain = changing `--zone`.** Adding a server = the same command with
a different `--node`. That is the whole turnkey property, and it holds only
because no hostname is hardcoded anywhere.

---

## 3. How a request flows

```
phone / desktop
   │  https://flareshub.<zone>          ONE address. PWA installs from here.
   ▼
Cloudflare Access ── Google ──► one login covers every node in the same Access org
   │
   ▼
FlareSHub  ─── service tokens ───┬──► https://hub-fks.<zone>   → fks-services :8765
   aggregates /api/node          └──► https://hub-ksgco.<zone> → ksgcohub    :8765
   from every node
```

**Node hostnames are never typed by a human.** Their Access policies should be
service-token only, so a person browsing to one is refused outright and only
FlareSHub can reach them. Add a tenth server and the human-facing surface does
not grow.

**Why server-side aggregation and not browser-side:** one origin means no CORS,
one Access session, one service worker, one push subscription. The extra hop
buys all of that.

---

## 4. Two doors — the auth model

| Path | Already proved | Login it asks for |
|------|----------------|-------------------|
| LAN / Tailscale | you are on an enrolled device in a private network | hub username + password |
| Cloudflare | nothing — it is the open internet | Access → Google |

The local login **always works, is never disabled, and depends on nothing
external.** When Cloudflare, Google or your domain is having a bad day, you get
on Tailscale or walk to the machine. That is why you do not collapse to
Google-only.

Access grants a user-level session. Gate 2/3 routes — vault, shell, TOTP —
still demand the stronger proof regardless of which door you came through.
Google gets you in the building, not into the safe.

Built, off by default: `HUB_CF_TRUST_IP` arms it. The Access header is trusted
**only** from the tunnel's address, because anything on the tailnet can forge a
header. The trust is the path, not the header.

---

## 5. Notifications

**What exists:** ntfy, working, with real mobile apps. It fires on container
start/die only.

**What does not:** the hub records **no logins at all** — successful or failed.
`post_auth_login` never calls `log_activity`. So the interesting events are not
being emitted, which matters more than the transport.

**The PWA today is a shell.** `manifest.json` is real and the install prompt
works. `sw.js` is one line:

```js
self.addEventListener('fetch', () => {});
```

No caching, no offline, **no push handler.**

**Order that respects reality:**

1. Emit the events first — login, failed login, deploy, drift, incident → `activity_log`
2. Route them to ntfy, which already works and already has apps on your phone
3. Only then Web Push in the PWA: real service worker, VAPID keys, subscription
   storage. On iOS the PWA must be installed to the home screen (16.4+), no
   exceptions.

Web Push makes alerts arrive *as FlareSHub* rather than as ntfy. That is a
polish step, not the win. The win is step 1.

---

## 6. Where it stands

**Built and deployed**

- Hub refactored: `server.py` 2,890 → 122 lines, 11 handlers, 7 kernel modules, 68 routes
- Both nodes ran identical code and verified 41/41 routes
- `/api/node` — live on ksgcohub. machine-id, reachability, projects grouped by
  label, and an `attention` block listing what is wrong with the node
- `machine_id` on `/api/identity` — peers can key on identity instead of address
- Two-door auth — written, trust boundary tested, off by default
- Phase 3 UI — `/ui/` static route, `registry.js`, 2 of 19 views migrated

**Built, never executed**

- `enroll.sh` — untested against the live Cloudflare API, because the token in
  fksinv's `.env` is revoked. `--dry-run` verifies token, zone and account and
  stops before mutating.

**Not built**

- FlareSHub itself — the aggregating entry point
- Service tokens, and service-token-only policies on node hostnames
- Login events → activity log → ntfy
- Real service worker; Web Push
- Phase 3 — 17 views remaining
- Session persistence — sessions are an in-memory dict, so every restart logs
  everyone out

**Known wrong**

- `_users_list()` returns `[]` on any exception, so `/api/users` lies
- Gate enforcement off: 52 of 66 routes gated in the table, `app.html` sends a
  token on 16 calls. Arming it locks the UI out
- 12 projects on ksgcohub carry no `com.ksg.project` label
- fks-services has an unlabelled Meilisearch on port 7700 that nobody can identify
- The sudo password is in public git history and needs rotating

---

## 7. Build order

| # | Step | Owner | Blocked by |
|---|------|-------|-----------|
| 1 | Valid scoped CF token at `~/.cf-token` | you | — |
| 2 | `enroll.sh --dry-run` on ksgcohub, then real | me | 1 |
| 3 | Same on fks-services | me | 1, box back online |
| 4 | Service tokens; node policies to token-only | you + me | 2, 3 |
| 5 | FlareSHub: poll every `/api/node`, one page | me | 4 |
| 6 | Login/deploy/drift events → activity log → ntfy | me | — |
| 7 | Real service worker, offline shell | me | 5 |
| 8 | Web Push | me | 7 |
| 9 | Phase 3 — remaining 17 views | me | — |

6 and 9 need nothing and can run in parallel with everything else.

---

## 8. The standing rule

Every failure found in the week of 2026-09-10 was a **record disagreeing with
the machine**, not a code bug: an installer that copied the app where its
imports failed, a service unit pointing at a deleted file, docs describing an
already-split monolith, a memory declaring a live server dead, a compose
fallback to a domain that does not exist.

So: **derive, do not maintain.** `/api/node` reads the machine every call and
holds no opinion about what should be there. Intent lives with the authority;
the node reports only what is. When those two disagree, that is drift — and
drift you can see is the entire point.
