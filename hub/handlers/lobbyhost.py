#!/usr/bin/env python3
"""
# 20204018  handlers.lobbyhost — the dashboard host, and the route INTO a server

    GET  /            on dashboard.<zone>   the lobby page, not the hub app
    GET  /s/<id>/*                          route into that server
    POST /s/<id>/*                          refused, and says which seam refused it

THE MISTAKE THIS FILE UNDOES. A "Fleet" view was added inside app.html as one
more pane. That made picking a server a SELECTION: the list changed, the origin
did not, and every other pane in that app still described the box the browser
was talking to. So the operator read a summary of ksgcohub inside fks-services'
control room and believed they were operating ksgcohub.

The correction is structural, not cosmetic:

    dashboard.<zone>/           a STANDALONE page (lobby.html). Cards only.
    dashboard.<zone>/s/<id>/    that server's own hub UI, served through here.

You do not read about a server. You go to it. Everything below exists to make
the second line true, and the honest limits of how true it currently is are
written down rather than smoothed over.

WHY THE LOBBY PAGE IS CHOSEN BY HOST AND NOT BY PATH. handlers/identity.py
already decides on Host before anything else, because the apex is public and a
request that arrived there must never fall through to the app. The same
reasoning applies here in reverse: lobby.html must be unreachable by path on a
node hostname, because a node hostname is service-token-only and a human-shaped
page on it is a page that invites a human policy onto it -- which is exactly
what the FlareVault login-flow spec forbids. No route entry names lobby.html.
The only way to it is arriving at a dashboard host, and identity.serve_app
makes that call.

CONSTITUTION Law IV -- report, never repair. A node that will not answer
produces a finding, its HTTP status and the command to check it. There is no
retry, no cache, and above all no fallback to the LOCAL box's data: answering
/s/<remote>/api/containers from this machine would put fks-services' containers
under a card labelled ksgcohub, which is the worst bug a fleet UI can have.

CONSTITUTION Law V -- credentials are never here. The Cloudflare Access service
token is fetched from kernel.svctoken at call time, sent on one request, and
dropped. It is never cached in this module, never logged, and never reaches a
response body or a browser.

HONEST LIMITS OF THE REMOTE DRILL-IN. Say these out loud, because a route that
half works while looking like it fully works is the reason this file exists.

  THE NODE'S OWN LOGIN GATE IS NOT BRIDGED, and it is the big one. app.html
  asks GET /api/auth/check before it shows anything. That path is not in
  handlers/lobby.py:PROXY_ALLOW, so it is refused and the remote app renders
  its login screen. Opening it would not help: the lobby reaches the node with
  a SERVICE token, so the node has no session for the human to check. Bridging
  that -- one sign-in that both the lobby and every node accept -- is
  FlareVault's single-sign-on half, and inventing it here would mean two
  issuers disagreeing about who someone is. So today /s/<remote>/ gets you the
  real node's real UI at the real prefix, and stops at its door.

  ONLY THE ALLOWLISTED VIEWS ANSWER. PROXY_ALLOW is read-only and enumerated,
  and it is deliberately not duplicated or extended here -- a second list would
  drift, and drift in an allowlist is always permissive. Every other pane of
  the remote app reports remote_path_unsupported.

  NO QUERY STRINGS CROSS. See _remote_path(). Any view needing a parameter is
  therefore unreachable remotely.

  GET ONLY. See refuse_write().

  ONE ZONE. kernel.svctoken.node_url builds flareshub-<label>.<zone> from the
  zone THIS box enrolled into. A cross-zone fleet addresses the wrong hostname
  and fails to resolve; that limit is svctoken's and is stated there too.

  LOCAL IS EXEMPT FROM ALL OF THIS. Central drilling into itself gets its own
  app.html, unmodified, talking to its own API -- a complete, working hub.
"""
import os
import urllib.error
import urllib.parse
import urllib.request
from http.cookies import SimpleCookie

# The prefix every route-into-a-server sits under. One place, because the shim
# injected into proxied HTML has to agree with the router exactly or the app
# silently calls the LOBBY's API while displaying a remote server's name.
PREFIX = '/s/'

