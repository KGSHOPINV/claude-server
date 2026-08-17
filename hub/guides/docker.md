# Docker Commands

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

# Exec into a running container
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

## Docker Disk Usage

```bash
# Summary of images, containers, volumes
docker system df

# Prune unused images and stopped containers
docker system prune

# Prune everything including unused volumes (careful)
docker system prune -a --volumes
```

## Docker Network

All services share the `proxy` Docker network for internal communication.

```bash
docker network inspect proxy
docker network ls
```

## See Also

- `services.md` — all installed stacks and their ports
- `troubleshooting.md` — container won't start, port conflicts
