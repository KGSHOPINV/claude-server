# Project intake — paste this into any project's session

One message, every project, same shape back. The reply is what ServerHub admits.

Do not edit it per project. If a project cannot answer a field, `unknown` is a
real answer and more useful than a guess — a wrong claim is worse than a gap,
because a gap is visible.

---

## The message

```
Hi — I'm ServerHub, the ops layer on the server this project runs on.

I'm building a registry of every project across two servers so the machine can
answer "what is here, who owns it, what does it need" without anyone
remembering. I need your project's receipt.

Please reply with ONLY the fenced block below, filled in from what is ACTUALLY
running — not from your README, not from intent. Read the compose file, run
`docker ps`, check the disk. Where you cannot verify something, write `unknown`.

`unknown` is a real answer. A wrong claim is worse than a gap, because a gap is
visible and a wrong claim is not.

```yaml
project: <short-lowercase-name>          # the name you want to be known by
owner: <who to ask when it breaks>
status: dev | staging | production       # be honest; it sets how loudly drift reports
purpose: <one line, what it is for>

host: <ksgcohub | fks-services | other>
compose_file: <absolute path, or "none">
repo: <git remote, or "none — lives only on the server">

containers:                              # from `docker ps`, not from the compose
  - name: <container name>
    image: <image:tag>
    published_ports: [<host ports, e.g. 10100>]
    restart_policy: <unless-stopped | always | no>

data:                                    # everything that would hurt to lose
  - path: <absolute path OR docker volume name>
    kind: <bind | volume>
    class: <db | media | cache>          # cache = regenerable, never backed up
    size: <approx>
    backed_up: <yes | no | unknown>

depends_on:
  external: [<other services this calls, e.g. "fks-api", "cloudflare tunnel">]
  shared: [<anything it uses that it does NOT own — should be empty>]

exposure:
  public_hostname: <e.g. fks.ksgdev.com, or "none">
  auth: <how a user is authenticated, or "none">
  reachable_from: [<lan | tailscale | internet>]

secrets:
  location: <path to .env or "vault" or "none">
  in_git: <yes | no>                     # yes is a finding, not a failure

known_deviations:                         # what you already know is non-standard
  - <e.g. "data in a named volume on the OS disk">
  - <e.g. "port outside any assigned band">

health_check: <the one command that proves it works>
```

Two notes:

1. I am NOT asking you to change anything. This is a read. If your setup does
   not match the server's conventions, say so in `known_deviations` — a declared
   deviation is fine and is the point. Undeclared is the problem.

2. This claim can go stale and that is expected. The machine stays the source of
   truth; your claim is what you INTENDED. The difference between them is the
   useful signal, so nobody has to keep it tidy.
```

---

## What happens to the reply

| | |
|---|---|
| `project` + `owner` + `status` | the registry row; `status` sets drift weight |
| `containers` | diffed against `docker ps` — unlabelled ones surface |
| `data` | drives what gets backed up, and `class: cache` gets skipped |
| `depends_on.shared` | should be empty; anything here breaks isolation |
| `secrets.in_git: yes` | a finding, ranked |
| `known_deviations` | accepted, not enforced — declared beats discovered |

## Why one template instead of four bespoke messages

Four bespoke asks return four shapes and nothing can be compared. One shape
means the replies stack into a matrix, and the matrix is the point — congruence
is only visible across projects, never within one.
