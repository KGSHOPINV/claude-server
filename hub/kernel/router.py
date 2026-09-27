#!/usr/bin/env python3
"""
# 20200006  kernel.router — dispatch table for all hub routes
Hub kernel: request routing layer.
Auth is enforced here at dispatch time, not per-handler.
Gate levels: 0=public 1=user 2=admin 3=totp
"""

# Route entry shape:
# {
#   "code":    "20302701",        # telescope code
#   "method":  "GET",             # or "POST"
#   "path":    "/api/status",     # exact path, or prefix ending in *
#   "prefix":  False,             # True if path is a prefix match
#   "gate":    1,                 # minimum gate level required (0=public)
#   "handler": "handle_status",   # function name in handlers/ (phase 2)
#   "module":  "status",          # which handler file owns this
# }

# ── Namespace reservations ───────────────────────────────────────────────────
# Telescope module numbers and URL prefixes are a shared namespace across the
# federation. Reserving them costs nothing now; discovering a collision after
# both sides have shipped costs a migration.
#
#   00-19   ServerHub.    In use: 00 kernel, 01 identity, 02 status,
#                         03 federation, 04 config, 05 users, 06 events,
#                         07 ai, 08 tunnel, 09 proxy, 10 ops, 11 node,
#                         12 mesh.  Free: 13-19.
#   20-29   FlareVault.   Endpoints the hub implements on FV's behalf.
#                         None yet — reserved so FV can claim without asking.
#   30-39   Metaforge.    Same arrangement.
#   40-49   local.        Per-deployment, never upstreamed.
#
# URL prefixes:
#   /api/mesh/*      shared contract, changes need both sides to agree
#   /api/node        this node describing itself — ServerHub owns it
#   /api/admit       boundaries for a project landing here — ServerHub owns it
#   /api/vault/*     RESERVED AND DELIBERATELY UNIMPLEMENTED. Doctrine: the hub
#                    stores pointers, never credentials. If this prefix ever
#                    appears here, something has gone wrong.
#
ROUTES = [
    # ── Identity ─────────────────────────────────────────────────────────────
    {"code": "20301701", "method": "GET",  "path": "/",                           "prefix": False, "gate": 0, "handler": "serve_app",            "module": "identity"},
    {"code": "20301702", "method": "GET",  "path": "/mobile",                     "prefix": False, "gate": 0, "handler": "serve_app",             "module": "identity"},
    {"code": "20301709", "method": "GET",  "path": "/ui/",                       "prefix": True,  "gate": 0, "handler": "serve_ui_asset",      "module": "identity"},
    {"code": "20301708", "method": "GET",  "path": "/desktop",                    "prefix": False, "gate": 0, "handler": "serve_app",             "module": "identity"},
    {"code": "20301703", "method": "GET",  "path": "/manifest.json",              "prefix": False, "gate": 0, "handler": "serve_manifest",         "module": "identity"},
    {"code": "20301704", "method": "GET",  "path": "/sw.js",                      "prefix": False, "gate": 0, "handler": "serve_sw",               "module": "identity"},
    {"code": "20301705", "method": "GET",  "path": "/api/my-ip",                  "prefix": False, "gate": 0, "handler": "get_my_ip",              "module": "identity"},
    {"code": "20301706", "method": "GET",  "path": "/api/identity",               "prefix": False, "gate": 0, "handler": "get_identity",           "module": "identity"},
    {"code": "20301707", "method": "GET",  "path": "/api/access",                 "prefix": False, "gate": 1, "handler": "get_access",             "module": "identity"},

    {"code": "20301710", "method": "GET",  "path": "/api/auth/provider",          "prefix": False, "gate": 0, "handler": "get_auth_provider",    "module": "identity"},

    # ── Status / Docker ───────────────────────────────────────────────────────
    {"code": "20302701", "method": "GET",  "path": "/api/status",                 "prefix": False, "gate": 1, "handler": "get_status",             "module": "status"},
    {"code": "20302702", "method": "GET",  "path": "/api/setup/status",           "prefix": False, "gate": 1, "handler": "get_setup_status",       "module": "status"},
    {"code": "20302703", "method": "GET",  "path": "/api/containers",             "prefix": False, "gate": 1, "handler": "get_containers",         "module": "status"},
    {"code": "20302704", "method": "GET",  "path": "/api/services",               "prefix": False, "gate": 1, "handler": "get_services",           "module": "status"},
    {"code": "20302705", "method": "GET",  "path": "/api/ports",                  "prefix": False, "gate": 1, "handler": "get_ports",              "module": "status"},
    {"code": "20302706", "method": "GET",  "path": "/api/storage",                "prefix": False, "gate": 1, "handler": "get_storage",            "module": "status"},
    {"code": "20302707", "method": "GET",  "path": "/api/docker/images",          "prefix": False, "gate": 1, "handler": "get_docker_images",      "module": "status"},
    {"code": "20302708", "method": "GET",  "path": "/api/docker/volumes",         "prefix": False, "gate": 1, "handler": "get_docker_volumes",     "module": "status"},
    {"code": "20302709", "method": "GET",  "path": "/api/docker/stats",           "prefix": False, "gate": 1, "handler": "get_docker_stats",       "module": "status"},
    {"code": "20302710", "method": "GET",  "path": "/api/docker/diagnostics",     "prefix": False, "gate": 1, "handler": "get_docker_diagnostics", "module": "status"},
    {"code": "20302711", "method": "GET",  "path": "/api/integrations",           "prefix": False, "gate": 1, "handler": "get_integrations",       "module": "status"},
    {"code": "20302712", "method": "GET",  "path": "/api/manifest",               "prefix": False, "gate": 1, "handler": "get_manifest",           "module": "status"},
    {"code": "20302713", "method": "GET",  "path": "/api/receipt",                "prefix": False, "gate": 2, "handler": "get_receipt",            "module": "status"},
    {"code": "20302714", "method": "GET",  "path": "/api/sync",                   "prefix": False, "gate": 1, "handler": "get_sync",               "module": "status"},
    {"code": "20302715", "method": "GET",  "path": "/api/context",                "prefix": False, "gate": 1, "handler": "get_context",            "module": "status"},
    {"code": "20302716", "method": "GET",  "path": "/api/sitemap",                "prefix": False, "gate": 0, "handler": "get_sitemap",            "module": "status"},
    {"code": "20302717", "method": "GET",  "path": "/cutsheet",                   "prefix": False, "gate": 0, "handler": "get_cutsheet",           "module": "status"},
    {"code": "20302718", "method": "POST", "path": "/api/refresh",                "prefix": False, "gate": 1, "handler": "post_refresh",           "module": "status"},
    {"code": "20302719", "method": "POST", "path": "/api/docker/prune",           "prefix": False, "gate": 2, "handler": "post_docker_prune",      "module": "status"},
    {"code": "20302720", "method": "POST", "path": "/api/docker/action/",         "prefix": True,  "gate": 2, "handler": "post_docker_action",     "module": "status"},
    {"code": "20302721", "method": "POST", "path": "/api/ports/ack",              "prefix": False, "gate": 1, "handler": "post_ports_ack",         "module": "status"},

    # ── Node self-description (module 11) ────────────────────────────────────
    {"code": "20311701", "method": "GET",  "path": "/api/node",                   "prefix": False, "gate": 1, "handler": "get_node",              "module": "node"},

    {"code": "20311702", "method": "GET",  "path": "/api/admit",                  "prefix": False, "gate": 1, "handler": "get_admit",            "module": "node"},

    # ── registry (module 13) — what a project talks to ───────────────────────
    # Gate 1: a project must be authenticated to file a claim, but reading the
    # registry is gate 1 too rather than 0 -- who runs what on a machine is not
    # public information.
    {"code": "20313701", "method": "GET",  "path": "/api/registry",               "prefix": False, "gate": 1, "handler": "get_registry",         "module": "registry"},
    {"code": "20313702", "method": "GET",  "path": "/api/registry/",              "prefix": True,  "gate": 1, "handler": "get_registry_project", "module": "registry"},
    {"code": "20313703", "method": "POST", "path": "/api/registry/",              "prefix": True,  "gate": 1, "handler": "post_registry_project","module": "registry"},
    {"code": "20313704", "method": "POST", "path": "/api/ack/",                   "prefix": True,  "gate": 1, "handler": "post_ack",             "module": "registry"},

    # ── Mesh (module 12) — beats ENRICH the register; the zone IS the register
    # Corrected 2026-09-26. This said "hub-and-spoke: nodes report UP, never
    # laterally". Who exists is answered by the zone's flareshub-* records
    # (kernel/fleet.discover), so no box has to be up for the fleet to be
    # visible. These two POSTs still only ever go one way, and a node still
    # never writes another node's state -- that part was the useful half.
    {"code": "20312701", "method": "POST", "path": "/api/heartbeat",              "prefix": False, "gate": 0, "handler": "post_heartbeat",       "module": "mesh"},
    {"code": "20312702", "method": "POST", "path": "/api/mesh/register",          "prefix": False, "gate": 0, "handler": "post_mesh_register",   "module": "mesh"},
    {"code": "20312703", "method": "GET",  "path": "/api/mesh/fleet",             "prefix": False, "gate": 1, "handler": "get_mesh_fleet",       "module": "mesh"},
    # A handler with no route is not a feature, it is a 404 with a telescope
    # code. get_mesh_registry was written, coded 20312709 and documented, and
    # this line was never added -- so the one address that answers "what runs
    # where, and is it the same build" answered 404 on both servers. Verified
    # against ksgcohub on 2026-09-26 before this entry existed.
    {"code": "20312709", "method": "GET",  "path": "/api/mesh/registry",          "prefix": False, "gate": 1, "handler": "get_mesh_registry",    "module": "mesh"},

    # ── The lobby (module 16) — dashboard.<zone>, central mode ───────────────
    # Gate 1 here is a DECLARATION, not the control. A gate level cannot say
    # "this role may see these three servers and must not learn the others
    # exist", so every one of these does its own role check inside. That also
    # survives HUB_ENFORCE_GATES being unset, which it currently is.
    # The connector: a login becomes a role the lobby can read. Layers 1-2
    # only -- 3 and 4 are space FlareVault is holding.
    {"code": "20319701", "method": "GET",  "path": "/api/door",                  "prefix": False, "gate": 1, "handler": "get_door",           "module": "door"},
    {"code": "20316701", "method": "GET",  "path": "/api/lobby",                 "prefix": False, "gate": 1, "handler": "get_lobby",          "module": "lobby"},
    {"code": "20316702", "method": "GET",  "path": "/api/lobby/server/",         "prefix": True,  "gate": 1, "handler": "get_lobby_server",   "module": "lobby"},
    {"code": "20316703", "method": "POST", "path": "/api/lobby/server/",         "prefix": True,  "gate": 2, "handler": "post_lobby_action",  "module": "lobby"},
    {"code": "20316704", "method": "POST", "path": "/api/lobby/vault",           "prefix": False, "gate": 3, "handler": "post_lobby_vault",   "module": "lobby"},

    # ── Route into a server (module 18) — dashboard.<zone>/s/<id>/ ──────────
    # The lobby LISTS; this is where you actually go. GET only: writes do not
    # cross nodes, and the POST entry exists so a write is refused BY NAME
    # rather than 404ing as though the route were gone.
    #
    # serve_lobby has no entry on purpose. A path would make lobby.html
    # reachable on every hostname this origin answers to, including the
    # service-token-only node hostnames. identity.serve_app dispatches to it
    # on Host, the same way the splash does.
    # FlareSHub, the page you land on after the login space. A real route, not
    # a fall-through from serve_app: that one only ever answers /, /mobile and
    # /desktop, so /fleet never reached the host dispatch and 404'd.
    #
    # Gate 0 because Cloudflare Access is scoped to this PATH and has already
    # decided there is a person here. The page itself then fetches /api/door
    # and /api/lobby, both of which do their own checks -- a hostile request
    # that reached this path gets an empty shell and nothing else.
    {"code": "20318701", "method": "GET",  "path": "/fleet",                     "prefix": False, "gate": 0, "handler": "serve_lobby",        "module": "lobbyhost"},
    {"code": "20318704", "method": "GET",  "path": "/flareshub",                 "prefix": False, "gate": 0, "handler": "serve_lobby",        "module": "lobbyhost"},
    {"code": "20318702", "method": "GET",  "path": "/s/",                        "prefix": True,  "gate": 1, "handler": "route_into_server",  "module": "lobbyhost"},
    {"code": "20318703", "method": "POST", "path": "/s/",                        "prefix": True,  "gate": 1, "handler": "refuse_write",       "module": "lobbyhost"},

    # ── The outbox (module 17) — outbound, staged and collected ──────────────
    # Build-order item 1. The hole the eleven-step flow sat over: the intake
    # message left the machine only because a human pasted it.
    #
    # -ack and -address are SIBLINGS, not children of /api/outbox/. A second
    # entry on one prefix can never win the stable sort, and the gates differ:
    # staging speaks FOR the server, a project acting on itself does not.
    {"code": "20317701", "method": "GET",  "path": "/api/outbox",               "prefix": False, "gate": 2, "handler": "get_outbox_board",    "module": "outbox"},
    {"code": "20317703", "method": "POST", "path": "/api/outbox/",              "prefix": True,  "gate": 2, "handler": "post_outbox_stage",   "module": "outbox"},
    {"code": "20317702", "method": "GET",  "path": "/api/outbox/",              "prefix": True,  "gate": 1, "handler": "get_outbox_project",  "module": "outbox"},
    {"code": "20317704", "method": "POST", "path": "/api/outbox-ack/",          "prefix": True,  "gate": 1, "handler": "post_outbox_ack",     "module": "outbox"},
    {"code": "20317705", "method": "POST", "path": "/api/outbox-address/",      "prefix": True,  "gate": 1, "handler": "post_outbox_address", "module": "outbox"},

    # ── Federation ───────────────────────────────────────────────────────────
    {"code": "20303701", "method": "GET",  "path": "/api/federation",             "prefix": False, "gate": 1, "handler": "get_federation",         "module": "federation"},
    {"code": "20303702", "method": "POST", "path": "/api/federation",             "prefix": False, "gate": 1, "handler": "post_federation",        "module": "federation"},
    {"code": "20303703", "method": "POST", "path": "/api/peer/register",          "prefix": False, "gate": 0, "handler": "post_peer_register",     "module": "federation"},

    # ── Config / Vault / Journal ──────────────────────────────────────────────
    {"code": "20304701", "method": "GET",  "path": "/api/vault",                  "prefix": False, "gate": 2, "handler": "get_vault",              "module": "config"},
    {"code": "20304702", "method": "GET",  "path": "/api/issues",                 "prefix": False, "gate": 1, "handler": "get_issues",             "module": "config"},
    {"code": "20304703", "method": "GET",  "path": "/api/journal",                "prefix": False, "gate": 1, "handler": "get_journal",            "module": "config"},
    {"code": "20304704", "method": "GET",  "path": "/api/config",                 "prefix": False, "gate": 1, "handler": "get_config",             "module": "config"},
    {"code": "20304705", "method": "POST", "path": "/api/vault",                  "prefix": False, "gate": 2, "handler": "post_vault",             "module": "config"},
    {"code": "20304706", "method": "POST", "path": "/api/config",                 "prefix": False, "gate": 2, "handler": "post_config",            "module": "config"},
    {"code": "20304707", "method": "POST", "path": "/api/journal",                "prefix": False, "gate": 1, "handler": "post_journal",           "module": "config"},

    # ── Users / Auth / TOTP ───────────────────────────────────────────────────
    {"code": "20305701", "method": "GET",  "path": "/api/auth/check",             "prefix": False, "gate": 0, "handler": "get_auth_check",         "module": "users"},
    {"code": "20305702", "method": "GET",  "path": "/api/users",                  "prefix": False, "gate": 2, "handler": "get_users",              "module": "users"},
    {"code": "20305703", "method": "GET",  "path": "/api/totp/status",            "prefix": False, "gate": 1, "handler": "get_totp_status",        "module": "users"},
    {"code": "20305704", "method": "GET",  "path": "/api/totp/setup",             "prefix": False, "gate": 2, "handler": "get_totp_setup",         "module": "users"},
    {"code": "20305705", "method": "POST", "path": "/api/auth/login",             "prefix": False, "gate": 0, "handler": "post_auth_login",        "module": "users"},
    {"code": "20305706", "method": "POST", "path": "/api/auth/logout",            "prefix": False, "gate": 0, "handler": "post_auth_logout",       "module": "users"},
    {"code": "20305707", "method": "POST", "path": "/api/users",                  "prefix": False, "gate": 2, "handler": "post_users",             "module": "users"},
    {"code": "20305708", "method": "POST", "path": "/api/totp/confirm",           "prefix": False, "gate": 2, "handler": "post_totp_confirm",      "module": "users"},
    {"code": "20305709", "method": "POST", "path": "/api/totp/verify",            "prefix": False, "gate": 0, "handler": "post_totp_verify",       "module": "users"},
    {"code": "20305710", "method": "POST", "path": "/api/totp/disable",           "prefix": False, "gate": 3, "handler": "post_totp_disable",      "module": "users"},

    # ── Events / Incidents / Activity ─────────────────────────────────────────
    {"code": "20306701", "method": "GET",  "path": "/api/incidents",              "prefix": False, "gate": 1, "handler": "get_incidents",          "module": "events"},
    {"code": "20306702", "method": "GET",  "path": "/api/activity",               "prefix": False, "gate": 1, "handler": "get_activity",           "module": "events"},
    {"code": "20306703", "method": "POST", "path": "/api/incidents",              "prefix": False, "gate": 1, "handler": "post_incidents",         "module": "events"},
    {"code": "20306704", "method": "POST", "path": "/api/activity",               "prefix": False, "gate": 1, "handler": "post_activity",          "module": "events"},

    # The notification path. HOLDING is activity_log above; these two are LIVE.
    # Gate 1: a stream of what the server is doing is not public, and this is
    # the same session the page already holds -- no second credential.
    {"code": "20306705", "method": "GET",  "path": "/api/events/stream",          "prefix": False, "gate": 1, "handler": "get_events_stream",    "module": "events_stream"},
    {"code": "20306706", "method": "GET",  "path": "/api/events/since",           "prefix": False, "gate": 1, "handler": "get_events_since",     "module": "events_stream"},
    # Gate 0: it names files and says whether they are there. It returns no
    # event content, so it is safe to ask before you can log in -- which is
    # exactly when you need it, because "notifications are broken" and "I
    # cannot log in" have the same first question.
    {"code": "20306707", "method": "GET",  "path": "/api/events/self",            "prefix": False, "gate": 0, "handler": "get_events_self",      "module": "events_stream"},

    # ── The exchange (module 15) ─────────────────────────────────────────────
    # The entry path already existed: /api/admit, /api/registry, /api/ack. What
    # had no URLs was the ONGOING half -- bulletins, tickets, a project's own
    # log, baselines. It sat in kernel/control.py callable only from a tool on
    # the box, which meant the operator was still carrying every message by
    # hand. That is the thing the exchange exists to stop.
    #
    # Gate 1 for reading and answering: a project holds a session already.
    # Gate 2 to PUBLISH -- that speaks for the server to every project at once.
    # GET /api/bulletins is gate 1 and POST is gate 2, on the same path. That
    # is not an inconsistency: listing is reading, publishing speaks for the
    # server to every project at once. resolve() keys the exact table on
    # (method, path), so the two never see each other.
    {"code": "20315715", "method": "GET",  "path": "/api/bulletins",              "prefix": False, "gate": 1, "handler": "get_all_bulletins",     "module": "exchange"},
    {"code": "20315701", "method": "GET",  "path": "/api/bulletins/",             "prefix": True,  "gate": 1, "handler": "get_bulletins",         "module": "exchange"},
    {"code": "20315704", "method": "POST", "path": "/api/bulletins",              "prefix": False, "gate": 2, "handler": "post_bulletins",        "module": "exchange"},
    # Longest-prefix first: /read and /readers must be tested before the bare
    # /api/bulletin/<n>, or the bare route swallows them. -trail is its own
    # prefix for the same reason -readers is: it does not hang off /bulletin/.
    {"code": "20315703", "method": "POST", "path": "/api/bulletin/",              "prefix": True,  "gate": 1, "handler": "post_bulletin_read",    "module": "exchange"},
    {"code": "20315705", "method": "GET",  "path": "/api/bulletin-readers/",      "prefix": True,  "gate": 1, "handler": "get_bulletin_readers",  "module": "exchange"},
    {"code": "20315717", "method": "GET",  "path": "/api/bulletin-trail/",        "prefix": True,  "gate": 1, "handler": "get_bulletin_trail",    "module": "exchange"},
    {"code": "20315702", "method": "GET",  "path": "/api/bulletin/",              "prefix": True,  "gate": 1, "handler": "get_bulletin",          "module": "exchange"},

    {"code": "20315706", "method": "GET",  "path": "/api/tickets",                "prefix": False, "gate": 1, "handler": "get_tickets",           "module": "exchange"},
    {"code": "20315716", "method": "GET",  "path": "/api/tickets/",               "prefix": True,  "gate": 1, "handler": "get_ticket",            "module": "exchange"},
    {"code": "20315707", "method": "POST", "path": "/api/tickets",                "prefix": False, "gate": 1, "handler": "post_tickets",          "module": "exchange"},

    {"code": "20315708", "method": "GET",  "path": "/api/project-log/",           "prefix": True,  "gate": 1, "handler": "get_project_log",       "module": "exchange"},
    {"code": "20315709", "method": "POST", "path": "/api/project-log/",           "prefix": True,  "gate": 1, "handler": "post_project_log",      "module": "exchange"},

    {"code": "20315710", "method": "GET",  "path": "/api/baselines/",             "prefix": True,  "gate": 1, "handler": "get_baselines",         "module": "exchange"},
    {"code": "20315711", "method": "POST", "path": "/api/baselines/",             "prefix": True,  "gate": 1, "handler": "post_baselines",        "module": "exchange"},

    # The bank. Gate 2 to deposit -- that is handing the server a secret.
    # Collect is gate 1 because a project must be able to fetch its own.
    {"code": "20315712", "method": "GET",  "path": "/api/bank",                   "prefix": False, "gate": 2, "handler": "get_bank",              "module": "exchange"},
    {"code": "20315714", "method": "POST", "path": "/api/bank/collect",           "prefix": False, "gate": 1, "handler": "post_bank_collect",     "module": "exchange"},
    {"code": "20315713", "method": "POST", "path": "/api/bank",                   "prefix": False, "gate": 2, "handler": "post_bank",             "module": "exchange"},

    # ── AI ────────────────────────────────────────────────────────────────────
    {"code": "20307701", "method": "GET",  "path": "/api/ai/config",              "prefix": False, "gate": 1, "handler": "get_ai_config",          "module": "ai"},
    {"code": "20307702", "method": "POST", "path": "/api/ai/chat",                "prefix": False, "gate": 1, "handler": "post_ai_chat",           "module": "ai"},
    {"code": "20307703", "method": "POST", "path": "/api/ai/config",              "prefix": False, "gate": 2, "handler": "post_ai_config",         "module": "ai"},

    # ── Tunnel ────────────────────────────────────────────────────────────────
    {"code": "20308701", "method": "POST", "path": "/api/tunnel/start",           "prefix": False, "gate": 2, "handler": "post_tunnel_start",      "module": "tunnel"},
    {"code": "20308702", "method": "POST", "path": "/api/tunnel/stop",            "prefix": False, "gate": 2, "handler": "post_tunnel_stop",       "module": "tunnel"},

    # ── Proxy / Docs / Files ──────────────────────────────────────────────────
    {"code": "20309701", "method": "GET",  "path": "/proxy/",                     "prefix": True,  "gate": 1, "handler": "get_proxy",              "module": "proxy"},
    {"code": "20309702", "method": "GET",  "path": "/api/docs",                   "prefix": False, "gate": 1, "handler": "get_docs",               "module": "proxy"},
    {"code": "20309703", "method": "GET",  "path": "/api/docs/content",           "prefix": False, "gate": 1, "handler": "get_docs_content",       "module": "proxy"},
    {"code": "20309704", "method": "GET",  "path": "/api/files",                  "prefix": False, "gate": 1, "handler": "get_files",              "module": "proxy"},

    # ── Ops ───────────────────────────────────────────────────────────────────
    {"code": "20310701", "method": "POST", "path": "/api/run",                    "prefix": False, "gate": 3, "handler": "post_run",               "module": "ops"},
    {"code": "20310702", "method": "POST", "path": "/api/update",                 "prefix": False, "gate": 3, "handler": "post_update",            "module": "ops"},
    {"code": "20310703", "method": "POST", "path": "/api/setup/generate-claude-md", "prefix": False, "gate": 3, "handler": "post_setup_generate_claude_md", "module": "ops"},
    {"code": "20310704", "method": "POST", "path": "/api/service/install",        "prefix": False, "gate": 2, "handler": "post_service_install",   "module": "ops"},
]


