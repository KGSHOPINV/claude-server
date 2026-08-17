# Troubleshooting

## SSH Won't Connect

**Symptom:** `Permission denied` or connection times out.

1. Check if server is reachable: `ping {{server.local_ip}}`
2. Check Fail2Ban — you may be banned after 3 failed attempts
3. If banned, unban from another machine or the server console

**Unban your IP:**
```bash
sudo fail2ban-client set sshd unbanip YOUR_IP
```

**Check who is banned:**
```bash
sudo fail2ban-client status sshd
```

**If key is rejected:**
```bash
# Check key permissions
chmod 600 ~/.ssh/id_ed25519_server

# Verify key is in authorized_keys on server
cat {{server.home_dir}}/.ssh/authorized_keys
```

## Container Won't Start

```bash
# Check the logs
docker logs CONTAINER_NAME --tail 50

# Run without -d to see errors inline
cd /srv/docker/CONTAINER_NAME
docker compose up
```

Common causes:
- Port already in use (see below)
- Volume permission issue — check file ownership
- Missing env var — check `.env` file in compose dir

## Port Already in Use

```bash
# Find what's using a port
sudo ss -tlnp | grep :PORT
sudo lsof -i :PORT
```

## Portainer Timeout

If Portainer shows a setup timeout error:
```bash
docker restart portainer
```
Then immediately open `https://{{server.local_ip}}:9443` and complete setup.

## Disk Space

```bash
df -h /            # overall disk usage
docker system df   # Docker space usage

# Clean up unused Docker objects
docker system prune -a   # WARNING: removes unused images
docker volume prune
```

## Memory

```bash
free -h    # RAM usage summary
htop       # interactive process viewer
```

## Backup

```bash
# Run a manual backup now
sudo server-backup

# Check backup logs
cat /var/log/server-backup.log

# Backup location
ls /srv/backups/
```

## Security

```bash
sudo ufw status numbered          # firewall rules
sudo fail2ban-client status sshd  # who's banned
```

## See Also

- `ssh.md` — SSH connection details and Fail2Ban
- `docker.md` — container management commands
