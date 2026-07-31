# Quick Reference

## Server
- IP: 192.168.1.229
- SSH: `ssh admin1@192.168.1.229`
- OS: Ubuntu 24.04 LTS

## Key Service URLs
| Service | URL |
|---------|-----|
| Homepage | http://192.168.1.229:3000 |
| Portainer | https://192.168.1.229:9443 |
| Supabase | http://192.168.1.229:8000 |
| n8n | http://192.168.1.229:5678 |
| Dozzle (logs) | http://192.168.1.229:8090 |
| NPM | http://192.168.1.229:81 |
| Cockpit | https://192.168.1.229:9090 |
| Netdata | http://192.168.1.229:19999 |

## Docker Compose Root
`/srv/docker/` on the server

## Useful SSH Shortcuts
```bash
ssh admin1@192.168.1.229 "dkps"           # list running containers
ssh admin1@192.168.1.229 "health-check"   # full status report
ssh admin1@192.168.1.229 "dklogs NAME"    # tail logs for a container
```