# Removed here: an earlier `dispatch(method, path) -> dict | None` that did a
# linear scan of ROUTES. It was rebound -- and so made unreachable -- by the
# real `dispatch(handler, method, path, ...)` defined further down this same
# module, and its lookup logic survives as `resolve()` below (same semantics,
# but indexed). No caller ever reached it: the only call site in the repo is
# server.py:_route, which uses the six-argument form.


def routes_by_module() -> dict:
    """Return ROUTES grouped by module name.

    KEPT DESPITE HAVING NO CALLERS. handlers/status.py:get_sitemap
    (GET /api/sitemap) hand-maintains a second, parallel list of every route
    with its description. That list is already drifting from ROUTES. This
    function is the seam for generating the sitemap from the one real table --
    deleting it would remove the only piece of the fix that already exists.
    """
    result = {}
    for r in ROUTES:
        result.setdefault(r["module"], []).append(r)
    return result


# ── Dispatch ──────────────────────────────────────────────────────────────────
# 20200007  kernel.router.dispatch — resolve a request to a handler and call it.
#
# Handler contract:
#   GET   fn(handler, path, params)
#   POST  fn(handler, path, params, body)
# Handlers write the response themselves via handler.send_json / handler.wfile.

import importlib
import os
import threading

# Gate enforcement is OFF by default. The route table declares the target
# posture (52 of 65 routes gated) but the current UI only sends a token on a
# handful of calls, so enforcing here would lock out the app. Shadow mode
# records what WOULD have been denied; flip HUB_ENFORCE_GATES=1 once the UI
# sends X-Hub-Token / X-Gate-Token on every gated call.
ENFORCE_GATES = os.environ.get('HUB_ENFORCE_GATES', '0').lower() not in ('0', 'false', '')

