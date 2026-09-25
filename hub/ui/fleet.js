/* 20404902  ui.fleet — the server picker. The view that makes the UI bilateral.
 *
 * WHY THIS EXISTS
 *   Both servers serve byte-identical app.html, and each copy only ever talks
 *   to the box that served it. Nothing in the UI could name another node, let
 *   alone point at one. This is the missing control: it renders the fleet the
 *   LOBBY returned and lets the operator choose which server the rest of the
 *   app is reading. The choice lives in ui/data.js, so every view that asks
 *   "which server am I looking at" gets the same answer.
 *
 * THE RULE THAT SHAPES EVERY LINE BELOW: render only what the lobby returned.
 *   handlers/lobby.py filters BEFORE it counts, for one reason — a client must
 *   never learn that another server exists. Not its id, not its name, not a
 *   count, not an "N others" badge, not a greyed-out row. If this file invents
 *   a placeholder card, a "no other servers configured" hint that implies
 *   there could be, or a total computed any way other than by counting the
 *   rows it was handed, it undoes the whole filter on the client side.
 *   One server returned means one card. Zero means an empty lobby, which is a
 *   correct lobby, not an error and not a misconfiguration.
 *
 * MOBILE LIVES HERE, NOT IN A SECOND FILE (DAG section 4). mountMobile is
 *   exported on this same registry entry. HONEST NOTE: app.html's dispatcher
 *   (mountPaneContent -> HUB_VIEW_MOUNT) resolves `mount` only — it has no
 *   viewport branch yet — so `mount` does the viewport check itself and hands
 *   off. When the shell learns to pick, this keeps working and the branch here
 *   becomes redundant rather than wrong. What matters is that there is no
 *   parallel mobile frontend to keep in sync.
 *
 * NOT IN ui/views/. This file is loaded by an explicit <script> tag in
 *   app.html alongside data.js, so its registry entry carries no `file:true` —
 *   if it did, registry.js's loader would also inject /ui/views/fleet.js and
 *   404. Said here because a missing `file:true` otherwise looks like an
 *   oversight.
 */
