# Known Issues

## OPEN

### 1. CLI Aliases Not Working for admin1
- **Problem**: Commands like `menu`, `health`, `dkps` don't work as aliases
- **Cause**: Script 10 ran with `sudo`, so aliases were written to root's `.bashrc` instead of admin1's
- **Workaround**: Use full command names (`server-menu`, `health-check`, etc.) — these work because they're in `/usr/local/bin/`
- **Fix**: Add aliases to admin1's bashrc:
```bash
echo 'alias menu="server-menu"' >> /home/admin1/.bashrc
echo 'alias health="health-check"' >> /home/admin1/.bashrc
echo 'alias dkps="docker ps --format \"table {{.Names}}\t{{.Status}}\t{{.Ports}}\""' >> /home/admin1/.bashrc
source /home/admin1/.bashrc
```

### 2. Dozzle Port May Be Wrong on Live Server
- **Problem**: Dozzle docker-compose on the server may still map port 8080 instead of 8090
- **Check**: Look at `/srv/docker/dozzle/docker-compose.yml` on the server
- **Fix**: Change `8080:8080` to `8090:8080`, then `docker compose up -d`

### 3. AI Stack is CPU-Only (Very Slow)
- **Problem**: No GPU installed. AI models use 100% CPU and respond slowly
- **Impact**: Server fans spin up, other services may slow down
- **Workaround**: Keep AI stack OFF (`cd /srv/docker/ai && docker compose down`) unless actively using it
- **Fix**: Install a GPU, or use smaller models only (qwen3:4b, phi4-mini)

### 4. Netdata Console Access
- **Problem**: Netdata web UI may require account setup or shows limited data
- **Status**: Needs investigation

---

## RESOLVED

(none yet — move issues here once fixed)
