-- Architecture Decision Log
-- Seed this into decisions.db: sqlite3 decisions.db < decisions.sql
-- Or read directly as a history of why things are the way they are.

CREATE TABLE IF NOT EXISTS decisions (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  date        TEXT NOT NULL,
  title       TEXT NOT NULL,
  context     TEXT,
  decision    TEXT NOT NULL,
  consequence TEXT,
  status      TEXT DEFAULT 'active' -- active | superseded | reverted
);

INSERT INTO decisions (date, title, context, decision, consequence, status) VALUES

('2026-09-01',
 'Hub runs as Python stdlib HTTPServer, not Flask/FastAPI',
 'Need a hub that runs on any Ubuntu server with zero dependencies — no pip install, no venv.',
 'Use Python stdlib http.server.BaseHTTPRequestHandler. No framework. No dependencies beyond stdlib.',
 'Entire backend is one file (server.py). Easy to deploy, hard to modularize. Must be refactored to kernel+handlers architecture.',
 'active'),

('2026-09-01',
 'Hub runs on port 8765 as user systemd service',
 'Need hub to start on boot without root, run under the SSH user account.',
 'systemd --user service. Port 8765 is the canonical hub port across all nodes. Never assign 8765 to a container.',
 'Hub survives reboots without root. Port 8765 is now a hard constraint — any container that tries to use it will conflict.',
 'active'),

('2026-09-01',
 'Frontend is a single app.html file — no build step',
 'Need to ship the UI with zero build tooling so it can be deployed via git pull + systemctl restart.',
 'Single HTML file with embedded CSS and JS. No bundler, no npm, no node_modules.',
 'UI is a 6,518-line monolith. Phase 3 adds ES module split + optional esbuild step. Until then: one file.',
 'active'),

('2026-09-01',
 'Peer mesh uses Tailscale IPs as stable node addresses',
 'LAN IPs can change (DHCP). Hostnames only resolve inside their own subnet.',
 'All peer registration uses Tailscale overlay IPs (100.x.x.x). Hub URLs stored as http://<tailscale_ip>:8765.',
 'Mesh works across home and work networks. Requires Tailscale running on every node.',
 'active'),

('2026-09-02',
 'Auth is opt-in per route (current), will become enforced at router (Phase 1)',
 'Original monolith added routes quickly without a consistent auth pattern.',
 'Current: each route calls check_auth() or gate_check() manually. Phase 1: router enforces auth level from dispatch table.',
 'Until Phase 1: any new route MUST manually call check_auth(). After Phase 1: auth is automatic and cannot be skipped.',
 'active'),

('2026-09-05',
 'n8n uses N8N_SECURE_COOKIE=false on ksgcohub',
 'n8n returns 401 on all API calls when behind Cloudflare proxy — cookie security mismatch.',
 'Set N8N_SECURE_COOKIE=false in n8n docker-compose.yml environment.',
 'n8n API accessible via Tailscale and LAN. Cookie still set, just not Secure-flagged.',
 'active'),

('2026-09-07',
 'ksgcohub static IP via netplan + cloud-init conflict permanently fixed',
 'Ubuntu 24.04 cloud image ships 50-cloud-init.yaml which overwrites static netplan on reboot, dropping default route.',
 'Created /etc/cloud/cloud.cfg.d/99-disable-network-config.cfg to disable cloud-init networking. Removed 50-cloud-init.yaml. Deployed fix-netplan.sh. Static IP and gateway configured in /etc/netplan/01-static.yaml.',
 'ksgcohub has stable static IP and default route on every boot. fix-netplan.sh must be run on every new Ubuntu 24.04 cloud image setup.',
 'active'),

('2026-09-07',
 'Incidents endpoint added to hub — SQLite-backed',
 'Need a place to log server events, outages, fixes. Human and machine readable.',
 'Added /api/incidents GET+POST to server.py. SQLite table: incidents (id, title, body, severity, created_at). Hub UI shows last 50.',
 'Both servers now have a persistent incident log. Severity levels: info, warn, critical.',
 'active'),

('2026-09-07',
 'Boot health check deployed as systemd oneshot on ksgcohub',
 'After the ksgcohub internet outage (no default route), need a post-boot verification that catches issues automatically.',
 'server-kit/tools/boot-health-check.sh runs as systemd oneshot after network-online.target. Checks: default route, internet ping, DNS, Docker, hub:8765. Posts to ntfy on failure.',
 'Any boot problem sends an ntfy push before anyone touches the server. Must be deployed to fks-services too (gap G003).',
 'active'),

('2026-09-09',
 'FlareVault is root authority above Cloudflare — CF is an internal FV component',
 'Architecture discussion clarified that FV is not below CF, CF is a node/component managed by FV.',
 'FlareVault sits above Cloudflare in authority hierarchy. CF Tunnel, DNS, Access are FV-managed resources. FV generates deployment artifacts (ISO) for new nodes.',
 'FV MCP server (Phase 4) connects to CF API to create tunnels and DNS per new mesh node. Previous mesh-blueprint.html diagram had this backwards.',
 'active'),

