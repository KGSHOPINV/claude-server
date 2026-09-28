# Handoff — flarevault

Paste everything between the rules into flarevault's own session. Nothing else.

**Do not add what ServerHub already observed.** The claim and the machine are
recorded separately and neither is trusted over the other — the distance
between them is the product. Telling the project what we see first destroys it.

Reply comes back to `hub/intake/claims/flarevault.yaml`, verbatim, never edited.

---

Hi — I'm ServerHub, the ops layer on the server this project runs on.

I'm building a registry of every project across two servers so the machine can
answer "what is here, who owns it, what does it need" without anyone
remembering. I need your project's receipt, and I need to tell you two things
that are changing underneath you.

**I am not asking you to change anything today.** This is a read, plus a notice.

## Part 1 — what you are

Reply with the block below, filled in from what is ACTUALLY running — not from
your README, not from intent. Read the compose file, run `docker ps`, check the
disk. Where you cannot verify something, write `unknown`.

`unknown` is a real answer. A wrong claim is worse than a gap, because a gap is
visible and a wrong claim is not.

```yaml
project: <short-lowercase-name>
owner: <who to ask when it breaks>
status: dev | staging | production        # sets how loudly drift reports
purpose: <one line>

host: <ksgcohub | fks-services | other>
compose_file: <absolute path, or "none">
repo: <git remote, or "none — lives only on the server">

containers:                               # from `docker ps`, not the compose
  - name: <container name>
    image: <image:tag>
    published_ports: [<host ports>]
    restart_policy: <unless-stopped | always | no>

data:                                     # everything that would hurt to lose
  - path: <absolute path OR docker volume name>
    kind: <bind | volume>
    class: <db | media | public | private | cache | releases>
    size: <approx>
    backed_up: <yes | no | unknown>

depends_on:
  external: [<other services this calls>]
  shared: [<anything it uses that it does NOT own — should be empty>]

exposure:
  public_hostname: <or "none">
  auth: <how a user is authenticated, or "none">
  reachable_from: [<lan | tailscale | internet>]

secrets:
  location: <path to .env, or "vault", or "none">
  in_git: <yes | no>                      # yes is a finding, not a failure

known_deviations:                         # what you ALREADY know is non-standard
  - <e.g. "data in a named volume">
  - <e.g. "port outside any assigned band">
  - <e.g. "mounts the docker socket">

health_check: <the one command that proves it works>
```

## Part 2 — what is changing on this server

Two contract changes. Neither moves you. Both need a decision from you, and
`accept` is a real answer that ends the matter.

**PORTS — the project band moves to 12000–18999, 100 ports per project.**
The old band was 7100–7899 at 20 ports each. The two ranges do not overlap, so
a port inside the old one is outside the new one by definition.
*This is a migration, not a cutover.* Nothing is being taken off you. Do not
ADD to a port outside the new band; take your next one from inside it.

**STORAGE — a project's data now has a declared shape, and bind mounts, not
named volumes.** Your data root is handed to you by `GET /api/admit` and is
derived from that machine's actual disks, so it differs per server. Under it:

```
db/         structured state a database writes       backed up nightly
media/      your users' files — docs, images, av     backed up nightly
public/     the ONLY path served without a session   backed up nightly
private/    your own files — exports, reports        backed up nightly
cache/      regenerable                              NEVER backed up
releases/   build artifacts                          never backed up
```

The class is readable from the path so nobody has to remember it. A named
volume lives under `/var/lib/docker/volumes`, is invisible to `du` on the data
root, needs root to read, and `docker compose down -v` deletes it without
asking twice. `backup.sh` does still copy named volumes, so an accepted one is
not unprotected — it is just harder to see and easier to lose.

**The test that matters:** remove every container you own, then list your `db/`
directory. If it is empty or gone, you did not have isolation — you had a copy
that happened to still be running.

## Part 3 — what you actually do

1. Send the block in Part 1. That is all that is required of you today.
2. I read your machine independently and write down what is true.
3. Every difference between the two gets exactly ONE disposition:

   | | means | who decides |
   |---|---|---|
   | `fix` | you will change to match | **you** |
   | `accept` | the deviation is deliberate and stays | **you** |
   | `defer` | real, not now, with a reason | **you** |
   | `hub-wrong` | the contract is wrong, not you | **me**, and I change the contract |

**You are done when every difference has a disposition — not when every
difference is fixed.** A project with four accepted deviations is fully
reconciled. An undeclared deviation is the only failure state.

And `hub-wrong` is real. A project pushing back is a finding about ServerHub,
not insubordination. The contract has been wrong before — it handed out ports
inside a reserved lane for months before anyone noticed.

---
