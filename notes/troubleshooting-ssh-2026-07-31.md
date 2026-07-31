# Troubleshooting: SSH Access Blocked — 2026-07-31

## What Happened

Claude could not SSH into the server. The work PC (192.168.1.192) was being blocked.

## Root Cause Chain

1. **No SSH key set up** — Claude's Bash tool tried to connect using the existing `id_ed25519` key, which had an unknown passphrase. Auth failed.
2. **Multiple failed attempts** — While trying to fix key auth, several failed SSH attempts happened from the work PC IP (192.168.1.192).
3. **Fail2Ban triggered** — After 3 failed attempts against sshd, Fail2Ban automatically added a UFW REJECT rule for the work PC's IP, blocking ALL traffic from it.
4. **Looked like a network problem** — The block caused SSH to time out instead of saying "wrong password", which made it look like a firewall or network issue.

## How We Fixed It

### Step 1 — Diagnosed the firewall
```bash
sudo ufw status numbered
```
Found: `[1] REJECT IN 192.168.1.192  # by Fail2Ban after 3 attempts against sshd`

### Step 2 — Removed the Fail2Ban block
```bash
sudo ufw delete 1
```

### Step 3 — Restarted SSH (it had a config change pending)
```bash
sudo systemctl daemon-reload
sudo systemctl restart ssh
```

### Step 4 — Added the correct SSH key to the server
Generated a new key with no passphrase on the work PC:
```
ssh-keygen -t ed25519 -f "C:\Users\OEM-Nissan1\.ssh\id_ed25519_server"
# Press Enter twice for no passphrase
```

Added the public key to the server:
```bash
echo "ssh-ed25519 AAAAC3...KEY...E+N oem-nissan1@DESKTOP-6RL53JO" >> ~/.ssh/authorized_keys
```

### Step 5 — Created SSH config on work PC
File: `C:\Users\OEM-Nissan1\.ssh\config`
```
Host homeserver
    HostName 192.168.1.229
    User admin1
    IdentityFile ~/.ssh/id_ed25519_server
    IdentitiesOnly yes
```

## If This Happens Again

1. Check if Fail2Ban blocked the IP: `sudo ufw status numbered` — look for REJECT rules
2. Remove the block: `sudo ufw delete [rule number]`
3. Or unban from Fail2Ban directly: `sudo fail2ban-client set sshd unbanip 192.168.1.192`

## Prevention

Consider whitelisting the work PC in Fail2Ban so it can never be blocked:
```bash
echo "[DEFAULT]" | sudo tee /etc/fail2ban/jail.local
echo "ignoreip = 127.0.0.1/8 192.168.1.192" | sudo tee -a /etc/fail2ban/jail.local
sudo systemctl restart fail2ban
```
