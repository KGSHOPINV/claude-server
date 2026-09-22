# FlareSHub — Checklists

Three sequences this system must perform, each step marked with what actually
exists today. Companion to `flareshub-blueprint.md`.

Legend: **✅ built** · **⚠️ built, off** · **❌ not built**

---

## A. Login — what happens when someone arrives

| # | Step | Status |
|---|------|--------|
| 1 | Request arrives; hub records which **door** it came through | ✅ `access_identity()` checks source against `HUB_CF_TRUST_IP` |
| 2 | **Cloudflare door:** `Cf-Access-Authenticated-User-Email` trusted *only* from the tunnel address | ⚠️ built, disabled until `HUB_CF_TRUST_IP` is set |
| 3 | Email checked against allowlist → session, role from `HUB_CF_ROLE` | ⚠️ same |
| 4 | **Local door:** username + SHA-256 password vs `users` table | ✅ |
| 5 | Session issued | ✅ but **in-memory dict — every restart logs everyone out** |
| 6 | **Write the login to `activity_log`** | ❌ `post_auth_login` never calls `log_activity` |
| 7 | **Notify** — normal for a new sign-in, high for repeated failures | ❌ ntfy fires on container events only |
| 8 | Per-route gate enforced (0 public / 1 user / 2 admin / 3 TOTP) | ⚠️ evaluated, **not applied** — 52 of 66 routes gated but `app.html` sends a token on 16 calls |
| 9 | Dangerous routes demand more than the Access door gave | ⚠️ depends on 8 |

**The gap that matters:** steps 6 and 7. The hub currently has no record that
anyone ever logged in — successful or failed — on a box reachable from the
internet. That is the first thing to fix, and it needs nothing from anyone.

**Second gap:** step 5. Sessions die on restart, which is why you keep landing
on the login screen. Persist them to SQLite with an expiry.

---

## B. Installer — what a new node gets

### `bootstrap.sh` — hub running

| # | Step | Status |
|---|------|--------|
| 1 | OS detect, packages (curl, git, python3, ufw) | ✅ |
| 2 | Docker installed, enabled, started | ✅ |
| 3 | Clone/update hub to `~/hub` | ✅ |
| 4 | `db/` created, admin user seeded (`admin`/`admin` default) | ✅ |
| 5 | systemd **user** service, `Restart=always`, journald | ✅ |
| 6 | Hub answering on `:8765` | ✅ |
| 7 | **Force the default password to be changed** | ❌ default is advertised on the login screen |
| 8 | **Register its port block** | ❌ no reservation step |

### `enroll.sh` — node joins the fleet

| # | Step | Status |
|---|------|--------|
| 1 | Read `/etc/machine-id` → stable node key | ✅ |
| 2 | Validate node label; require `--zone` | ✅ |
| 3 | **Refuse if the hub is not answering** — never publish a dead endpoint | ✅ |
| 4 | Load token from `$CF_API_TOKEN` / `~/.cf-token` / `/etc/flare/token` | ✅ |
| 5 | Verify token with Cloudflare before changing anything | ✅ |
| 6 | Resolve zone + account | ✅ |
| 7 | Create **or reuse** tunnel (idempotent) | ✅ untested |
| 8 | Ingress: this hostname → local hub, plus catch-all 404 | ✅ untested |
| 9 | DNS CNAME → `<tunnel>.cfargotunnel.com`, proxied | ✅ untested |
| 10 | Access app on the hostname — nothing public without a gate | ✅ untested |
| 11 | **Attach the allow policy** | ❌ warns; must be done by hand |
| 12 | `cloudflared` as a **host** systemd service | ✅ untested |
| 13 | `~/.flare/node.json` — facts only, no credentials | ✅ |
| 14 | Verify the public hostname answers (302 = Access login = success) | ✅ |
| 15 | **Announce itself to a sponsor node** | ❌ no enrollment handshake yet |
| 16 | **Decommission path** — remove tunnel, DNS, Access app | ❌ nothing removes a node |