# The cookie lobby.html writes the role JWT into. See _claims() for why a
# cookie exists at all when every API path uses a header.
ROLE_COOKIE = 'flare_role'

# Enough for an app shell and a UI module; small enough that this hub cannot be
# used as a general-purpose pipe for whatever a node will hand over.
MAX_BODY = 4 * 1024 * 1024

PROXY_TIMEOUT = 8

# What may be fetched from a remote node through this prefix, beyond the
# read-only API views handlers/lobby.py already allowlists in PROXY_ALLOW.
#
# The document and the UI modules, and nothing else. No images, no fonts, no
# arbitrary static path: the hub serves none of those today, and opening a
# static-file hole through a credential that unlocks every node to save a
# future favicon would be a poor trade.
_DOC_PATHS = ('', '/', '/mobile', '/desktop', '/manifest.json')

_UI_EXT = ('.js', '.mjs', '.css', '.json')


# ── The prefix shim ───────────────────────────────────────────────────────────
#
# EXACTLY WHAT IS REWRITTEN IN A PROXIED HTML BODY, AND WHY EACH ONE.
#
# The node's app.html is served byte-for-byte except for ONE <script> inserted
# immediately after <head>. Nothing else in the body is touched -- no regex
# over the markup, no attribute rewriting, no string replacement in the app's
# own JavaScript. Three problems make that one insertion unavoidable:
#
#  1. EVERY NETWORK CALL IS ROOT-ABSOLUTE. app.html sets
#     `const API = window.location.origin` and then calls `API + '/api/status'`,
#     plus ~20 bare `/api/...` fetches. Under /s/<id>/ those resolve to
#     dashboard.<zone>/api/status -- the LOBBY's own API, which is the central
#     box. The page would render a remote server's name over central's data.
#     That is the failure this whole file exists to prevent, so the shim wraps
#     window.fetch and re-prefixes same-origin /api/ and /ui/ paths.
#     A <base href> cannot do this: base only affects RELATIVE urls, and every
#     one of these is root-absolute.
#     This covers 100% of the app's traffic only because app.html uses no
#     XMLHttpRequest, no WebSocket and no EventSource. Verified; if any of the
#     three is ever added, it escapes this shim and must be added to it.
#
#  2. WRITES MUST NOT SILENTLY GO SOMEWHERE ELSE. The proxy is GET-only (see
#     refuse_write). Without the shim, a POST from the proxied page would leave
#     the prefix and hit the LOBBY's own /api/, i.e. it would restart a
#     container on central while the operator was looking at a remote node. The
#     shim answers non-GET locally with a 501 naming the layer-3 seam, so the
#     app shows a refusal instead of performing the action on the wrong machine.
#
#  3. THE SERVICE WORKER WOULD ESCAPE THE PREFIX. ui/notify.js calls
#     navigator.serviceWorker.register('/sw.js', {scope:'/'}). Registered from
#     a drill-in, that installs a worker controlling the ENTIRE lobby origin --
#     including the lobby page itself -- with a cache fallback. The shim makes
#     register() reject inside a drill-in. Notifications are lost there; the
#     lobby origin staying uncontrolled is worth more.
#
# The shim also draws a small fixed banner, because a page that looks exactly
# like the local hub while being a partially-proxied remote node is a page that
# will be misread. It says which machine this is and what does not work.
_SHIM = """<script data-flare-lobby-shim="1">
/* Injected by handlers/lobbyhost.py. Not part of the node's app.
   See the comment above _SHIM in that file for why each piece is here. */
(function () {
  var P = "__PREFIX__";
  var NAME = "__NAME__";
  window.__FLARE_LOBBY_PREFIX = P;

  function reprefix(u) {
    try {
      var a = new URL(u, window.location.href);
      if (a.origin !== window.location.origin) { return u; }   /* external: untouched */
      var p = a.pathname;
      if (p.indexOf(P + "/") === 0 || p === P) { return u; }   /* already prefixed */
      if (p.indexOf("/api/") === 0 || p === "/api" ||
          p.indexOf("/ui/") === 0 || p === "/manifest.json") {
        a.pathname = P + p;
        return a.toString();
      }
      return u;
    } catch (e) { return u; }
  }

  var _f = window.fetch.bind(window);
  window.fetch = function (input, init) {
    var m = ((init && init.method) ||
             (input && input.method) || "GET").toUpperCase();
    if (m !== "GET" && m !== "HEAD") {
      /* Refused HERE rather than at the network, so the write cannot land on
         the lobby's own box by escaping the prefix. */
      return Promise.resolve(new Response(JSON.stringify({
        ok: false,
        error: "write_across_nodes_refused",
        owner: "FlareVault",
        detail: "Writes do not cross nodes. Layer 3 step-up (PIN / TOTP) is " +
                "FlareVault's, and until it exists this drill-in is read-only."
      }), { status: 501, headers: { "Content-Type": "application/json" } }));
    }
    if (typeof input === "string" || input instanceof URL) {
      return _f(reprefix(String(input)), init);
    }
    if (typeof Request !== "undefined" && input instanceof Request) {
      return _f(new Request(reprefix(input.url), {
        method: input.method, headers: input.headers,
        credentials: input.credentials, mode: input.mode,
        cache: input.cache, redirect: input.redirect
      }), init);
    }
    return _f(input, init);
  };

  try {
    Object.defineProperty(navigator.serviceWorker, "register", {
      configurable: true,
      value: function () {
        return Promise.reject(new Error(
          "service worker registration is disabled inside a lobby drill-in"));
      }
    });
  } catch (e) { /* no serviceWorker here at all is the same outcome */ }

  function banner() {
    var d = document.createElement("div");
    d.setAttribute("role", "status");
    d.style.cssText = "position:fixed;right:10px;bottom:10px;z-index:2147483647;" +
      "max-width:300px;padding:8px 11px;border-radius:8px;border:1px solid #f78166;" +
      "background:#161b22;color:#e6edf3;font:11px/1.5 ui-sans-serif,system-ui," +
      "sans-serif;box-shadow:0 2px 10px rgba(0,0,0,.4)";
    d.innerHTML = '<b>Routed into ' + NAME + '</b><br>' +
      'Through the lobby, over a service token. Read-only: writes are the ' +
      'layer-3 seam FlareVault owns, views this hub does not proxy report ' +
      '<code>remote_path_unsupported</code>, and this node\\'s own login gate ' +
      'is not bridged &mdash; the lobby holds the credential, you do not.' +
      '<br><a href="/" style="color:#f78166">Back to the fleet</a>';
    document.body.appendChild(d);
  }
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", banner);
  } else { banner(); }
})();
</script>"""