_SHADOW_MAX = 500
_shadow_denials = []
_shadow_lock = threading.Lock()

_handler_cache = {}
_cache_lock = threading.Lock()

_EXACT = {}
_PREFIX = []


def _build_index():
    """Split ROUTES into an exact-match dict and a longest-first prefix list."""
    _EXACT.clear()
    del _PREFIX[:]
    for r in ROUTES:
        if r.get('prefix'):
            _PREFIX.append(r)
        else:
            _EXACT[(r['method'], r['path'])] = r
    _PREFIX.sort(key=lambda r: len(r['path']), reverse=True)


_build_index()


def resolve(method, path):
    """Return the route entry for method+path, or None."""
    r = _EXACT.get((method, path))
    if r is not None:
        return r
    # METHOD MATTERS HERE. This loop used to match on path alone, so a POST to
    # a prefix declared GET dispatched into the GET handler -- which then blew
    # up on arity, because GET handlers take (handler, path, params) and POST
    # handlers take (handler, path, params, body).
    #
    # It went unnoticed because no prefix had both verbs until /api/registry/
    # did. Every prefix route was effectively method-agnostic, including
    # /proxy/ and /api/docker/action/.
    for r in _PREFIX:
        if r['method'] == method and path.startswith(r['path']):
            return r
    return None


