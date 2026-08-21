# FlareVault — Designator Document
> Current state + ecosystem placement as of Aug 2026

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

## Current Hub Vault Status

- Existing hub vault = client-side AES encrypted, master password never leaves browser
- Status: **placeholder — to be replaced by FlareVault integration**
- When FlareVault is ready: hub vault UI becomes a window into FlareVault, not its own storage

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

*This document describes Server Hub's relationship to FlareVault only. Full FlareVault architecture lives in the FlareVault project.*