# 20318704  _finding — one shape for every refusal this module makes
def _finding(handler, status, error, fix, **extra):
    """Report, never repair. Every non-answer from this file carries what went
    wrong and the next command, because 'the drill-in is broken' costs an
    evening and 'the node rejected the service token' costs five minutes.
    """
    out = {'ok': False, 'error': error, 'fix': fix}
    out.update(extra)
    handler.send_json(out, status)


# 20318705  _claims — the caller's verified role, header or cookie
def _claims(handler):
    """Returns (claims, reason) from handlers.lobby._identity -- the SINGLE
    verifier. Nothing here decides who anybody is.

    The one thing this adds is a CARRIER. lobby._identity reads
    `Authorization: Bearer` or `X-Flare-Token`, which is right for an API that
    is always called by script. But arriving at /s/<id>/ is a top-level
    NAVIGATION -- the operator clicked a card -- and a navigation carries no
    headers at all. Without a second carrier every drill-in is a 401 and the
    route is decorative.

    So lobby.html also writes the role JWT to a cookie scoped Path=/s/,
    SameSite=Strict, and when no header is present that cookie is promoted into
    an Authorization header before _identity runs. The token is verified by the
    same code, with the same fail-closed behaviour; only the envelope differs.

    A cookie-borne credential is only safe on a route that changes nothing.
    This one is GET-only and refuse_write() holds that line -- if a write ever
    appears under this prefix, this cookie becomes a CSRF hole on that day.
    """
    from handlers import lobby as _lobby   # noqa: PLC0415

    has_header = bool((handler.headers.get('X-Flare-Token', '') or '').strip())
    if not has_header:
        auth = (handler.headers.get('Authorization', '') or '').strip()
        has_header = auth[:7].lower() == 'bearer '

    if not has_header:
        try:
            jar = SimpleCookie()
            jar.load(handler.headers.get('Cookie', '') or '')
            morsel = jar.get(ROLE_COOKIE)
            tok = urllib.parse.unquote(morsel.value).strip() if morsel else ''
            if tok:
                # Appended, not assigned: HTTPMessage has no replace. _identity
                # reads the first Authorization header, and we only get here
                # when there was none.
                handler.headers['Authorization'] = 'Bearer ' + tok
        except Exception:
            # A malformed Cookie header is 'no identity', not a stack trace in
            # the one route the operator uses to reach a machine.
            pass

    return _lobby._identity(handler)


