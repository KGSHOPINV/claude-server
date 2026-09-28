# Port Reference & Lane Definitions

> Central port registry for the full server stack.
> Ports are assigned to lanes — category-scoped ranges that prevent conflicts.
> When adding a new service, pick the next free port in its lane and document it here.

---

## Lanes

| Lane | Range | Category |
|------|-------|----------|
| **System** | 80, 443 | Public HTTP/HTTPS (handled by Nginx Proxy Manager) |
| **Hub** | 8765 | Server Hub control panel (reserved — never assign to a container) |
| **Infrastructure** | 3000–3099 | Dashboards, admin UIs, core tooling |
| **Monitoring** | 19000–19999 | Metrics, graphs, health checks |
| **Automation** | 5600–5699 | Workflow engines, job schedulers |
| **Database** | 5400–5499, 6300–6399 | SQL, NoSQL, key-value stores |
| **API/Services** | 8000–8099 | Admin UIs, API tools |
| **Notifications** | 8080–8089 | Push alerts, webhooks, notification servers |
| **Storage** | 9000–9099 | Object storage, file services |
| **Admin/Management** | 9400–9499 | Container managers, Linux admin panels |
| **AI** | 11000–11999 | Model engines, chat UIs |
| **Proxy/Tunnel** | 8200–8299 | Reverse proxy management |

---

## Assignments are not in this file

A lane is a **rule** and belongs in a document. An assignment is a **fact about
a machine** and does not. A table of assignments stood here; it was one of
several hand-typed service inventories in this repo that disagreed with each
other and with the machines.

```bash
curl -s <hub>/api/ports              what is bound right now, with lane and owner per port
curl -s "<hub>/api/admit?project=X"  the band a project may bind inside, derived live
python3 hub/tools/situation.py       plus what is exposed beyond the box
ss -tlnp                             the raw socket view, on the box
```

**`/api/ports` is the authority, not the container list.** A service installed
outside Docker — a snap, an apt package, anything bound by the host — never
appears in `docker ps` or in the receipt's container list. Only the socket view
sees it. A port can be occupied by something no container view will ever show.

**Lanes are a declaration, not a policy.** Nothing enforces them. That is how
admission handed out ports inside another stack's reserved lane for months:
two places answered *"what may a project bind"* and disagreed, and neither was
checked against the other. If you want a lane enforced, put the check in code —
a rule written here cannot fail.

**Project bands are allocated fleet-wide**, not per box, so a project can move
machines without renumbering. A band is the boundary; how a project arranges
ports inside its own band is the project's business, and outgrowing one is a
ticket, not a violation.

## Rules

1. **Pick the next free port in the lane** — don't use random ports
2. **Ask the machine, don't consult a list** — `curl -s <hub>/api/ports` before
   you claim anything. A document cannot tell you a port was taken yesterday
3. **NPM routes public traffic** — LAN services stay on their lane port; NPM handles public domain routing
4. **No two services on the same port** — run `ss -tlnp` or `port-scan` to check for conflicts
5. **8765 is reserved for Hub** — never assign to a container

---

## Adding a New Service

1. Identify the lane (what category is this service?)
2. Ask for the next free port in that lane — `curl -s <hub>/api/ports`, or for a
   project, `curl -s "<hub>/api/admit?project=X"`, which derives a whole band
3. Update the compose file to use it, and **carry the labels** — `com.ksg.project`,
   `owner`, `role`, `data`. Ownership is declared by the thing itself, because a
   label travels with the container and a registry beside it drifts
4. Verify no conflicts: `ss -tlnp | grep <port>`
5. Prove isolation: `docker ps --filter label=com.ksg.project=X` must return that
   project's containers and nothing else. No reviewer required

**Do not add it to this file.** That step is what made the old table wrong.

---

## Port Scan (server CLI)

```bash
port-scan          # shows all open ports on the server
port-scan 3000     # check if a specific port is free
ss -tlnp           # raw socket view
```
