# FlareVault — the boundary, from ServerHub's side

> **What this is:** the ownership boundary between ServerHub and FlareVault,
> written down so neither side has to guess. **Relayed from FlareVault in
> August 2026** and kept as a record of that hand-off.
>
> **It is not a status report on FlareVault, and must never become one.**
> FlareVault owns its own state; a copy of it kept here would be a second
> source of truth for a fact this repo does not own — Law IV. Anything below
> phrased in the present tense describes the August 2026 hand-off.
>
> What ServerHub can honestly say about FlareVault at any moment is limited to
> what it can observe: `python3 hub/tools/edges.py` names the joint and what
> binds each write; `curl -s <hub>/api/receipt` shows the container, up or
> down.

---

## What FlareVault Is

FlareVault is a credential mesh node. It is the single authoritative source for every key, token, API credential, and server detail across the entire project ecosystem.

It is not just a Cloudflare tool — Cloudflare is the primary integration surface, but FlareVault is the intersection for **all credentials** of any kind.

---

## Core Function

| Role | What it does |
|------|-------------|
| **Credential vault** | Holds ALL keys, tokens, API credentials, server details |
| **Cloudflare overseer** | Manages Cloudflare API tokens across all domains — opens and closes connections, makes projects go live |
| **Mesh node** | Runs in Docker, can replicate/connect to FlareVault on another server |
| **Access controller** | Determines which credentials are open to which project at any time |

---

## Deployment Model

- **Primary**: Docker container — organizational structure + protection
- **Also planned**: Non-Docker option for flexibility
- **Mesh**: One FlareVault node per server — nodes communicate bidirectionally
- **Extension model**: When a user deploys on a new server, they get a FlareVault extension that connects back to the primary node

---

## Ecosystem Placement

```
FlareVault (Docker node)
    ↕ bidirectional mesh
FlareVault (another server's node)

FlareVault ←── is part of ──→ Metaforge
FlareVault ←── monitored by → Server Hub
FlareVault ←── feeds creds to → any project that needs them
```

---

## Metaforge Relationship

FlareVault is built into Metaforge as its credential layer. Metaforge tenancy model:

- **Single project = single tenant** — one Metaforge, one tenant, that IS the project
- **Meta project** = multiple projects, multiple tenants — FlareVault coordinates credentials across all of them
- The vault/credential discussion for multi-tenant lives at the Metaforge level — Server Hub delegates to it

---

## Server Hub Relationship

Server Hub's role with FlareVault is **monitor + access point only**:

| What Hub does | What Hub does NOT do |
|--------------|---------------------|
| Watches FlareVault Docker node health (up/down) | Control FlareVault internals |
| Shows FlareVault status in Platform view | Store credentials itself |
| Provides access point interface | Replace FlareVault |
| Alerts if FlareVault node goes down | |

The current Vault in Server Hub (client-side AES password vault) is a **placeholder** — it gets retired when FlareVault integration is ready. FlareVault becomes the credential layer for the hub ecosystem.

---

## The hub's own vault — a placeholder, by decision

The hub's vault holds **pointers, never values**, and the constitution says so:
*credentials are never here.* The node holds no key and creates no hostname.

It is explicitly a placeholder. When FlareVault integration lands, the hub's
vault UI becomes a **window into FlareVault**, not its own storage. That is the
decision; it does not expire.

---

## What Is NOT Server Hub's Concern

- FlareVault's internal USB master key system — that is FlareVault's own security layer
- How FlareVault stores or encrypts credentials internally
- FlareVault ↔ Metaforge internals

---

## Open Questions (to resolve in FlareVault project)

- How does Server Hub authenticate to the FlareVault node?
- Which credentials does Hub get access to vs which are project-only?
- What does the monitor API from FlareVault look like (health endpoint)?

---

*This document describes ServerHub's relationship to FlareVault only. Full
FlareVault architecture lives in the FlareVault project, and carrying their
paperwork here is how a second source of truth starts.*
