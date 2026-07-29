# Server Map — How Everything Connects

## The Big Picture

```
INTERNET
    |
[Cloudflare] ---- DNS + protection (optional, not yet configured)
    |
[Router/Firewall] ---- your home network
    |
[Server: 192.168.1.229] ---- Ubuntu 24.04, 216GB RAM, no GPU
    |
[Docker Engine] ---- runs EVERYTHING below
    |
    +-- [Nginx Proxy Manager :81]
    |       Routes domain names to the right container
    |       Example: myapp.mydomain.com -> container on port 3000
    |
    +-- TIER 1: Foundation
    |   +-- Portainer (:9443) — container manager (GUI)
    |   +-- Watchtower — auto-updates containers
    |
    +-- TIER 2: Monitoring
    |   +-- Homepage (:3000) — your main dashboard
    |   +-- Uptime Kuma (:3001) — is stuff running?
    |   +-- Netdata (:19999) — CPU/RAM/disk graphs
    |   +-- Dozzle (:8090) — live logs
    |   +-- Cockpit (:9090) — system admin
    |
    +-- TIER 3: Tools
    |   +-- Databases: Supabase, Postgres, SurrealDB, Redis, MinIO
    |   +-- Dev: n8n, Adminer, Mailpit, Wiki.js, LanguageTool
    |
    +-- TIER 4: AI (OFF by default)
        +-- Ollama (:11434) — runs AI models
        +-- Open WebUI (:3004) — chat interface
        +-- OpenClaw (:3005) — playground
```

## What Talks to What

- **You** -> browser -> Homepage (:3000) = see everything at a glance
- **You** -> browser -> Portainer (:9443) = manage containers visually
- **You** -> SSH -> terminal = run commands directly
- **NPM** sits in front of services and maps domain names to ports
- **Watchtower** runs in background, pulls new container images automatically
- **Uptime Kuma** pings services every 60 seconds, alerts if something dies

## Storage Layout

```
/dev/sda (1TB SSD) — OS drive
  /          — Ubuntu system
  /srv/docker/ — all container configs + data

/dev/sdb (4TB HDD) — data drive (mounted at /mnt/storage)
  /mnt/storage/backups/   — automated backups
  /mnt/storage/media/     — media files
  /mnt/storage/documents/ — document storage
```