# 20318706  _split — the node id and the path remaining after the prefix
def _split(path):
    """/s/fvn_685a59/api/status -> ('fvn_685a59', '/api/status').

    Returns ('', '') for a bare /s/. kernel/router.resolve matches on the
    longest LITERAL prefix and the id sits in the middle, so this split has to
    happen here -- the same split handlers/lobby.py:_target makes, for the same
    reason. A missing id is a bad request, not an exception.

    The query string is dropped on purpose; see _remote_path().
    """
    p = path.split('?', 1)[0]
    if not p.startswith(PREFIX):
        return '', ''
    tail = p[len(PREFIX):]
    if '/' not in tail:
        return tail.strip(), ''
    node_id, rest = tail.split('/', 1)
    return node_id.strip(), '/' + rest


# 20318707  _remote_path — what may be fetched from a node, and nothing else
def _remote_path(rest):
    """Returns (node_path, kind) or (None, reason).

    AN ALLOWLIST, NOT SANITISATION. This hub holds a credential that opens
    EVERY node. Forwarding a caller-supplied path with it is the textbook
    confused deputy: the browser cannot reach a node, but it can ask the lobby
    to. So a path is either one this function recognises or it is refused --
    there is no cleaning step that turns an unknown path into an allowed one.

    Three kinds are allowed:
      doc   the app shell itself
      ui    a UI module, by extension, with no directory traversal
      api   a read-only view, and ONLY the ones handlers/lobby.py already
            allowlists in PROXY_ALLOW. That set is the single decision about
            what this credential may reach; a second list here would drift
            from it and the drift would always be in the permissive direction.

    QUERY STRINGS ARE DROPPED, not forwarded. PROXY_ALLOW was written for
    parameterless views, and a forwarded parameter is the part of a URL most
    likely to select a file or a target. The cost is real and named in the
    module report: any view of a remote node that needs a parameter does not
    work through this prefix.
    """
    from handlers.lobby import PROXY_ALLOW   # noqa: PLC0415

    rest = (rest or '').split('?', 1)[0]
    if '..' in rest or '//' in rest:
        return None, 'path_traversal_refused'
    if rest in _DOC_PATHS:
        return (rest or '/'), 'doc'
    if rest.startswith('/ui/'):
        # By EXTENSION, the same rule handlers/identity.py:serve_ui_asset uses
        # at the other end. Nesting is allowed because ui/views/ exists; the
        # '..' refusal above is what keeps that from being a traversal.
        name = rest[len('/ui/'):]
        if not name or not name.lower().endswith(_UI_EXT):
            return None, 'remote_path_unsupported'
        return rest, 'ui'
    if rest.startswith('/api/'):
        sub = rest[len('/api/'):].strip('/')
        if sub in PROXY_ALLOW:
            return '/api/' + sub, 'api'
        return None, 'remote_path_unsupported'
    return None, 'remote_path_unsupported'