def _load(module):
    """Import handlers.<module> once and cache it."""
    with _cache_lock:
        mod = _handler_cache.get(module)
        if mod is None:
            mod = importlib.import_module('handlers.' + module)
            _handler_cache[module] = mod
        return mod


def _gate_allows(handler, route, db_conn_fn):
    """Evaluate the route's declared gate. Returns (allowed, reason).

    LEVEL 2 AND LEVEL 3 ARE DIFFERENT QUESTIONS, and asking gate_check both of
    them conflated them. Per the FlareVault login-flow spec the layers are:

        1  read the fleet          a session
        2  console / containers    an ADMIN ROLE -- what logging in earns you
        3  destructive             a STEP-UP, proved at the moment of use
        4  vault / kill switch     FlareVault's

    Level 2 was being answered by gate_check, which only knows about TOTP. That
    is the wrong instrument: TOTP is the step-up for 3, and requiring it at 2
    would put the whole console behind an authenticator while ALSO -- because
    gate_check returns True when TOTP is unconfigured -- leaving 2 and 3 both
    wide open in exactly the state both live boxes are in. One call answering
    two questions got both wrong at once.

    So 2 asks the session's role and 3 asks for the step-up. This makes
    shadow_report() tell the truth about WHICH gate a route would have failed
    and why, which matters because that report is what anyone reads before
    flipping HUB_ENFORCE_GATES on.

    A caveat this cannot fix from here: the role is only as good as the
    allowlist behind it. check_auth grants CF_ROLE to any identity Cloudflare
    Access approved, and on a box where HUB_CF_EMAILS is unset the test
    short-circuits on the empty list and admits everyone. Level 2 is then
    'anyone Access let in', which is not the same as 'an admin'.
    """
    level = route.get('gate', 0)
    if level <= 0:
        return True, ''
    from kernel.auth import check_auth, gate_check
    sess = check_auth(handler)
    if level >= 1 and sess is None:
        return False, 'no_session'
    if level >= 2 and (sess or {}).get('role') != 'admin':
        return False, 'admin_required'
    if level >= 3 and not gate_check(handler.headers, level, db_conn_fn):
        return False, 'step_up_required'
    return True, ''


