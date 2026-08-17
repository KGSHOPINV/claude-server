# SSH Connection

## Quick Connect

```bash
# Local network
ssh {{server.ssh_user}}@{{server.local_ip}}

# Via Tailscale (from anywhere)
ssh {{server.ssh_user}}@{{server.tailscale_ip}}
```

## Connection Details

| Key | Value |
|-----|-------|
| Local IP | `{{server.local_ip}}` |
| Tailscale IP | `{{server.tailscale_ip}}` |
| SSH User | `{{server.ssh_user}}` |
| Home Dir | `{{server.home_dir}}` |
| Port | 22 (default) |

## SSH Config (work PC)

Add to `~/.ssh/config` for a short alias:

```
Host myserver
    HostName {{server.local_ip}}
    User {{server.ssh_user}}
    IdentityFile ~/.ssh/id_ed25519_server
    IdentitiesOnly yes
```

Then connect with just: `ssh myserver`

## If You Get Locked Out (Fail2Ban)

Fail2Ban bans after **3 failed attempts** for **24 hours**.

Check current bans:
```bash
sudo fail2ban-client status sshd
```

Unban your IP from the server console:
```bash
sudo fail2ban-client set sshd unbanip YOUR_IP
```

**From the hub:** Settings → Security → open the Terminal and run the unban command.
Or use the Context Panel (right sidebar) → Fail2Ban → Unban My IP.

## Key Security Notes

- SSH key auth only — password auth is disabled
- Fail2Ban active: 3 failures = 24h ban
- UFW firewall blocks all ports except 22, 8765 (and services you explicitly open)

## See Also

- `remote-access.md` — Tailscale, Cloudflare Tunnel, access from anywhere
- `troubleshooting.md` — SSH won't connect, key rejected