**Untested** means written but never run against the live Cloudflare API — the
token available was revoked. `--dry-run` exercises steps 1–6 safely.

**Step 16 is the one people skip.** Without it, every dead server leaves a
tunnel, a DNS record and an Access app behind forever.

---

## C. Cross-connect — node A acknowledges node B

How two nodes come to know about each other. **Almost none of this is built.**

| # | Step | Status |
|---|------|--------|
| 1 | New node holds a **one-time join token** + a sponsor address — never the CF token | ❌ |
| 2 | New node POSTs `/api/enroll` to the sponsor with its `machine_id` | ❌ |
| 3 | Sponsor verifies the join token and **burns it** | ❌ |
| 4 | Sponsor (or FlareVault) provisions tunnel/DNS/Access on its behalf | ⚠️ `enroll.sh` does this directly today, which means the node holds the CF token — the model to move away from |
| 5 | Sponsor records the node **by machine-id**, with URL as a mutable attribute | ❌ peers are keyed by URL today |
| 6 | Sponsor returns tunnel token + assigned hostname | ❌ |
| 7 | Both sides poll `/api/node` and reconcile | ✅ `/api/node` exists; nothing polls it |
| 8 | Address change re-announces the **same** machine-id | ❌ |

**Why keying by machine-id matters, concretely:** both hubs already list each
other as peers —

```
fks-services  peers: ["http://100.107.234.9:8765"]
ksgcohub      peers: ["http://100.75.1.105:8765"]
```

— and neither has ever connected (`fv_last_contact: null` on both), because
those addresses are on separate tailnets. Keyed by URL, a moved peer is a dead
peer. Keyed by machine-id, it has simply changed address.

**Ownership:** steps 1–6 are **FlareVault's** by doctrine — it holds
credentials and makes access decisions. ServerHub's part is step 7: describe
itself accurately and let the authority reconcile.

---

## D. Correcting ksgcohub's Cloudflare

Today ksgcohub serves three hostnames through **one containerised tunnel**:

```
babyhelp-tunnel  (Docker, network "babyhelp", 172.19.0.3)
  ├── babyhelp.ksgco.app
  ├── hub.ksgco.app
  └── ntfy.ksgco.app
```

**Two problems.** The tunnel is a container, so if Docker wedges the tunnel dies
with it — the way in disappears exactly when it is needed to diagnose the box.
And its ingress lives only in the Cloudflare dashboard, invisible from the
server, which is why a hub outage could not be diagnosed from the machine.

**Do not migrate babyhelp.** It is live and explicitly out of scope. Tunnels
coexist fine, so:

| # | Step | Risk |
|---|------|------|
| 1 | Run `enroll.sh --node ksgco --zone <zone>` → creates a **second**, host-level tunnel serving only `hub-ksgco.<zone>` | none — additive |
| 2 | Verify `hub-ksgco.<zone>` reaches the hub | none |
| 3 | Attach the Access policy | none |
| 4 | Move `hub.ksgco.app` off `babyhelp-tunnel` **only after** the new path is proven | reversible |
| 5 | Leave `babyhelp.ksgco.app` and `ntfy.ksgco.app` on `babyhelp-tunnel` | untouched |

End state: the hub reached by a host-level tunnel that survives Docker dying;
babyhelp untouched on its own. **ntfy deliberately stays off Access** — it is an
app endpoint and Access would silently kill push.

---

## E. What the system will be able to state

Once A–D land, these become answerable in one call rather than by archaeology:

- Which nodes exist, by stable identity, and where each is reachable
- What runs on each node, grouped by owning project — and what nothing claims
- Which projects are publicly exposed and behind which policy
- Who logged in, when, through which door
- What has drifted from what was declared

All five are unanswerable today. The last one is the point of the whole
exercise: **drift you can see.**