def shadow_report():
    """What gate enforcement would have blocked. Diagnostic for the flip."""
    with _shadow_lock:
        return list(_shadow_denials)


# Hosts that are PUBLIC by design and must serve the splash and nothing else.
# Kept in step with handlers/identity.py:SPLASH_HOSTS via the same env var.
SPLASH_HOSTS = [h.strip().lower() for h in os.environ.get(
    'HUB_SPLASH_HOSTS', 'flarevault.dev').split(',') if h.strip()]

# Aliases are NOT splash hosts. They are handled in handlers/identity.py and
# answer 301 without serving anything. www.flarevault.dev was on this list,
# and because SPLASH_BEHIND_LOGIN assumes "Access is scoped to these paths" --
# true for the apex, false for an alias with no apps of its own --
# www.flarevault.dev/api/node served the machine id and LAN address publicly.
REDIRECT_HOSTS = [h.strip().lower() for h in os.environ.get(
    'HUB_REDIRECT_HOSTS', 'www.flarevault.dev').split(',') if h.strip()]
CANONICAL_HOST = os.environ.get('HUB_CANONICAL_HOST', 'flarevault.dev')

# The only paths a splash host may reach. Everything else is 404 — not 403,
# which would confirm the route exists.
SPLASH_ALLOW = ('/', '/mobile', '/desktop', '/manifest.json', '/sw.js')

