/* 20404901  ui.data — the one fetch layer, and the only thing that knows
 *            WHICH SERVER a view is looking at.
 *
 * WHY THIS EXISTS
 *   Today every server serves a byte-identical app.html and every one of those
 *   copies only ever talks to its own /api/*. That is not one frontend that
 *   reaches any node; it is N identical frontends each locked to the box that
 *   served it. The spec asks for the other thing:
 *
 *       "One frontend works against any server. Not a UI per node —
 *        the same build talks to whichever node."
 *
 *   A view cannot be bilateral on its own. If each view writes its own
 *   `fetch(API+'/api/ports', {headers:{'X-Hub-Token':HUB_TOKEN}})` — there are
 *   a dozen of those in app.html — then pointing the UI at another node means
 *   editing a dozen call sites, and the one somebody misses silently keeps
 *   reading the local box while its header says otherwise. That is the failure
 *   mode this file exists to make impossible: ONE place decides where a read
 *   goes, so there is one place to get it right.
 *
 * WHAT THE BROWSER MAY AND MAY NOT REACH
 *   The browser must NEVER call a node hostname directly. Per the FlareVault
 *   spec (rule 6, and handlers/lobby.py:_proxy_node), flareshub-<id>.<zone>
 *   refuses humans entirely — a direct call gets a 302 into a Cloudflare Access
 *   login the page can never complete, which arrives back looking like a
 *   network fault. The human is in the LOBBY; the lobby reaches the node with a
 *   SERVICE token on their behalf. So:
 *
 *       own node     ->  /api/<path>                  (hub token / Access header)
 *       other node   ->  /api/lobby/server/<id>       (role JWT; lobby proxies)
 *
 *   There is no third option and this file offers none.
 *
 * LOADED AS A CLASSIC SCRIPT, like registry.js and notify.js, for the same
 * reason: app.html's script block is one enormous global scope and type=module
 * would move it out from under the rest of the page. Publishes one global.
 *
 * HONEST LIMITS — read these before trusting get():
 *   1. The lobby proxies exactly ONE node endpoint: /api/node. There is no
 *      arbitrary cross-node path proxy, and adding one is a Python change this
 *      file is not allowed to make. So get('ports', {server:'fvn_other'}) is
 *      REFUSED with remote_path_unsupported rather than quietly answered from
 *      the local box — a wrong answer that looks right is worse than no answer.
 *   2. Writes do not cross nodes at all. POST /api/lobby/server/<id>/action is
 *      a declared 501 seam: layer 3 step-up is FlareVault's to implement.
 *   3. `self` (this node's own id) is learned from the lobby, not known at
 *      load. Until the lobby answers, "no server named" means "this one".
 */