# 20318708  _fetch_node — one authenticated GET to one node
def _fetch_node(node_id, node_path):
    """Returns (status, content_type, body_bytes, None) or (None, None, None,
    finding).

    kernel.svctoken owns the URL and the credential; this asks for both at call
    time and keeps neither. The guard chain below is deliberately the same one
    handlers/lobby.py:_proxy_node runs, because the failure modes are the same
    and an operator should not have to learn two different vocabularies for
    'the node did not answer'.

    headers_for() returning {} means DO NOT CALL -- not 'call it without auth'.
    An unauthenticated request gets a 302 to a Cloudflare Access login this
    process can never complete, which arrives back looking like a network
    fault, and the evening goes on the tunnel while the real answer is that no
    service token is stored.
    """
    try:
        from kernel import svctoken   # noqa: PLC0415
    except Exception as e:
        return None, None, None, {
            'error': 'svctoken_unavailable', 'detail': str(e),
            'fix': 'kernel/svctoken.py is not deployed on this host — check '
                   'the deploy, then restart the hub'}
    try:
        base = (svctoken.node_url(node_id) or '').rstrip('/')
        headers = svctoken.headers_for(node_id) or {}
    except Exception as e:
        return None, None, None, {
            'error': 'svctoken_failed', 'detail': str(e),
            'fix': 'the service token for this node could not be resolved — '
                   'check its enrolment with FlareVault'}
    if not base:
        return None, None, None, {
            'error': 'node_url_unknown',
            'fix': 'FlareVault has no hostname recorded for this node'}
    if not headers:
        return None, None, None, {
            'error': 'no_service_token',
            'fix': 'no usable Access service token on this host — check '
                   '`python3 -c "from kernel import svctoken; '
                   'print(svctoken.status())"`'}
    if not base.lower().startswith('https://'):
        return None, None, None, {
            'error': 'insecure_node_url',
            'fix': 'node_url must be https — refusing to send a service token '
                   'over plaintext'}

    out = dict(headers)
    # Identity encoding, because this function hands the bytes straight on and
    # does not decompress. USER_AGENT already comes from svctoken and is NOT
    # optional: Cloudflare's Browser Integrity Check sits in front of Access
    # and answers 403/1010 to anything that looks automated, which reads
    # exactly like Access refusing the credential.
    out['Accept-Encoding'] = 'identity'
    req = urllib.request.Request(base + node_path, headers=out)
    try:
        with urllib.request.urlopen(req, timeout=PROXY_TIMEOUT) as r:
            landed = urllib.parse.urlsplit(r.geturl()).netloc.lower()
            if landed != urllib.parse.urlsplit(base).netloc.lower():
                # urllib follows redirects, so an Access login page would
                # otherwise arrive here as a perfectly healthy 200 of HTML and
                # be served to the operator as if it were the node.
                return None, None, None, {
                    'error': 'redirected_off_node', 'landed_on': landed,
                    'fix': 'the request was redirected away from the node, '
                           'which usually means Access did not accept the '
                           'service token — re-issue it from FlareVault'}
            body = r.read(MAX_BODY + 1)
            if len(body) > MAX_BODY:
                return None, None, None, {
                    'error': 'node_response_too_large', 'limit': MAX_BODY,
                    'fix': 'the lobby will not relay a body this large; open '
                           'this view on the node itself'}
            return (r.status, r.headers.get('Content-Type', '') or '',
                    body, None)
    except urllib.error.HTTPError as e:
        # The NODE's refusal, passed back as the node's. A 401 from the node is
        # a fact about the node, and reinterpreting it here as a lobby error
        # sends the reader to the wrong system.
        try:
            body = e.read(MAX_BODY)
        except Exception:
            body = b''
        return (e.code, (e.headers.get('Content-Type', '') if e.headers else ''),
                body, None)
    except Exception as e:
        return None, None, None, {
            'error': 'node_unreachable', 'detail': str(e),
            'fix': 'the node did not answer within %ss — check its tunnel and '
                   'its hub service' % PROXY_TIMEOUT}


