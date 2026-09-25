# ServerHub — what it actually does for you

Every capability, grouped by what you'd want to do rather than by how it's built.
Generated from the real route table (73 routes, 12 modules) and the real view
registry (28 views, 24 in the nav), not from memory.

Status marks, because the honest version is more useful than the flattering one:
**✅ works · ⚠️ works but off or unwired · ❌ built, broken or unreachable**

---

## See what's on the machine

| You want to know | It gives you |
|---|---|
| Is anything wrong right now | `/api/status` — uptime, RAM, load, containers, every disk ✅ |
| What's running | `/api/containers`, `/api/services` ✅ |
| What's using my ports | `/api/ports` — live from `ss`, with lanes and a name per port ✅ |
| Where my disk went | `/api/storage` — mounts, volumes, Docker usage, log size ✅ |
| Which images and volumes exist | `/api/docker/images`, `/api/docker/volumes` ✅ |
| Live resource use per container | `/api/docker/stats` ✅ |
| Why is Docker unhappy | `/api/docker/diagnostics` ✅ |
| What is this machine, completely | `/api/node` — machine-id, reachability, projects by label, an `attention` block ✅ |
| Everything in one snapshot | `/api/receipt`, `/api/context`, `/cutsheet` ⚠️ four overlapping shapes, see note |

## Change things

| You want to | It gives you |
|---|---|
| Start/stop/restart a container | `/api/docker/action/` ✅ |
| Free up disk | `/api/docker/prune` ✅ |
| Run a shell command | `/api/run` ✅ gated behind TOTP |
| Install a service | `/api/service/install` ✅ |
| Update the hub itself | `/api/update` ✅ |
| Open/close a tunnel | `/api/tunnel/start`, `/api/tunnel/stop` ✅ |

## Keep track of things

| You want to | It gives you |
|---|---|
| See what happened, and when | `/api/activity` — an append-only log ✅ |
| Record an incident | `/api/incidents` ✅ |
| Track a problem | `/api/issues` ✅ |
| Write a note against the server | `/api/journal` ✅ |
| Be told when something happens | ntfy, with real phone apps ⚠️ fires on container events only; logins are never recorded |

## Secrets and access

| You want to | It gives you |
|---|---|
| Store a credential | `/api/vault` ✅ pointers, per doctrine |
| Log in | `/api/auth/login` — local username + password ✅ |
| Log in from the internet | Cloudflare Access + Google ⚠️ built, off until `HUB_CF_TRUST_IP` is set |
| Two-factor | `/api/totp/*` — setup, confirm, verify, disable ✅ |
| Manage users | `/api/users` ✅ |
| Know which door someone came through | `/api/access`, `/api/identity` ✅ |
| Stay logged in across a restart | ❌ sessions are an in-memory dict — every restart logs everyone out |
| Enforce per-route permissions | ⚠️ 52 of 73 routes carry a gate; enforcement is OFF. Arming it locks the UI out |

## Onboard a new project

| You want to | It gives you |
|---|---|
| Know where a project may bind, write and name things | `/api/admit?project=X` ✅ |
| — its port band | live, from the free space on this machine ✅ |
| — where its data goes | derived from this machine's disks ✅ *(pending deploy)* |
| — the labels it must carry | `com.ksg.project`, `owner`, `role`, `data` ✅ |
| — what is forbidden | reserved ports, other projects' networks and databases ✅ |
| — proof it complied | a runnable acceptance test ✅ |

**This is the one a novice needs most.** One request, no tribal knowledge.

## Run more than one server

| You want to | It gives you |
|---|---|
| A node reports itself to central | `/api/heartbeat`, every 30s, with a cloudflare → tailscale → lan fallback ✅ |
| A node joins the fleet | `/api/mesh/register` ✅ |
| See the whole fleet | `/api/mesh/fleet` — status derived from `last_seen`, never by a sweeper ✅ |
| Flip a box between node and central | `tools/flare-mode.sh` ✅ |
| Give a node a public hostname | `enroll.sh` — tunnel, DNS, Access app ⚠️ never executed against the live API |
| Peer with another hub | `/api/federation`, `/api/peer/register` ⚠️ the two servers are on split tailnets |

## Ask questions in English

| You want to | It gives you |
|---|---|
| Ask about the server | `/api/ai/chat` ✅ |
| Point it at a model | `/api/ai/config` ✅ |
| Read the guides | `/api/docs`, `/api/docs/content` ✅ |

## Command-line tools

| Tool | What it does | Runs |
|---|---|---|
| `tools/install-preflight.py` | Is this node finished? 8 assertions, `--strict` exits 1 | on demand ✅ |
| `tools/storage-preflight.py` | Disks, data root, backup target, findings with fixes | on demand ✅ |
| `tools/check-views.py` | Registry and renderer must agree, both directions | on demand ✅ |
| `tools/backup.sh` | Backs up volumes, configs and the hub DB to a device that does not hold the data | daily 03:00 ✅ |
| `tools/reclaim.sh` | Keeps a week of build cache, drops the rest | Sundays 04:00 ✅ |
| `tools/flare-mode.sh` | node ↔ central, and where home is | on demand ✅ |
| `bootstrap.sh` | Bare machine → running hub | on demand ⚠️ 5 of 11 documented steps |
| `enroll.sh` | Node → public hostname behind Access | ⚠️ needs a scoped token |

---

## The interface

24 views in the nav, any of them openable in a split pane:

**Watching** — dashboard · logs · network · ports · infra map · storage · docker · activity
**Doing** — terminal · files · runbooks · settings · survey
**Knowing** — docs · guide · receipt · issues · journal · vault
**Fleet** — federation · remote access
**Asking** — AI chat · hub AI *(two separate implementations, both live)*
**Embedding** — any service in an iframe pane, from the nav

Plus: a command palette, a context panel, splittable panes with saved layouts, and
a PWA manifest so it installs to a phone home screen.

---

## What it does not do, stated plainly

- **Deploy from git.** Nothing here turns a repo into a running container. That gap is real, and Coolify is the candidate to fill it.
- **Survive its own restart, session-wise.** You get logged out.
- **Enforce its own permissions.** The gates are declared, not applied.
- **Record logins.** Successful or failed. On a box reachable from the internet.
- **Aggregate several servers into one address.** FlareSHub is a design, not code.
- **Hold credentials.** By choice. That's FlareVault's job.

---

## The four-shapes note

`/api/status`, `/api/storage`, `/api/receipt`, `/api/context`, `/api/node` and
`/api/admit` all answer *"what is true about this machine"* in six different shapes
across two modules, with no shared source. They work. They also drift, for exactly
the reason the constitution warns about. The intended fix is one receipt requested
at a depth:

```
/api/receipt                  the machine
/api/receipt?for=project      + your band, your data paths, the contract
/api/receipt?for=fleet        + identity, mode, peers
/api/receipt?for=authority    + what FlareVault needs to provision
```
