# Server commands

**Save this file in your project's repo at first admit.** It is the whole
interface between this project and the server it runs on. Nothing else needs to
be remembered, and nothing here needs re-explaining later.

When the operator says **"pull up our server commands"**, open this file and run
what they name.

---

## Your identity — fill this in once, at first admit

```
PROJECT   <your-name>
SERVER    http://192.168.50.100:8765      ← ksgcohub
                or
          http://192.168.1.229:8765       ← fks-services
LAST PIN  <the last bulletin PIN you acknowledged>
```

Your project lives on **one** server. The rules come from that host's disks and
its bound ports, so the other server gives different — and equally correct —
answers. Never carry an answer across.

---

## The command tree

```
server status          where do I stand
server bulletins       what has the server published that I have not read
server read <n>        pull bulletin n in full
server ack <n> <pin>   confirm I read it — the PIN proves it
server rules           my operating set: band, paths, labels, forbidden
server claim           tell the server the half it cannot see
server ticket          report a problem BEFORE fixing it myself
```

Seven. That is the entire surface.

---

## What each one does

### `server status`
```bash
curl -s $SERVER/api/registry/$PROJECT
```
Your standing record: registered or not, what the machine sees of you, which
bulletin you last acknowledged, and whether you are behind.

### `server bulletins`
```bash
curl -s $SERVER/api/bulletins?since=$LAST_PIN
```
What the server has published that you have not read. Usually empty. Empty is
reported as `none` rather than silence — those are different answers and only
one is information.

### `server read <n>`
```bash
curl -s $SERVER/api/bulletins/<n>
```
The full bulletin. **Read it whole.** It ends with a PIN, and the PIN is the
proof you read it. Do not skim for the number — a bulletin you skimmed is a
change you will be surprised by.

While you are reading a bulletin, do nothing else. You were pointed here
deliberately.

### `server ack <n> <pin>`
```bash
curl -s -X POST $SERVER/api/ack/$PROJECT \
  -H 'Content-Type: application/json' \
  -d '{"bulletin": <n>, "pin": "<pin>", "answer": "what I will do about it"}'
```
`answer` is required even when it is *"nothing, does not affect me"*. An
unanswered change is how a project ends up bound to a port that moved
underneath it.

Acknowledging unlocks the next rung. You cannot read what is coming until you
have confirmed what is.

### `server rules`
```bash
curl -s $SERVER/api/admit?project=$PROJECT
```
Your operating set, derived live from this host:

- the port band you may bind inside
- your data paths — `db` / `media` / `cache` / `releases` / `public` / `private`
- the labels every container must carry
- what is forbidden
- the acceptance test that proves you complied

Run this before you deploy anything. It is computed from the machine at the
moment you ask, so it is never stale.

### `server claim`
```bash
curl -s -X POST $SERVER/api/registry/$PROJECT \
  -H 'Content-Type: application/json' -d @claim.json
```
The half the server **cannot see**: your Cloudflare zone and hostname, your
tunnel, your Access policy, your DNS, where your secrets live, who your users
are, what you believe you are, and what you plan next.

Do not report containers, ports or mounts — the server already reads those, and
a guess there is worse than a gap. This is strictly what it cannot derive.

### `server ticket`
```bash
curl -s -X POST $SERVER/api/ticket/$PROJECT \
  -H 'Content-Type: application/json' \
  -d '{"problem": "...", "what_i_see": "..."}'
```
**Before you fix it yourself.** You see "my container will not start." The
server sees the disk at 96%, or another project holding your port, or a volume
pruned, or a band that moved.

A project fixing blind is how isolation gets broken in the name of getting
unstuck — rebinding to a random free port, dropping data on the OS disk, joining
another project's network. File the ticket, get the diagnosis, then fix it. You
still do the fixing; you just do the right one.

---

## The two rules that matter

**1. Check in when told, not on a schedule.** You are not polling. The operator
says *"pull up our server commands"* and names a function. Between those, do
nothing.

**2. Your compliance is your own.** Nothing here blocks you. No bulletin stops a
deploy, no unacknowledged change breaks anything. The server publishes and
records; it does not enforce. Which means reading them is the only thing keeping
you from being surprised.

---

## Why this exists

So the operator stops being the messenger.

Before this, every server change had to be carried by hand into each project,
and each project's state had to be carried back. That does not scale past a
couple of projects and it is how a port band moved under four of them with none
of them told.

The server holds the truth. You ask it. It tells you what changed. You say what
you will do. Nobody repeats themselves.
