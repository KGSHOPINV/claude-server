# Troubleshooting

## SSH Won't Connect

**Symptom:** `Permission denied` or connection times out.

1. Check if server is reachable: `ping 192.168.1.229`
2. Check Fail2Ban: you may be banned after 3 failed attempts
3. If banned, you need physical/console access or another IP to unban yourself

**Unban from the server:**
```bash
sudo fail2ban-client set sshd unbanip 192.168.1.192
sudo ufw delete 1
```

**If key is rejected:**
- Verify public key is in `/home/admin1/.ssh/authorized_keys` on server
- Check key permissions: `chmod 600 ~/.ssh/id_ed25519_server`

## Container Won't Start

```bash
# Check the logs
docker logs CONTAINER_NAME --tail 50

# Check compose config
cd /srv/docker/CONTAINER_NAME
docker compose config   # validate the compose file
docker compose up       # run without -d to see errors inline
```

Common causes:
- Port already in use: `sudo ss -tlnp | grep PORT`
- Volume permission issue: check file ownership
- Environment variable missing: check `.env` file in compose dir

## Port Already in Use

```bash
# Find what's using a port
sudo ss -tlnp | grep :PORT
sudo lsof -i :PORT
```

Known: something is listening on **port 8080** (unknown process — not a container).

## Portainer Timeout

If Portainer shows a setup screen error (initial setup timeout):
```bash
sudo docker restart portainer
```
Then immediately open `https://192.168.1.229:9443` and complete setup.

## Disk Space

```bash
# Overall disk usage
df -h /

# Docker space usage
docker system df

# Clean up unused images, containers, volumes
docker system prune -a   # WARNING: removes unused images
docker volume prune
```

## Memory

```bash
free -h          # current RAM usage
htop             # interactive process viewer
```

Server has 216 GB RAM — memory pressure is unlikely.

## Backup

Manual backup:
```bash
sudo server-backup
```

Logs: `/var/log/server-backup.log`
Backup dir: `/srv/backups/`
Schedule: daily at 3:00 AM (cron)

## Security Check

```bash
security-check      # runs lynis + rkhunter + other checks
sudo ufw status numbered
sudo fail2ban-client status sshd
```