# 20318709  _send_bytes — relay a node's body without relaying its session
def _send_bytes(handler, status, ctype, body):
    """Set-Cookie and every other response header from the node are DROPPED.

    Only the status, the content type and the bytes cross. A node's cookie set
    on this origin would sit alongside the lobby's own and there is no reading
    of that which ends well; hop-by-hop headers (Connection, Transfer-Encoding)
    would be lies about a connection this hub is not making.
    """
    handler.send_response(status or 200)
    handler.send_header('Content-Type', ctype or 'application/octet-stream')
    handler.send_header('Content-Length', str(len(body)))
    # A proxied page is authenticated and machine-specific. A shared cache
    # holding it would serve one server's console to the next person through.
    handler.send_header('Cache-Control', 'no-store')
    handler.end_headers()
    handler.wfile.write(body)


# 20318710  _inject — put the shim in, or say why the page cannot be served
def _inject(body, prefix, name):
    """Returns (html_bytes, None) or (None, reason).

    The ONLY edit made to a proxied HTML body: one <script> immediately after
    <head>. If there is no <head> to anchor to, this returns a reason and the
    caller serves a finding -- a page whose shim did not land would send every
    one of its API calls to the lobby's own box while displaying the remote
    server's name, and a half-working page that lies about which machine you
    are on is worse than a refusal that explains itself.
    """
    try:
        text = body.decode('utf-8')
    except Exception:
        return None, 'node_html_not_utf8'
    low = text.lower()
    i = low.find('<head>')
    if i < 0:
        return None, 'node_html_has_no_head'
    # The name is operator-supplied text going into a JS string literal and an
    # innerHTML. Keep only characters that cannot end either one; a server
    # called `"><script>` must not become a script on the lobby's origin.
    safe = ''.join(c for c in str(name) if c.isalnum() or c in ' ._-')[:60]
    shim = _SHIM.replace('__PREFIX__', prefix).replace('__NAME__', safe or 'this server')
    at = i + len('<head>')
    return (text[:at] + shim + text[at:]).encode('utf-8'), None


# 20318701  GET / on a dashboard host — the lobby page
def serve_lobby(handler, path, params):
    """# 20318701  serve the standalone lobby page

    Called by handlers/identity.py:serve_app once it has decided, on Host, that
    this request arrived at a dashboard hostname. It is NOT wired to a route of
    its own: giving lobby.html a path would make it reachable on every hostname
    this origin answers to, including the node hostnames, and a human-shaped
    page on a service-token-only host invites a human policy onto it.

    THE PAGE DOES NOT FETCH. It used to call /api/door and then /api/lobby,
    and on the apex that breaks in a way worth writing down.

    /fleet and /api are SEPARATE Cloudflare Access applications, so they have
    separate sessions. Signing in for /fleet does not authenticate /api. Access
    answers the fetch with a 302 to its login on kgco.cloudflareaccess.com --
    a cross-ORIGIN redirect, which fetch() cannot follow, so the browser
    reports it as a CORS failure with no Access-Control-Allow-Origin. The
    console blames CORS; the cause is two apps and one session.

    A NAVIGATION survives that redirect fine -- which is why clicking into a
    server still works and only the page's own fetches died.

    So the server injects what the page needs. It already holds the answer at
    render time: this request came through Access, so there is an identity, and
    the lobby data is one local call away. No token round trip, no second app,
    nothing to be refused.

    The injected data is exactly what /api/lobby would have returned for THIS
    identity -- same function, same role scoping. A client still cannot see a
    server they do not hold, because the same _visible() decides it.

    Cache-Control is no-store as a result: this page now carries fleet data,
    so it must not sit in a proxy or a back-button cache.
    """
    fpath = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'lobby.html')
    try:
        with open(fpath, 'rb') as f:
            body = f.read()
    except FileNotFoundError:
        handler.send_response(404)
        handler.end_headers()
        return

    # Build the same payload /api/lobby would have produced, and hand it to the
    # page as a global. Failure is reported, never papered over: the page falls
    # back to fetching, which at least produces a diagnosable error rather than
    # an empty screen.
    boot = 'null'
    try:
        import json as _json                      # noqa: PLC0415
        from handlers import lobby as _lobby      # noqa: PLC0415

        class _Cap(object):
            """Catches the handler's send_json instead of writing a response."""
            def __init__(self, h):
                self.headers = h.headers
                self.client_address = getattr(h, 'client_address', ('', 0))
                self.path = getattr(h, 'path', '/')
                self.payload = None
            def send_json(self, data, status=200):
                self.payload = (status, data)

        cap = _Cap(handler)
        _lobby.get_lobby(cap, '/api/lobby', {})
        if cap.payload and cap.payload[0] == 200:
            boot = _json.dumps(cap.payload[1])
    except Exception:
        boot = 'null'

    tag = ('<script>window.__LOBBY__ = ' + boot + ';</script>').encode('utf-8')
    # After <head> so the page's own script, which runs later, can read it.
    if b'<head>' in body:
        body = body.replace(b'<head>', b'<head>' + tag, 1)
    else:
        body = tag + body
    handler.send_response(200)
    handler.send_header('Content-Type', 'text/html; charset=utf-8')
    handler.send_header('Content-Length', str(len(body)))
    # The shell is public-shaped; everything it shows arrives over an
    # authenticated fetch. no-cache rather than a max-age so a deploy is picked
    # up on the next load, which matters for the page an operator lands on.
    handler.send_header('Cache-Control', 'no-store')
    handler.end_headers()
    handler.wfile.write(body)


