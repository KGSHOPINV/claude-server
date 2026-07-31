# SSH Connection

## Quick Connect

```bash
ssh homeserver
```

SSH config alias defined at `~/.ssh/config`. Uses key `id_ed25519_server` with no passphrase.

## Full Connection Details

| Key | Value |
|-----|-------|
| Host | 192.168.1.229 |
| User | admin1 |
| Key | `~/.ssh/id_ed25519_server` |
| Port | 22 (default) |

## If You Get Locked Out (Fail2Ban)

Fail2Ban bans after **3 failed attempts** for **24 hours**.

**Unban your work PC (192.168.1.192):**

```bash
sudo fail2ban-client set sshd unbanip 192.168.1.192
sudo ufw delete 1
```

Check current bans:
```bash
sudo fail2ban-client status sshd
```

## SSH Config File

Location: `C:\Users\OEM-Nissan1\.ssh\config`

```
Host homeserver
    HostName 192.168.1.229
    User admin1
    IdentityFile ~/.ssh/id_ed25519_server
    IdentitiesOnly yes
```

## Key Files

| File | Purpose |
|------|---------|
| `~/.ssh/id_ed25519_server` | Private key (work PC) |
| `~/.ssh/id_ed25519_server.pub` | Public key |
| `~/.ssh/authorized_keys` (server) | Where the public key lives |

## Security Notes

- Fail2Ban is active — 3 failures = 24h ban, repeat offenders = 1 week
- CrowdSec is installed but currently **inactive** — start with `sudo systemctl start crowdsec` if needed
- SSH hardening config at `/etc/ssh/sshd_config` (backup at `.bak`)
