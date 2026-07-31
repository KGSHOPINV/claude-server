# Known Issues

## OPEN

### 1. CLI Aliases Not Working for admin1
- **Problem**: Commands like `dkps`, `dklogs` from CLAUDE.md don't exist — actual shortcuts are `dps`, `dlogs`, `dcu`, `dcd`, `dcr`
- **Cause**: CLAUDE.md was written with wrong alias names
- **Fix**: Update CLAUDE.md to use correct names (done in this session)

### 2. Dozzle Not Running
- **Problem**: Dozzle container exists (Created) but is not running
- **Port**: Health-check confirms port 8090 is correct
- **Fix**: `cd /srv/docker/dozzle && docker compose up -d`

### 3. Most of Stack Not Installed
- **Problem**: 18 services show DOWN — Supabase, n8n, SurrealDB, MinIO, Wiki.js, etc. not installed yet
- **Status**: Only foundation stack is running (NPM, Portainer, Homepage, Netdata, Uptime Kuma, ntfy)
- **Fix**: Run setup scripts from server-kit or install individually

### 4. AI Stack is CPU-Only (Very Slow)
- **Problem**: No GPU installed. AI models use 100% CPU and respond slowly
- **Workaround**: Keep AI stack OFF unless actively using it

### 5. High Load Average Observed
- **Problem**: Load average was 7.15 / 3.50 / 1.47 during session on 2026-07-31 with only 6 containers running
- **Status**: Needs monitoring — could be normal or indicate a runaway process
- **Check**: `top` or `htop` on the server

### 6. ntfy Running on Port 8085 (Not in Original Stack)
- **Status**: Running fine, just not documented in CLAUDE.md
- **URL**: http://192.168.1.229:8085

---

## RESOLVED

### SSH Blocked by Fail2Ban (2026-07-31)
- **Problem**: SSH from work PC (192.168.1.229) was timing out
- **Cause**: Fail2Ban blocked the work PC's IP (192.168.1.192) after 3 failed SSH auth attempts during key setup
- **Fix**: `sudo ufw delete 1` (removed the Fail2Ban REJECT rule for the IP)
- **Prevention**: Set up correct SSH key before multiple failed attempts; consider whitelisting the work PC IP in Fail2Ban config

### SSH Key Not Set Up (2026-07-31)
- **Problem**: Claude's Bash tool could not SSH into the server
- **Cause**: No passwordless key was in server's authorized_keys
- **Fix**: Generated `id_ed25519_server` (no passphrase), added public key to `~/.ssh/authorized_keys` on server
- **SSH Config**: Created `~/.ssh/config` on work PC to auto-use the right key