# 20318702  GET /s/<id>/* — route the operator INTO that server
def route_into_server(handler, path, params):
    """# 20318702  the route into a server

    THIS IS THE POINT OF THE WHOLE THING. Everything else is a list.

    Order of checks, and none of them may be reordered:

      1. central only. A node has no fleet, so this route on a node is 409 and
         names where the lobby lives.
      2. a verified role. No identity, no answer -- and the 401 names the door.
      3. VISIBILITY BEFORE EXISTENCE. An id this role may not see and an id
         that was never minted return the same 404. Anything that told them
         apart would answer the one question a client must never be able to
         ask.
      4. only then, local or remote.

    LOCAL IS SERVED LOCALLY, BYTE FOR BYTE. Central drilling into itself reads
    its own files; it does not loop through its own Cloudflare tunnel and its
    own service token to describe the machine it is running on. That would make
    the box unable to show itself whenever its own tunnel was down -- precisely
    when an operator needs it.

    The local page is served UNMODIFIED, with no shim, because it needs none:
    the lobby origin IS that server, so app.html's root-absolute /api/ and /ui/
    calls already land on exactly the right machine. Rewriting them would add a
    hop and a class of bug for no gain.
    """
    from kernel import identity as _id      # noqa: PLC0415
    from handlers import lobby as _lobby    # noqa: PLC0415

    if not _id.is_central():
        _lobby._not_central(handler)
        return

    claims, reason = _claims(handler)
    if claims is None:
        _lobby._deny(handler, reason)
        return

    node_id, rest = _split(path)
    if (not node_id or not _lobby._ID_OK.match(node_id)
            or node_id not in _lobby._visible(claims)):
        # Same answer for malformed, unknown and not-yours. See lobby.py.
        handler.send_json({'ok': False, 'error': 'no_such_server'}, 404)
        return

    if node_id == _id.server_id():
        _serve_local(handler, rest)
        return

    node_path, kind = _remote_path(rest)
    if node_path is None:
        from handlers.lobby import PROXY_ALLOW   # noqa: PLC0415
        _finding(handler, 403, kind,
                 'the lobby relays a node\'s app shell, its UI modules and the '
                 'read-only views it publishes. Anything else is refused: this '
                 'hub holds a service token that opens every node, and '
                 'forwarding an arbitrary path with it is a confused deputy.',
                 path=rest, allowed_api=sorted(PROXY_ALLOW))
        return

    status, ctype, body, err = _fetch_node(node_id, node_path)
    if err is not None:
        # Report, never repair. No retry, and no falling back to this box's own
        # data -- serving central's containers under a remote server's name is
        # the failure this file was written to make impossible.
        _finding(handler, 502, err.get('error', 'node_unreachable'),
                 err.get('fix', ''), server_id=node_id,
                 detail=err.get('detail'), **{k: v for k, v in err.items()
                                              if k not in ('error', 'fix', 'detail')})
        return

    if kind == 'doc' and 'html' in (ctype or '').lower():
        rec = {}
        try:
            from kernel import fleet as _fleet   # noqa: PLC0415
            rec = _fleet.fleet().get(node_id) or {}
        except Exception:
            rec = {}
        html, why = _inject(body, PREFIX + node_id, rec.get('name') or node_id)
        if html is None:
            _finding(handler, 502, why,
                     'the node returned a page this hub cannot safely serve '
                     'under a prefix. Serving it unmodified would send its API '
                     'calls to the lobby\'s own box while showing this '
                     'server\'s name, so it is refused instead.',
                     server_id=node_id)
            return
        _send_bytes(handler, status, 'text/html; charset=utf-8', html)
        return

    _send_bytes(handler, status, ctype, body)


