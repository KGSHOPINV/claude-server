# Deployment Landscape

The five questions to answer for **any** service you deploy, on any node, behind any
domain. Written after a week where every single failure turned out to be
documentation disagreeing with the machine — not one was a code bug.

---

## 1. What are the three parts, and which are portable?

Every deployable splits three ways:

| Part | What | Comes from | Rule |
|------|------|-----------|------|
| **Code** | source, Dockerfiles, compose | git | disposable — rebuild anywhere |
| **Config** | `.env`, ports, secrets, domain | per-node | never committed |
| **State** | databases, uploads, vaults | backup | the only irreplaceable part |

If a project can't be stood up on a fresh box in ten minutes, one of these isn't
separated. Usually it's code: when the source lives only on the machine that runs
it, **that server *is* the source of truth** — no rollback, no drift detection.

> Real example: `/srv/docker/fksinv` on ksgcohub is not a git repo. Overwrite a
> file and the previous version is gone. Meanwhile `~/hub` is a repo, which is why
> rolling it back is `git checkout <commit> && systemctl --user restart hub`.

---

## 2. Which paths reach it, and what does each carry?

| Path | Reaches | Carries |
|------|---------|---------|
| LAN `192.168.x.x` | devices on that one network | anything |
| Tailscale `100.x` | your enrolled devices, anywhere | anything, **SSH included** |
| Public hostname (Cloudflare) | the whole internet | **HTTP/HTTPS only** |

LAN addresses are private and not routable between networks — `192.168.50.100`
means nothing from a `192.168.1.x` machine. Tailscale is an *overlay*: virtual
addresses tunnelled over whatever internet each device has, which is why they work
from anywhere.

**Cloudflare does not carry SSH.** A host answering HTTP while SSH hangs is a
proxied hostname, not a firewall or a reboot. Use the Tailscale address.

---

## 3. What proves identity on each path?

Private paths already proved something by *how you got there*. The public path
proves nothing, so the door has to. See `remote-access.md` for the full model.

- **Browsers** → Cloudflare Access + SSO
- **Apps and machines** → their own token ACL behind the same tunnel

Never put Access in front of an app endpoint. It's a browser redirect flow; an app
with no browser just dies, silently.

---

## 4. Is there a build step between source and what's served?

This changes what "deploy" means, and getting it wrong is invisible:

| Service | Source → served | Deploy |
|---------|----------------|--------|
| hub | `app.html` read off disk | `git pull` + restart |
| fks-ui | compiled into the image | `git pull` + **`docker compose build`** + up |

With a build step, copying files changes nothing on the live site. `scp` exits 0,
the old bundle keeps serving, and it looks like your code is broken. Put the build
inside the deploy script so it cannot be skipped.

---

## 5. Does anything compare the record to the machine?

The one that actually bites. Drift found in a single week:

- `update.sh` copied the app to a directory where its own imports failed — broken
  for weeks, silently, because nobody ran it
- `hub.service` pointed at a file that no longer existed
- `AGENTS.md` described a monolith that had already been split
- A memory file declared a live server "DOWN — do not SSH to it"
- `docker-compose.yml` falls back to a `.us` domain when the real one is `.com`

None were code bugs. All were records that stopped matching reality. Prefer things
**derived** from the machine (`/api/status`, `/api/ports`, `registry.json`) over
things maintained alongside it.

---

## Standing a service up on a new node

```bash
# 1. prerequisites
sudo apt install -y docker.io docker-compose-plugin
sudo usermod -aG docker $USER          # log out/in

# 2. code — from git, never copied off the running server
sudo mkdir -p /srv/docker && sudo chown $USER:$USER /srv/docker
git clone <repo> /srv/docker/<service>
cd /srv/docker/<service>

# 3. config — written per node, never from git
#    regenerate secrets; do not reuse keys across nodes
cp .env.example .env && $EDITOR .env

# 4. state — fresh, or restored from backup
mkdir -p data

# 5. build + run
docker compose build && docker compose up -d

# 6. verify each port answers
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:<port>
```

Then expose it: add an ingress hostname on the existing tunnel (one tunnel serves
many hostnames — you don't need one per service) and an Access policy if it
shouldn't be world-readable.

### Things that bite

- **Ports must be free and open in `ufw`.** Every new service = a port, a firewall
  rule, and an ingress entry. Three places to drift — see `PORTS.md` and the port
  lane registry.
- **Regenerate secrets per node.** A shared `API_SECRET_KEY` means a token minted
  on one node is valid on the other.
- **Tunnel ingress rules live in the Cloudflare dashboard**, with no trace on the
  server. Nothing local can tell you what a hostname points at. Write it down.
- **Use `${VAR:?msg}`, not `${VAR:-default}`** for anything environment-critical.
  A missing value should stop the deploy, not quietly produce a half-working stack.
- **Back up state before schema work.** It's the only part you can't rebuild.

---

## See also

- `remote-access.md` — the two-door auth model, ntfy token setup
- `../../knowledge/decisions.sql` — why these rules exist
- `PORTS.md` — port lane registry