(function () {
  'use strict';

  /* window.location.origin, not app.html's `const API`. app.html declares API
   * with `const` at the top of its script block, which runs AFTER this file.
   * A cross-script `const`/`let` read before initialisation is a TDZ
   * ReferenceError, not undefined — so borrowing its globals would make this
   * file's behaviour depend on load order. Same reason the token comes out of
   * sessionStorage below instead of off app.html's `let HUB_TOKEN`; that is
   * also what notify.js does, and it is the pattern that has not broken. */
  const ORIGIN = window.location.origin;

  /* ── auth ────────────────────────────────────────────────────────────────
   * Two doors, one rule. Over Tailscale / LAN there is a hub session token in
   * sessionStorage and it must ride every request. Through Cloudflare Access
   * there is NO token to send: identity is the Cf-Access-Authenticated-User-
   * Email header the tunnel adds, which kernel/auth.check_auth already trusts.
   * Inventing a token for that case is what made the page ask for a second
   * login; sending nothing is correct, not a gap. */
  function hubToken() {
    try {
      return sessionStorage.getItem('hub_token') ||
             localStorage.getItem('hub_token') || '';
    } catch (_) { return ''; }      // private mode / blocked storage
  }

  function authHeaders(extra) {
    const h = Object.assign({}, extra || {});
    const t = hubToken();
    if (t) h['X-Hub-Token'] = t;
    return h;
  }

  /* ── 401 is surfaced, never swallowed ────────────────────────────────────
   * The old inline calls did `.then(r=>r.json()).catch(()=>({}))`, so an
   * expired session rendered as an empty view: "you have no servers" instead
   * of "you are not signed in". Those are different facts and the UI must not
   * confuse them. Every refusal comes back as a result object with ok:false
   * and a status, AND fires a window event so the shell can react once rather
   * than every view discovering it separately. */
  function unauthorized(result) {
    try {
      window.dispatchEvent(new CustomEvent('hub:unauthorized', { detail: result }));
    } catch (_) {}
    return result;
  }

  /* One shape for every answer, success or failure:
   *   {ok, status, data, error, detail}
   * A view branches on .ok and never has to know whether the failure was HTTP,
   * JSON, or the network. */
  async function request(url, opts) {
    let r;
    try {
      r = await fetch(url, opts || {});
    } catch (e) {
      return { ok: false, status: 0, error: 'unreachable',
               detail: (e && e.message) || 'fetch failed', data: null };
    }
    let body = null;
    try { body = await r.json(); } catch (_) { body = null; }

    if (r.status === 401) {
      return unauthorized({ ok: false, status: 401,
                            error: (body && body.error) || 'unauthorized',
                            detail: (body && body.detail) || '',
                            door: (body && body.door) || '',
                            data: body });
    }
    if (!r.ok) {
      return { ok: false, status: r.status,
               error: (body && body.error) || ('http_' + r.status),
               detail: (body && (body.detail || body.fix)) || '',
               data: body };
    }
    /* A 200 whose payload says ok:false is still a failure — the hub uses that
     * shape in places. Report it as one rather than handing a view a body it
     * has to re-check. */
    if (body && body.ok === false) {
      return { ok: false, status: r.status, error: body.error || 'refused',
               detail: body.detail || body.fix || '', data: body };
    }
    return { ok: true, status: r.status, error: '', detail: '', data: body };
  }

  /* ── role token cache ────────────────────────────────────────────────────
   * GET /api/door exchanges a session for a short-lived role JWT. The lobby
   * wants it as `Authorization: Bearer <token>`.
   *
   * 30 minute TTL (handlers/door.py: ttl=1800, echoed as expires_in). Minting
   * one per call would be wasteful and, worse, would hide expiry: the symptom
   * of a stale token is a 401 from the lobby that looks exactly like being
   * signed out. So cache it with its own expiry, refresh a minute early to
   * cover clock skew and a slow request, and dedupe in-flight mints — six
   * views mounting at once must produce ONE /api/door call, not six. */
  const SKEW_MS = 60 * 1000;
  let role = null;          // {token, role, via, user, ceiling, expires_at}
  let rolePending = null;   // the in-flight promise, if any

  function roleFresh() {
    return role && role.token && (Date.now() < role.expires_at - SKEW_MS);
  }

  async function roleToken(force) {
    if (!force && roleFresh()) return role.token;
    if (rolePending) return rolePending;

    rolePending = (async () => {
      const res = await request(ORIGIN + '/api/door', { headers: authHeaders() });
      if (!res.ok) {
        /* Do NOT keep a stale token around after a failed refresh. Sending a
         * token we know is dead turns "your session ended" into "the lobby is
         * broken", and somebody spends the evening on the wrong thing. */
        role = null;
        return null;
      }
      const d = res.data || {};
      role = {
        token:      d.token || '',
        role:       d.role || '',
        via:        d.via || '',          // 'cf-access' or 'local' — which door
        user:       d.user || '',
        ceiling:    d.ceiling,
        expires_at: Date.now() + (Number(d.expires_in) || 1800) * 1000,
      };
      return role.token;
    })();

    try { return await rolePending; }
    finally { rolePending = null; }
  }

  /* Whatever the door last told us about the caller. Null before the first
   * successful /api/door — a view that renders a role must handle that, rather
   * than printing "unknown" as if it were a role. */
  function identity() {
    return role ? { user: role.user, role: role.role, via: role.via,
                    ceiling: role.ceiling, expires_at: role.expires_at } : null;
  }

  async function lobbyHeaders() {
    const t = await roleToken();
    const h = authHeaders();
    if (t) h['Authorization'] = 'Bearer ' + t;
    return h;
  }

  /* ── the lobby, cached ───────────────────────────────────────────────────
   * Cached briefly because every view that wants to name its target needs the
   * server rows, and the fleet view refreshing must not mean six round trips.
   * Short TTL on purpose: these rows carry live status, and a stale "healthy"
   * is a lie with a straight face. force:true whenever the operator asked. */
  const LOBBY_TTL_MS = 10 * 1000;
  let lobbyCache = null, lobbyAt = 0, lobbyPending = null;
  let selfId = '';            // learned from the row flagged self:true
  let target = '';            // '' means this node

  async function lobby(opts) {
    const force = !!(opts && opts.force);
    if (!force && lobbyCache && (Date.now() - lobbyAt) < LOBBY_TTL_MS) return lobbyCache;
    if (lobbyPending) return lobbyPending;

    lobbyPending = (async () => {
      let res = await request(ORIGIN + '/api/lobby', { headers: await lobbyHeaders() });

      /* One retry, and only for 401, and only once: the single case worth
       * retrying is a role token that expired between mint and use. Anything
       * else that 401s is genuinely not signed in, and retrying it just turns
       * one honest refusal into two. */
      if (!res.ok && res.status === 401 && role) {
        await roleToken(true);
        res = await request(ORIGIN + '/api/lobby', { headers: await lobbyHeaders() });
      }

      if (res.ok && res.data) {
        const rows = res.data.servers || [];
        const me = rows.find(r => r.self);
        if (me) selfId = me.server_id || '';
        /* If the target we were pointed at is no longer in the lobby, fall
         * back to this node rather than keep asking for a server the API has
         * stopped naming. Holding onto it would let the UI assert a server
         * exists after the lobby stopped saying so. */
        if (target && !rows.some(r => r.server_id === target)) setTarget('');
      }
      lobbyCache = res; lobbyAt = Date.now();
      return res;
    })();

    try { return await lobbyPending; }
    finally { lobbyPending = null; }
  }

  /* ── which server am I looking at ────────────────────────────────────────
   * The question every view has to be able to ask so it can render the same
   * for any node. Returns a row-shaped answer, never null, so a view can print
   * a header before the lobby has answered.
   *
   * `known:false` means exactly that — we have not been told. It does NOT mean
   * the server is down, and a view must not draw it as down. */
  function server() {
    const rows = (lobbyCache && lobbyCache.ok && lobbyCache.data &&
                  lobbyCache.data.servers) || [];
    const id = target || selfId;
    const row = rows.find(r => r.server_id === id);
    if (row) return Object.assign({ known: true, remote: !row.self }, row);
    return { known: false, remote: !!target, self: !target,
             server_id: id || '', name: id || 'this node', status: '' };
  }

  function isSelf(id) { return !id || (!!selfId && id === selfId); }

  const targetListeners = [];
  function setTarget(id) {
    const next = (id && !isSelf(id)) ? String(id) : '';
    if (next === target) return target;
    target = next;
    /* Both channels on purpose: onTarget for views that hold a handle, and a
     * DOM event for anything that would otherwise need one. Listener errors are
     * contained — one view throwing must not stop the rest from re-pointing,
     * which would leave half the UI showing one server and half another. */
    targetListeners.forEach(fn => { try { fn(target); } catch (e) { console.warn('[data] target listener:', e); } });
    try { window.dispatchEvent(new CustomEvent('hub:target', { detail: { server: target } })); } catch (_) {}
    return target;
  }
  function onTarget(fn) {
    if (typeof fn === 'function') targetListeners.push(fn);
    return function off() {
      const i = targetListeners.indexOf(fn);
      if (i >= 0) targetListeners.splice(i, 1);
    };
  }

  /* ── the targeted read ───────────────────────────────────────────────────
   * data.get('ports')                     -> this node
   * data.get('ports', {server:''})        -> this node
   * data.get('node',  {server:'fvn_x'})   -> via the lobby's service-token proxy
   *
   * `path` is written without /api and without a leading slash; both are
   * accepted anyway, because a view author will type one of the three and
   * being strict here buys nothing.
   *
   * THE REMOTE LIMIT, SAID PLAINLY. GET /api/lobby/server/<id> proxies the
   * node's /api/node and nothing else. So a remote read of any other path is
   * refused with error 'remote_path_unsupported' and the drill-in envelope is
   * still returned in .data, so a view can at least keep rendering its header
   * and say what it cannot show. It is NOT silently answered from the local
   * box: that would put another server's name over this server's numbers,
   * which is the single worst bug a bilateral UI can have. */

  function apiUrl(path) {
    let p = String(path == null ? '' : path).replace(/^\/+/, '');
    if (p.indexOf('api/') === 0) p = p.slice(4);
    return { url: ORIGIN + '/api/' + p, path: p.split('?')[0] };
  }

  async function get(path, opts) {
    const o = opts || {};
    const want = (o.server === undefined) ? target : (o.server || '');
    const p = apiUrl(path);

    if (isSelf(want)) {
      return request(p.url, { headers: authHeaders(o.headers) });
    }

    /* ?view= names which of the node's read-only views to fetch. Without it
     * every remote read returned that node's /api/node and the caller had to
     * pretend that was what it asked for. */
    const res = await request(
      ORIGIN + '/api/lobby/server/' + encodeURIComponent(want)
             + '?view=' + encodeURIComponent(p.path),
      { headers: await lobbyHeaders() });

    /* The drill-in's own failures pass through untouched: 404 no_such_server
     * (which is deliberately indistinguishable from "not yours"), and 502 with
     * a `finding` naming what the node or the service token did. Report,
     * never repair — the same rule the Python half follows. */
    if (!res.ok) return res;

    /* The allowlist lives in handlers/lobby.py (PROXY_ALLOW) and the server
     * refuses anything outside it with remote_path_unsupported. A second copy
     * of that list here would be a second source of truth that goes stale --
     * this one already had, claiming the lobby proxies /api/node only, hours
     * after the passthrough landed. Let the server answer. */
    return res;
  }

  /* Writes do not cross nodes. Saying so is the point of this function: a view
   * that calls post() against a remote target gets a refusal naming the seam,
   * instead of a write that lands on the wrong machine. */
  async function post(path, body, opts) {
    const o = opts || {};
    const want = (o.server === undefined) ? target : (o.server || '');
    if (!isSelf(want)) {
      return { ok: false, status: 0, error: 'remote_write_unsupported',
               detail: 'Writes to another node go through POST /api/lobby/server/'
                     + '<id>/action, which is a declared 501 seam — layer 3 '
                     + 'step-up (PIN / TOTP) is FlareVault\'s to implement.',
               data: null };
    }
    const p = apiUrl(path);
    return request(p.url, {
      method: 'POST',
      headers: authHeaders(Object.assign({ 'Content-Type': 'application/json' }, o.headers)),
      body: JSON.stringify(body || {}),
    });
  }

  window.HubData = {
    // reads
    get: get,                  // get(path, {server}) -> {ok,status,data,error,detail}
    post: post,                // post(path, body, {server}) — own node only
    request: request,          // raw wrapper, absolute url, same result shape
    lobby: lobby,              // lobby({force}) -> result; .data is the lobby payload

    // auth
    authHeaders: authHeaders,  // X-Hub-Token when there is one; nothing under Access
    roleToken: roleToken,      // roleToken(force) -> JWT string or null
    identity: identity,        // {user, role, via, ceiling, expires_at} or null

    // targeting
    server: server,            // the row for the server this UI is pointed at
    target: function () { return target; },
    setTarget: setTarget,
    onTarget: onTarget,        // returns an unsubscribe function
    selfId: function () { return selfId; },
    isSelf: isSelf,
  };
})();