# 20318711  _serve_local — central describing itself, without a tunnel hop
def _serve_local(handler, rest):
    """The app shell off disk for the document paths, and a finding for
    anything else.

    /s/<self>/api/... is never requested in practice, because the local page is
    served without the prefix shim and therefore calls /api/... directly. If it
    IS requested, saying so beats quietly answering -- the caller has a
    same-origin route to the real endpoint and should use it, and a second path
    to the same data is a second place for an auth check to be forgotten.
    """
    from handlers import identity as _identity   # noqa: PLC0415

    if rest not in _DOC_PATHS:
        _finding(handler, 400, 'self_is_local',
                 'this is the box you are already talking to — call %s '
                 'directly on this origin' % (rest or '/'))
        return

    ua = handler.headers.get('User-Agent', '') or ''
    is_mobile = any(x in ua for x in ('Mobile', 'Android', 'iPhone', 'iPad',
                                      'iPod', 'BlackBerry', 'Windows Phone'))
    fpath = _identity.MOBILE_PATH if (rest == '/mobile' or is_mobile) \
        else _identity.APP_PATH
    try:
        with open(fpath, 'rb') as f:
            body = f.read()
    except FileNotFoundError:
        handler.send_response(404)
        handler.end_headers()
        return
    _send_bytes(handler, 200, 'text/html; charset=utf-8', body)


# 20318703  POST /s/<id>/* — refused, naming the seam that refuses it
def refuse_write(handler, path, params, body):
    """# 20318703  writes do not cross nodes

    A 404 here would read as "that route was removed" and send the reader
    looking for a deploy problem. This refusal names the seam instead: layer 3
    is a step-up proof (PIN / TOTP) that FlareVault owns and has not built, and
    a lobby that performed a destructive action on a remote box without it
    would make the whole ladder decorative.

    The visibility check runs FIRST and the 501 sits BEHIND the 404, for the
    same reason it does in handlers/lobby.py: answering 'not implemented' to
    someone who may not see this server would confirm the server exists.
    """
    from kernel import identity as _id      # noqa: PLC0415
    from handlers import lobby as _lobby    # noqa: PLC0415

    if not _id.is_central():
        _lobby._not_central(handler)
        return

    claims, reason = _claims(handler)
    if claims is None:
        _lobby._deny(handler, reason)
        return

    node_id, rest = _split(path)
    if (not node_id or not _lobby._ID_OK.match(node_id)
            or node_id not in _lobby._visible(claims)):
        handler.send_json({'ok': False, 'error': 'no_such_server'}, 404)
        return

    _finding(handler, 501, 'write_across_nodes_refused',
             'nothing here will perform this write. Layer 3 (PIN / TOTP '
             'step-up) is FlareVault\'s to implement; ServerHub provides the '
             'seam at POST /api/lobby/server/<id>/action and performs no '
             'destructive action without that proof.',
             server_id=node_id, path=rest, owner='FlareVault', needs_layer=3)