# Paths on the apex that are NOT the public login space. These reach the API
# because there is a person behind them -- Cloudflare Access is scoped to
# these paths, so a request only arrives here having already signed in.
#
# The guard above still applies to everything else: the apex must never expose
# /api/config and friends, which is what it did for four minutes when a second
# hostname was added without its own Access app.
SPLASH_BEHIND_LOGIN = ('/fleet', '/flareshub', '/s/', '/api/lobby', '/api/door',
                       '/ui/', '/api/auth/check', '/api/node')


# MOVED, 2026-09-27: 202003 25-26 -> 38-39. These two were duplicates of
# kernel/identity.py's `mode` and `issue`, which own a contiguous run at
# 202003 21-27. Two answers to "go to 20200325" is exactly what the address
# space exists to rule out. Reallocated with `hub/tools/atlas.py --codes`.
# 20200338  _splash_only — the apex must never reach the API
def _splash_only(handler, path):
    """Door 1 is a PUBLIC page, so it cannot sit behind Access. That means the
    hostname serving it reaches this origin with no gate in front of it at all.

    Gates here run in shadow mode unless HUB_ENFORCE_GATES is set, so 'gate 1'
    stops nothing. Pointing the apex at this origin without this check would
    publish /api/config, /api/status, /api/containers and the rest to the open
    internet.

    That is not hypothetical. A second hostname was added to this origin
    earlier tonight without an Access app, and https://<that host>/api/config
    returned the hub's configuration to anyone who asked, for about four
    minutes.

    So a splash host gets the splash and the PWA files it needs, and 404 for
    everything else. This holds whether or not gate enforcement is ever
    switched on, because it does not depend on gates.
    """
    try:
        host = (handler.headers.get('Host', '') or '').split(':')[0].lower()
    except Exception:
        return False
    if host not in SPLASH_HOSTS:
        return False
    p = path.split('?')[0]
    if p in SPLASH_ALLOW:
        return False
    if any(p == a or p.startswith(a) for a in SPLASH_BEHIND_LOGIN):
        return False
    return True


