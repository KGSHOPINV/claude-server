# Docker Commands

## Aliases (interactive SSH sessions only)

| Alias | Full command |
|-------|-------------|
| `dps` | `docker ps` |
| `dlogs NAME` | `docker logs -f NAME` |
| `dcu` | `docker compose up -d` |
| `dcd` | `docker compose down` |
| `dcr` | `docker compose restart` |

> Note: aliases only work in interactive SSH sessions, not in non-interactive commands.

## Managing Containers

```bash
# See all running containers
docker ps --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"

# See ALL containers (including stopped)
docker ps -a

# Restart a container
docker restart CONTAINER_NAME

# Stop / start
docker stop CONTAINER_NAME
docker start CONTAINER_NAME

# Follow logs
docker logs -f --tail 50 CONTAINER_NAME

# Exec into a container
docker exec -it CONTAINER_NAME bash
```

## Managing Stacks (Compose)

All stacks live under `/srv/docker/`. To manage one:

```bash
cd /srv/docker/STACK_NAME

docker compose up -d      # start / update
docker compose down       # stop and remove
docker compose restart    # restart all services
docker compose logs -f    # follow logs
docker compose pull       # pull new images
```

## Installed Stacks

| Stack folder | Service |
|-------------|---------|
| `npm/` | Nginx Proxy Manager |
| `portainer/` | Portainer |
| `homepage/` | Homepage dashboard |
| `uptime-kuma/` | Uptime Kuma |
| `netdata/` | Netdata |
| `dozzle/` | Dozzle logs |
| `ai/` | Ollama + Open WebUI |

## Install Extra Services

Re-run the extras setup script to install Supabase, n8n, Redis, etc:

```bash
~/server-kit/08-extras-setup.sh
```

## Docker Network

All services share the `proxy` Docker network for internal communication.

```bash
# Inspect the proxy network
docker network inspect proxy

# List all networks
docker network ls
```