('2026-09-09',
 'Registry covers entire server state, not just the kernel',
 'Question arose: is the registry just for the kernel, or everything?',
 'Registry covers three layers: servers (UUID primary key), files (repo manifest), services (all Docker containers). The kernel reads/writes the registry. FV is the authority.',
 'knowledge/registry.json is the canonical state barcode. Any AI session touching this repo should read it first.',
 'active'),

('2026-09-09',
 'Device UUID (dmidecode -s system-uuid) as permanent node identity',
 'Need a stable identifier for each server that survives hostname changes, IP changes, and Tailscale re-enrollment.',
 'Use dmidecode system-uuid as the primary key for the servers table in registry.json.',
 'UUIDs must be populated in registry.json and knowledge/servers.json. Currently marked POPULATE_VIA_dmidecode.',
 'active');

-- ── Deployment + access landscape (session 2026-09-10..14) ───────────────────
-- Every failure found in this session was documentation disagreeing with the
-- machine, not a code bug. These rows record the rules that came out of it.

INSERT INTO decisions (date, title, context, decision, consequence, status) VALUES

('2026-09-14',
 'Login matches the trust the path already established (two-door auth)',
 'Reaching the hub through Cloudflare asked twice: Access verified the user with Google, then the hub demanded its own username and password anyway.',
 'Private paths (LAN, Tailscale) already proved identity by how you got there, so a local credential is enough. The public path proves nothing, so the door authenticates: Cloudflare Access with Google. The hub trusts Cf-Access-Authenticated-User-Email ONLY from the tunnel address (HUB_CF_TRUST_IP) -- the trust is the network path, not the header, because anything on the tailnet can forge a header.',
 'One login per path instead of two. The local login must always work, never be disabled and depend on nothing external -- it is the break-glass when Cloudflare or Google is down. Access grants user-level only; gate 2/3 routes still demand stronger proof.',
 'active'),

('2026-09-14',
 'Browsers get SSO, apps get tokens -- never put Access in front of an app endpoint',
 'Cloudflare Access is a browser redirect flow. ntfy is consumed by a mobile app holding a long-lived subscription, with no browser to redirect.',
 'Split auth by CLIENT TYPE, not by service. Browser-facing hostnames get Access + SSO. App/machine endpoints (ntfy, federation, MCP) use their own token ACLs behind the same tunnel.',
 'Putting Access in front of ntfy silently kills push notifications and looks like ntfy broke. Cloudflare still does the transport job either way; only the identity check differs.',
 'active'),

('2026-09-14',
 'Cloudflare proxy carries HTTP/HTTPS only -- SSH goes over Tailscale',
 'A session spent hours retrying SSH to fks.ksgdev.com, concluding the server was rebooting. That hostname resolves to Cloudflare.',
 'Never attempt SSH, SCP or any non-HTTP protocol against a Cloudflare-proxied hostname. Use the Tailscale address. A host that answers HTTP while SSH hangs is the signature of a proxied hostname, not a firewall.',
 'Three paths with different reach: LAN (same network, any protocol), Tailscale (your devices anywhere, any protocol), public hostname (whole internet, HTTP only). Choosing the wrong one wastes hours and looks like an outage.',
 'active'),

('2026-09-14',
 'Every deployable splits into code, config and state',
 'fksinv could not be stood up on a second server: its code lives only on the machine that runs it, with no git repo.',
 'Code comes from git and is disposable. Config is per-node, secret, never committed. State is the only irreplaceable part and must be backed up. A project that cannot be rebuilt on a fresh box in minutes has one of the three not separated.',
 'When code is not in git the running server IS the source of truth, so there is no rollback and no way to detect drift. That is how fks-services sat 15 commits behind unnoticed.',
 'active'),

('2026-09-14',
 'If a build step exists, copying files is not deploying',
 'fks-ui has no bind mounts -- the React app compiles into the image. SCP to disk changes nothing on the live site.',
 'Establish per service whether source is served directly or compiled. Hub serves app.html straight off disk; fks-ui requires docker compose build. Deploy scripts must include the build so it cannot be forgotten.',
 'Skipping the rebuild makes scp exit 0 while the old bundle keeps serving -- a silent success that looks like broken code. Same failure mode as update.sh appearing to work while doing nothing.',
 'active'),

('2026-09-14',
 'Deploy defaults must fail loudly, never silently substitute',
 'docker-compose.yml falls back to DOMAIN=fks.ksgdev.us when .env is missing. Live is .com; the fallback only fires on a fresh deploy.',
 'Use ${VAR:?message} rather than ${VAR:-wrong-default} for anything environment-critical. A missing value should stop the deploy with a clear error instead of producing a half-working stack.',
 'Silent wrong defaults are the hardest class of bug to find because nothing errors. Prefer a loud failure at deploy time over a quiet misconfiguration in production.',
 'active');