# 20200339  _alias_redirect — an alias answers 301 and serves nothing
def _alias_redirect(handler, path):
    """True if this request was answered with a redirect to the canonical host.

    Checked BEFORE the splash guard, because the guard answers 404 and an
    alias should answer 301. A 404 would break www as a usable address; a 301
    makes it work while serving nothing of its own.

    The point is that gating lives in ONE place. An alias that serves needs
    its own Access apps kept in step with the canonical host's, and the one
    that drifts is the one nobody is looking at -- which is precisely how
    www.flarevault.dev/api/node came to serve the machine id and LAN address
    to the open internet while the apex correctly answered 302.
    """
    try:
        host = (handler.headers.get('Host', '') or '').split(':')[0].lower()
    except Exception:
        return False
    if host not in REDIRECT_HOSTS:
        return False
    try:
        handler.send_response(301)
        handler.send_header('Location', 'https://%s%s' % (CANONICAL_HOST, path))
        # Never cached: a cached redirect outlives a decision to change it.
        handler.send_header('Cache-Control', 'no-cache')
        handler.send_header('Content-Length', '0')
        handler.end_headers()
    except Exception:
        pass
    return True


def dispatch(handler, method, path, params=None, body=None, db_conn_fn=None):
    """Route one request. Returns True if handled, False to fall through."""
    if _alias_redirect(handler, path):
        return True
    if _splash_only(handler, path):
        handler.send_response(404)
        handler.end_headers()
        return True
    route = resolve(method, path)
    if route is None:
        return False
    try:
        fn = getattr(_load(route['module']), route['handler'], None)
    except Exception as e:
        handler.send_json({'ok': False, 'error': 'handler_import_failed',
                           'module': route['module'], 'detail': str(e)}, 500)
        return True
    if fn is None:
        return False

    allowed, reason = _gate_allows(handler, route, db_conn_fn)
    if not allowed:
        if ENFORCE_GATES:
            handler.send_json({'error': reason, 'layer': route.get('gate', 0),
                               'code': route['code']}, 403)
            return True
        with _shadow_lock:
            if len(_shadow_denials) < _SHADOW_MAX:
                _shadow_denials.append({'code': route['code'], 'method': method,
                                        'path': path, 'reason': reason})

    if params is None:
        params = {}
    if method == 'POST':
        fn(handler, path, params, body or {})
    else:
        fn(handler, path, params)
    return True
