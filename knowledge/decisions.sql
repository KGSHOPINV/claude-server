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