(function () {
  'use strict';

  const esc = s => String(s == null ? '' : s)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');

  const V = window.HUB_VIEWS && window.HUB_VIEWS.fleet;
  if (!V) return;            // no registry entry — nothing to mount onto

  const MOBILE_MAX = 900;    // the DAG's breakpoint, not a new one

  /* Status vocabulary comes from the API, not from here. 'self' is the central
   * box describing itself (read now, not remembered); 'healthy' / 'degraded' /
   * 'unreachable' come off the fleet record. Anything else is rendered as
   * itself in the neutral style rather than guessed at — a status this file
   * has not seen before is not automatically bad news. */
  const TONE = {
    self:        { cls: 'up',  dot: 'var(--accent)' },
    healthy:     { cls: 'up',  dot: 'var(--green)'  },
    degraded:    { cls: 'off', dot: 'var(--yellow)' },
    stale:       { cls: 'off', dot: 'var(--yellow)' },
    unreachable: { cls: 'dn',  dot: 'var(--red)'    },
    offline:     { cls: 'dn',  dot: 'var(--red)'    },
  };
  const tone = s => TONE[s] || { cls: 'off', dot: 'var(--muted2)' };

  function ago(iso) {
    if (!iso) return '';
    const t = Date.parse(iso);
    if (isNaN(t)) return String(iso).replace('T', ' ').slice(0, 16);
    const s = Math.max(0, Math.round((Date.now() - t) / 1000));
    if (s < 60)    return s + 's ago';
    if (s < 3600)  return Math.round(s / 60) + 'm ago';
    if (s < 86400) return Math.round(s / 3600) + 'h ago';
    return Math.round(s / 86400) + 'd ago';
  }

  function stub(icon, title, msg) {
    return `<div class="stub-view" style="height:auto;padding:28px 16px">
      <div class="stub-icon">${icon}</div>
      <div class="stub-title">${title}</div>
      <div class="stub-msg">${msg}</div>
    </div>`;
  }

  /* ── the layer strip ─────────────────────────────────────────────────────
   * Rendered from the lobby's own `layer` block, never from a copy of the
   * rules kept here. Two places deciding who may reach layer 3 is one place
   * too many — and the copy is always the one that goes stale.
   *
   * Layers 3 and 4 are shown as PENDING, with FlareVault named, because that
   * is the truth: kernel/router.py runs gate checks in shadow mode and the
   * step-up does not exist. A UI that draws them as available is promising a
   * guard nothing enforces. */
  function layerStrip(layer) {
    if (!layer) return '';
    const max = Number(layer.max) || 0;
    const enforced = layer.enforced || [];
    const pending = layer.pending || {};
    const cells = [1, 2, 3, 4].map(n => {
      const isEnforced = enforced.indexOf(n) >= 0;
      const reach = max >= n;
      const note = pending[String(n)] || '';
      const colour = !isEnforced ? 'var(--yellow)' : (reach ? 'var(--green)' : 'var(--muted2)');
      const label = !isEnforced ? 'pending' : (reach ? 'enforced' : 'above you');
      return `<div title="${esc(note || (label + ' — layer ' + n))}"
        style="flex:1;min-width:0;padding:4px 6px;border:1px solid var(--border);
               border-radius:var(--r);background:var(--panel2)">
        <div style="font-size:9px;font-family:var(--mono);color:${colour};font-weight:700">L${n} · ${esc(label)}</div>
        <div style="font-size:9px;color:var(--muted2);overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${esc(note || '')}</div>
      </div>`;
    }).join('');
    return `<div style="display:flex;gap:4px;padding:6px 10px">${cells}</div>`;
  }

  function doorStrip(doors) {
    if (!doors || !doors.length) return '';
    /* Doors ABOVE the role's ceiling are omitted by the API, not disabled.
     * Listing them as the API gave them keeps that property: a door the
     * caller cannot see does not appear here either. */
    return `<div style="display:flex;flex-wrap:wrap;gap:4px;padding:0 10px 6px">` +
      doors.map(d => `<span class="badge off" title="layer ${esc(d.layer)}">${esc(d.label)}</span>`).join('') +
      `</div>`;
  }

  /* ── one server card ─────────────────────────────────────────────────────
   * Every field here is one the lobby row actually carries (_row in
   * handlers/lobby.py). A field the row omits renders as nothing, not as a
   * dash or a zero: `containers: null` means "not reported", and drawing it as
   * 0 would be a number this UI made up. */
  function card(r, selected) {
    const t = tone(r.status);
    const bits = [];
    if (r.os)                       bits.push(esc(r.os));
    if (r.uptime)                   bits.push('up ' + esc(r.uptime));
    if (r.containers != null)       bits.push(esc(r.containers) + ' containers');
    if (r.projects != null)         bits.push(esc(r.projects) + ' projects');
    if (r.missed_beats)             bits.push(esc(r.missed_beats) + ' missed beats');
    if (r.last_seen)                bits.push('seen ' + esc(ago(r.last_seen)));
    const reach = (r.reachability || []).map(x => esc(x)).join(' · ');

    return `<div class="fleet-card" data-sid="${esc(r.server_id)}" role="button" tabindex="0"
      style="display:flex;gap:8px;align-items:flex-start;padding:9px 10px;cursor:pointer;
             border:1px solid ${selected ? 'var(--accent)' : 'var(--border)'};
             background:${selected ? 'var(--acdim)' : 'var(--panel2)'};
             border-radius:var(--r);margin:0 10px 6px">
      <div style="width:7px;height:7px;border-radius:50%;margin-top:5px;flex-shrink:0;background:${t.dot}"></div>
      <div style="min-width:0;flex:1">
        <div style="font-size:12px;font-weight:600;display:flex;gap:6px;align-items:center">
          <span style="overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${esc(r.name)}</span>
          ${r.self ? '<span class="badge off">this node</span>' : ''}
          ${r.attention ? `<span class="badge dn">${esc(r.attention)} need attention</span>` : ''}
        </div>
        <div style="font-size:9px;color:var(--muted2);font-family:var(--mono);margin-top:2px">${esc(r.server_id)}</div>
        ${bits.length ? `<div style="font-size:10px;color:var(--muted);margin-top:3px">${bits.join(' · ')}</div>` : ''}
        ${reach ? `<div style="font-size:9px;color:var(--muted2);margin-top:2px">reachable via ${reach}</div>` : ''}
      </div>
      <span class="badge ${t.cls}" style="flex-shrink:0">${esc(r.status || 'unknown')}</span>
    </div>`;
  }

  /* ── mount ───────────────────────────────────────────────────────────── */
  function shell(key, compact) {
    return `<div class="view-fleet" style="display:flex;flex-direction:column;height:100%">
      <div style="display:flex;align-items:center;gap:8px;padding:6px 10px;border-bottom:1px solid var(--border);flex-shrink:0">
        <span style="font-size:11px;color:var(--muted);font-weight:600;letter-spacing:.06em">FLEET</span>
        <span id="fleet-${key}-sub" style="font-size:10px;color:var(--muted)"></span>
        <button class="btn" style="margin-left:auto;padding:2px 10px;font-size:11px"
                onclick="window.HUB_VIEWS.fleet.reload('${key}')">&#8635; Refresh</button>
      </div>
      <div id="fleet-${key}" style="overflow-y:auto;flex:1;padding-top:6px"
           data-compact="${compact ? '1' : '0'}"></div>
    </div>`;
  }

  V.mount = function (wsId, paneId, viewConfig, body, key) {
    /* The viewport branch the shell does not do yet — see the header note. */
    if (window.innerWidth < MOBILE_MAX) return V.mountMobile(wsId, paneId, viewConfig, body, key);
    body.innerHTML = shell(key, false);
    wire(key);
    V.reload(key);
  };

  /* Same file, same data, one layout difference: the compact form drops the
   * door strip and the per-server detail lines that do not survive a 375px
   * column. It does NOT drop or add a server — the list is the list. */
  V.mountMobile = function (wsId, paneId, viewConfig, body, key) {
    body.innerHTML = shell(key, true);
    wire(key);
    V.reload(key);
  };

  /* Event delegation rather than inline onclick, unlike the other views, for
   * one specific reason: the thing being clicked carries an API-supplied id.
   * Interpolating that into a JS string inside an HTML attribute means getting
   * two levels of quoting right on data this file did not author. The lobby
   * constrains ids to [A-Za-z0-9_.-] today, but a UI that is only safe because
   * of a regex in another file is safe by luck. */
  function wire(key) {
    const el = document.getElementById('fleet-' + key);
    if (!el) return;
    el.addEventListener('click', e => {
      const c = e.target.closest('.fleet-card');
      if (c) V.select(key, c.getAttribute('data-sid'));
    });
    el.addEventListener('keydown', e => {
      if (e.key !== 'Enter' && e.key !== ' ') return;
      const c = e.target.closest && e.target.closest('.fleet-card');
      if (c) { e.preventDefault(); V.select(key, c.getAttribute('data-sid')); }
    });
  }

  /* Picking a server points the WHOLE app, not just this pane. That is the
   * point of the view — a picker that only changed its own rendering would be
   * a list, and the UI would still be locked to the box that served it. */
  V.select = function (key, sid) {
    if (!window.HubData) return;
    const cur = window.HubData.target();
    /* Clicking the selected card clears back to this node. Without that, the
     * only way back from a remote target is a reload, and an operator who
     * cannot get home does not trust the control. */
    window.HubData.setTarget((sid && sid === cur) ? '' : sid);
    /* No reload here when the target subscription is live: it re-renders every
     * fleet pane already, and doing both flashes "Loading…" twice for one
     * click. Only the no-subscription fallback needs to redraw itself. */
    if (!subscribed) V.reload(key);
  };

  V.reload = async function (key) {
    const el = document.getElementById('fleet-' + key);
    if (!el) return;
    const compact = el.getAttribute('data-compact') === '1';
    const sub = document.getElementById('fleet-' + key + '-sub');
    el.innerHTML = '<div style="padding:14px;color:var(--muted);font-size:12px">Loading…</div>';

    if (!window.HubData) {
      el.innerHTML = stub('&#9888;', 'Data layer missing',
        'ui/data.js did not load, so this view has no way to reach the lobby. ' +
        'Check the <code>&lt;script src="/ui/data.js"&gt;</code> tag in app.html.');
      return;
    }

    const res = await window.HubData.lobby({ force: true });

    /* NOT AN ERROR. A node answering 409 not_central is answering correctly:
     * it is not the lobby. Drawing this red would send an operator hunting a
     * fault that does not exist. The lobby's address comes out of the
     * response, not out of a constant here — this file must not be the second
     * place that thinks it knows the zone. */
    if (!res.ok && res.error === 'not_central') {
      const where = (res.data && res.data.lobby) || 'dashboard.<zone>';
      if (sub) sub.textContent = 'node';
      el.innerHTML = stub('&#128225;', 'This is a node, not the lobby',
        `Fleet lives at <code>${esc(where)}</code>. A node knows itself and the ` +
        `hub it beats to; it does not hold the fleet, by design — so there is ` +
        `nothing here to fix. Mode reported: <code>${esc((res.data && res.data.mode) || 'node')}</code>.`);
      return;
    }

    if (!res.ok && res.status === 401) {
      const door = (res.data && res.data.door) || 'login.flarevault.dev';
      if (sub) sub.textContent = 'signed out';
      el.innerHTML = stub('&#128274;', 'Not signed in',
        `The lobby refused this request: <code>${esc(res.error)}</code>. ` +
        `Sign in at <code>${esc(door)}</code>. Over Tailscale, the hub login on ` +
        `this page issues the session the door exchanges for a role.`);
      return;
    }

    if (!res.ok) {
      if (sub) sub.textContent = '';
      el.innerHTML = stub('&#9888;', 'Lobby unavailable',
        `<code>${esc(res.error)}</code>${res.detail ? ' — ' + esc(res.detail) : ''}. ` +
        `Nothing is being guessed at here: until the lobby answers, this view ` +
        `knows of no servers, which is not the same as there being none.`);
      return;
    }

    const d = res.data || {};
    const rows = d.servers || [];
    const ident = d.identity || {};
    const cur = window.HubData.target() || window.HubData.selfId();

    /* The count is a count of the rows we were handed. Never a total from
     * anywhere else — see the header. */
    if (sub) {
      const by = (d.summary && d.summary.by_status) || {};
      const parts = Object.keys(by).sort().map(k => by[k] + ' ' + k);
      sub.textContent = rows.length
        ? rows.length + (rows.length === 1 ? ' server' : ' servers') +
          (parts.length ? ' · ' + parts.join(' · ') : '')
        : 'empty';
    }

    const who = `<div style="padding:0 10px 6px;font-size:10px;color:var(--muted)">
      ${esc(ident.sub || 'unknown')} · <span style="color:var(--accent)">${esc(ident.role || 'no role')}</span>
      ${d.mode ? ' · mode ' + esc(d.mode) : ''}
    </div>`;

    if (!rows.length) {
      /* An empty lobby is a correct lobby (handlers/lobby.py, LOBBY FIRST).
       * This says what the role can see — it does not hint that more exists. */
      el.innerHTML = who + stub('&#128225;', 'No servers in this lobby',
        'This role has no servers to show. That is a complete answer, not a ' +
        'partial one — the lobby renders for every role, including the ones ' +
        'that can see nothing.');
      return;
    }

    el.innerHTML =
      who +
      layerStrip(d.layer) +
      (compact ? '' : doorStrip(d.doors)) +
      rows.map(r => card(r, r.server_id === cur)).join('') +
      '<div id="fleet-' + key + '-detail"></div>' +
      targetNote(rows, cur);

    // A picker that only highlights a card is a list. Selecting a server has
    // to SHOW that server, or the operator clicks, sees nothing move, and
    // concludes the switcher is broken -- which is exactly what happened.
    if (cur) V.detail(key, cur);
  };

  /* Drill in. Reads the node THROUGH THE LOBBY -- never the node hostname,
   * which answers 403 to a browser by design.
   *
   * Everything here is reported, never repaired: if the node is unreachable
   * the finding and its suggested fix are what render. Showing the local
   * box's numbers under a remote server's name is the one failure this whole
   * layer exists to make impossible. */
  V.detail = async function (key, sid) {
    const box = document.getElementById('fleet-' + key + '-detail');
    if (!box || !window.HubData) return;
    if (window.HubData.isSelf(sid)) {
      box.innerHTML = '<div style="padding:8px 10px;font-size:10px;color:var(--muted2)">' +
        'This is the box serving this page — its own views read it directly.</div>';
      return;
    }
    box.innerHTML = '<div style="padding:10px;font-size:11px;color:var(--muted)">Reading ' +
      esc(sid) + ' through the lobby…</div>';

    const r = await window.HubData.request(
      window.location.origin + '/api/lobby/server/' + encodeURIComponent(sid) + '?view=status');
    const d = r && r.data || {};

    if (!r.ok || d.ok === false) {
      const f = d.finding || {};
      box.innerHTML =
        '<div style="padding:10px;border-top:1px solid var(--border)">' +
        '<div style="font-size:11px;color:var(--red)">could not read ' + esc(sid) + '</div>' +
        '<div style="font-size:10px;color:var(--muted);margin-top:4px">' +
          esc(f.error || ('HTTP ' + (r.status || '?'))) + '</div>' +
        (f.fix ? '<div style="font-size:10px;color:var(--muted2);margin-top:3px">' +
                 esc(f.fix) + '</div>' : '') +
        '</div>';
      return;
    }

    const s = d.server || {};
    const p = d.payload || d.node || {};
    const cell = (k, v) => v === undefined || v === null || v === ''
      ? '' : '<div style="display:flex;justify-content:space-between;padding:2px 0">' +
             '<span style="color:var(--muted2)">' + esc(k) + '</span>' +
             '<span style="font-family:var(--mono)">' + esc(String(v)) + '</span></div>';
    box.innerHTML =
      '<div style="padding:10px;border-top:1px solid var(--border);font-size:10px">' +
      '<div style="font-size:11px;margin-bottom:6px">' + esc(s.name || sid) +
        ' <span style="color:var(--muted2)">read through the lobby</span></div>' +
      cell('server id', s.server_id || sid) +
      cell('status', s.status) +
      cell('containers', s.containers) +
      cell('projects', s.projects) +
      cell('needs attention', s.attention) +
      cell('os', s.os) +
      cell('uptime', s.uptime) +
      cell('last seen', s.last_seen) +
      cell('mode', p.mode) +
      '</div>';
  };

  /* Says out loud where the rest of the app is now reading from, and — when
   * that is another node — what the proxy can and cannot fetch. A picker that
   * changes global state silently is how you end up reading one server's
   * numbers under another server's name. */
  function targetNote(rows, cur) {
    const row = rows.find(r => r.server_id === cur);
    if (!row || row.self) {
      return `<div style="padding:8px 10px;font-size:10px;color:var(--muted2);border-top:1px solid var(--border)">
        Other views are reading <strong>this node</strong> directly.
      </div>`;
    }
    return `<div style="padding:8px 10px;font-size:10px;color:var(--muted);border-top:1px solid var(--border)">
      Other views are pointed at <strong>${esc(row.name)}</strong>, read through the
      lobby's service token — the browser never calls a node hostname, which
      refuses humans by design.
      <div style="color:var(--muted2);margin-top:3px">Reads are proxied from an
      allowlist of the node's own views. Anything outside it says
      <code>remote_path_unsupported</code> rather than quietly showing local
      data. Writes do not cross nodes at all — that is the layer 3 seam
      FlareVault owns.</div>
    </div>`;
  }

  /* Re-render when something else re-points the app, so two fleet panes (or a
   * fleet pane and a future header picker) cannot disagree about the target. */
  let subscribed = false;
  if (window.HubData && window.HubData.onTarget) {
    subscribed = true;
    window.HubData.onTarget(function () {
      document.querySelectorAll('.view-fleet [id^="fleet-"]').forEach(function (el) {
        const key = el.id.slice('fleet-'.length);
        if (key && !/-sub$/.test(key)) V.reload(key);
      });
    });
  }
})();
