# Remote Access

How to reach your server from anywhere — SSH, hub UI, raw service ports, and sharing things publicly.

---

## The Core Division

```
Your devices only  →  Tailscale (intranet extension)
Public internet    →  Cloudflare Tunnel + Access
```

These two tools are complementary, not competing. Most setups need both.

---

## Tailscale — Intranet from Anywhere

Tailscale creates a private mesh network between every device you enroll. Each gets a persistent `100.x.x.x` address. Once connected, you are on the intranet — same as sitting on the LAN.

**What you get:**
- SSH: `ssh user@100.x.x.x` from anywhere, no port forwarding
- Every port on the server: Portainer `:9443`, Netdata `:19999`, Dozzle `:8090` — all reachable directly
- Hub: `http://100.x.x.x:8765` from any enrolled device
- Devices talk to each other too — laptop, phone, second server, all on the same mesh

**What it is under the hood:**  
WireGuard VPN with a coordination server that handles key exchange and NAT traversal automatically. Tailscale runs the coordination layer (free tier: 3 users, 100 devices). If you want to self-host that layer, see **Headscale** below.

**Setup:**
```bash
# On the server (one time)
curl -fsSL https://tailscale.com/install.sh | sh
sudo tailscale up

# On each client device: install from tailscale.com, sign in with same account
# That's it — devices find each other automatically
```

**When you have Tailscale, you don't need:**
- Port forwarding for any service
- Cloudflare Tunnel for private access
- SSH bastion/jump hosts

---

## Cloudflare Tunnel — Public Front Door

Cloudflare Tunnel runs a lightweight outbound connection (`cloudflared`) from your server to Cloudflare's edge. No open ports on your router. Cloudflare proxies inbound traffic to your local service.

**What you get:**
- A public URL (`https://hub.yourdomain.com`) that reaches a local service
- HTTPS automatically — Cloudflare handles the cert
- DDoS protection, WAF, bot filtering at the edge
- Works from any browser in the world — no Tailscale enrollment needed

**What it doesn't give you:**
- Access to arbitrary ports (you configure tunnels per service, not per port)
- SSH tunneling without extra Cloudflare config
- Any path that doesn't go through Cloudflare's servers

**Add Cloudflare Access on top:**  
Access is a zero-trust auth gate that sits in front of your Tunnel. Before a request ever reaches your service, Cloudflare challenges the user — email OTP, Google, GitHub, or any OIDC provider. Free tier available.

```
Browser → Cloudflare Edge → Access auth check → Tunnel → your service
```

**When you'd reach for Tunnel over Tailscale:**
- Sharing a service with someone who isn't in your tailnet
- Public-facing URL you can hand out (a docs site, a dashboard for a client)
- Services that need to be internet-accessible (webhooks, public APIs)

---

## Headscale — Self-Hosted Tailscale Coordination

Tailscale's mesh is WireGuard. The only part that touches Tailscale's servers is the coordination layer (device discovery + key exchange). Headscale replaces that with your own server.

**Why you'd want it:**
- Full data sovereignty — nothing goes through Tailscale's infrastructure
- No user/device limits
- Works offline from the public internet (air-gapped environments)

**Trade-off:** You manage the server, auth, and availability. Tailscale's free tier is generous enough that most homelab setups don't need this yet.

---

## WireGuard (Raw)

The protocol under Tailscale. You can run it directly — generate key pairs, write config files, manage peer lists yourself. Same end result as Tailscale but every step is manual.

**Reach for raw WireGuard when:**
- You want zero third-party coordination (not even Headscale)
- You're embedding VPN into a custom appliance
- You need extremely fine-grained routing control

For a homelab: Tailscale/Headscale is almost always the right call over raw WireGuard.

---

## What to Avoid

| Method | Problem |
|--------|---------|
| **Port forwarding** | Opens a port to the entire internet. Fine for SSH with key-only auth + Fail2Ban. Bad for web UIs. |
| **ngrok / serveo** | Dev-only tunnels. Ephemeral URLs, rate limits, third-party sees your traffic. |
| **SSH tunneling manually** | `ssh -L 9443:localhost:9443 user@server` — works but fragile, requires SSH access first, manual per port |

---

## Your Stack at a Glance

| Access path | Tool | Who for |
|-------------|------|---------|
| Local network | LAN IP (192.168.x.x) | Any device on the router |
| Private remote | Tailscale (100.x.x.x) | Your enrolled devices |
| Public remote | Cloudflare Tunnel | Anyone with the URL |
| Public + auth | Cloudflare Tunnel + Access | Controlled public access |

The hub's **Remote** view shows all three paths live — local address, Tailscale address, and Cloudflare tunnel status — so you always know what's reachable from where.

---

## Quick Diagnosis

**Can't reach the server remotely?**

1. Are you on the same LAN? → Use local IP  
2. Is Tailscale running on both devices? → `tailscale status` — use `100.x.x.x`  
3. Need a public URL? → Check Cloudflare Tunnel status in the hub Remote view  
4. SSH blocked? → Check Fail2Ban: `sudo fail2ban-client status sshd`  
   Unban your IP: `sudo fail2ban-client set sshd unbanip <your-ip>`

---

## See Also

- `ssh.md` — SSH hardening, key auth, Fail2Ban
- `services.md` — all services and their ports
- `PORTS.md` (repo root) — port lane registry
