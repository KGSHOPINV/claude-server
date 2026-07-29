# Docker — What You Need to Know

## The Analogy

Docker is like a building with apartments:
- The **server** is the building
- Each **container** is an apartment
- Each apartment runs one app (Homepage, Portainer, etc.)
- Apartments are independent — one crashes, others keep running
- The **docker-compose.yml** file is the lease — defines what the apartment looks like

## Key Commands

```bash
# See what's running
docker ps                         # list running containers
docker ps -a                      # list ALL containers (including stopped)

# Container controls
docker restart container_name     # restart
docker stop container_name        # stop
docker start container_name       # start
docker logs container_name        # view logs
docker logs -f container_name     # watch logs live (Ctrl+C to stop)

# Docker Compose (run from service folder)
docker compose up -d              # start service (detached)
docker compose down               # stop service
docker compose pull               # download latest image
docker compose restart            # restart service
docker compose logs -f            # watch logs

# Cleanup
docker system prune               # remove unused stuff (safe)
docker system prune -a             # remove everything unused (more aggressive)
docker volume prune                # remove unused data volumes (CAREFUL)
```

## Where Things Live

```
/srv/docker/           <- all service folders
  homepage/
    docker-compose.yml <- defines the service
    config/            <- service config files (if any)
    data/              <- service data (if any)
```

## Common Patterns

### Start a stopped service
```bash
cd /srv/docker/homepage
docker compose up -d
```

### Update a service to latest version
```bash
cd /srv/docker/homepage
docker compose pull
docker compose up -d
```

### Check why something is broken
```bash
docker logs homepage --tail 50    # last 50 log lines
```

### See resource usage
```bash
docker stats                      # live CPU/RAM per container (Ctrl+C to exit)
```
