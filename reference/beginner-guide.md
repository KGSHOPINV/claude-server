# Server Beginner Guide — Start Here

## What is a Server?

A computer that runs 24/7 and hosts services (apps, databases, websites).
Your server runs Ubuntu Linux and uses Docker to run everything in isolated containers.

---

## Key Concepts (the stuff you actually need to know)

### Docker
- Think of it as: **every app runs in its own little box**
- Each box is called a **container**
- Containers are defined by **docker-compose.yml** files
- You can start, stop, restart any container without affecting others
- All your containers live in `/srv/docker/`

### Ports
- Every service listens on a **port number** (like an apartment number)
- Your server IP is `192.168.1.229`
- To access a service: `http://192.168.1.229:PORT`
- Example: Homepage is port 3000 -> `http://192.168.1.229:3000`

### SSH
- **S**ecure **Sh**ell = remote terminal access to the server
- From your work PC: `ssh admin1@192.168.1.229`
- Now you're typing commands ON the server
- Type `exit` to disconnect

### sudo
- Means "do this as admin"
- Some commands need it: `sudo apt update`
- Your user (admin1) has sudo access

### Docker Compose
- The config file that defines a service
- Located at `/srv/docker/SERVICE_NAME/docker-compose.yml`
- `docker compose up -d` = start the service
- `docker compose down` = stop the service
- `docker compose logs -f` = watch what it's doing
- Always `cd` into the service folder first

---

## Your First 5 Things to Try

### 1. Open Homepage
Open browser: `http://192.168.1.229:3000`
This is your dashboard. See what's running.

### 2. Run a Health Check
SSH in, then:
```bash
health-check
```
Shows every service status + which ports are open.

### 3. Open Portainer
Browser: `https://192.168.1.229:9443`
Click "Containers" on the left. Green = running. Red = stopped.
You can start/stop/restart anything here WITHOUT terminal.

### 4. Check Logs for a Service
SSH in, then:
```bash
dklogs homepage
```
Shows what Homepage is doing. Replace `homepage` with any container name.

### 5. Open the Menu
SSH in, then:
```bash
server-menu
```
Interactive menu — pick a number, it does the thing.

---

## When Things Go Wrong

| Problem | What to do |
|---------|-----------|
| A service won't load in browser | `dkrestart service-name` |
| Everything seems slow | `ssh in` -> check `htop` for CPU/RAM hogs |
| Container keeps crashing | `dklogs service-name` to see the error |
| Disk space full | `df -h` to check, `docker system prune` to clean |
| Can't SSH in | Server might be off, or network issue |
| Forgot a port number | `health-check` or check CLAUDE.md |

---

## Commands Cheat Sheet

```bash
# STATUS
health-check              # full status report
dkps                      # list running containers
htop                      # live CPU/RAM monitor (q to quit)
df -h                     # disk space
free -h                   # RAM usage

# MANAGE CONTAINERS
dkrestart [name]          # restart a container
dkstop [name]             # stop a container
dkstart [name]            # start a container
dklogs [name]             # view logs

# SYSTEM
server-update             # update everything
server-backup             # run backup
sec                       # security check
server-menu               # interactive menu

# DOCKER COMPOSE (from service folder)
docker compose up -d      # start
docker compose down       # stop
docker compose pull       # download latest version
docker compose logs -f    # watch logs live
```

---

## Understanding What You See

### In Portainer
- **Green dot** = container is running fine
- **Red dot** = container is stopped or crashed
- **"Stacks"** = groups of containers that work together (like Supabase has multiple)
- Click a container name to see its logs, stats, and settings

### In Homepage
- Cards = services
- Each card can show status (up/down) and stats
- Configured via YAML files in `/srv/docker/homepage/`

### In Dozzle
- Pick a container from the left sidebar
- Logs stream in real-time
- Color coding: white=info, yellow=warning, red=error
