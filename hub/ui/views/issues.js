/* 20404801  ui.views.issues — Issues pane
 *
 * This view was a stub standing in front of a renderer that looked finished
 * and was not.
 *
 * renderIssues() lived in app.html with ZERO callers while mountPaneContent
 * rendered a .stub-view claiming issue tracking "will be available once you
 * start adding issues" — untrue, since GET /api/issues was live the whole
 * time. A nine-agent inventory found the orphan and refused to delete it,
 * calling it "a COMPLETE WORKING issues renderer".
 *
 * It was not complete. It read i.description, i.resolution and i.created_date.
 * The table (kernel/db.py) declares:
 *
 *     id · service · title · body · status · created · updated
 *
 * So three of its five fields would have rendered blank. Wiring it unchanged
 * would have produced a view that looked broken and been blamed on the data.
 * This renders against the schema that exists — which is why the view owning
 * its own rendering is better than app.html owning it at a distance.
 *
 * renderIssues() is deleted from app.html by the same commit; this file is now
 * the only renderer, and it sits next to the registry entry that mounts it.
 */
(function () {
  const esc = s => String(s == null ? '' : s)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');

  /* `created` is an INTEGER column, but rows seeded by hand or by older code
   * carry an ISO string. Accept either rather than printing NaN at someone. */
  function when(v) {
    if (!v) return '';
    if (typeof v === 'number' || /^\d+$/.test(v)) {
      const n = Number(v);
      const ms = n < 1e12 ? n * 1000 : n;      // seconds vs milliseconds
      try { return new Date(ms).toISOString().slice(0, 10); } catch { return ''; }
    }
    return String(v).replace('T', ' ').slice(0, 16);
  }

  window.HUB_VIEWS.issues.mount = function (wsId, paneId, viewConfig, body, key) {
    const listId = 'iss-list-' + key;
    body.innerHTML = `<div class="view-issues" style="display:flex;flex-direction:column;height:100%">
      <div style="display:flex;align-items:center;gap:8px;padding:6px 10px;border-bottom:1px solid var(--border);flex-shrink:0">
        <span style="font-size:11px;color:var(--muted);font-weight:600;letter-spacing:.06em">ISSUES</span>
        <span id="${listId}-count" style="font-size:10px;color:var(--muted)"></span>
        <button class="btn" style="margin-left:auto;padding:2px 10px;font-size:11px"
                onclick="window.HUB_VIEWS.issues.reload('${key}')">&#8635; Refresh</button>
      </div>
      <div id="${listId}" style="overflow-y:auto;flex:1"></div>
    </div>`;
    window.HUB_VIEWS.issues.reload(key);
  };

  /* A named method, not a closure, so the inline onclick above can reach it —
   * the same wiring every other control in this codebase uses. */
  window.HUB_VIEWS.issues.reload = async function (key) {
    const listId = 'iss-list-' + key;
    const el = document.getElementById(listId);
    if (!el) return;
    el.innerHTML = '<div style="padding:14px;color:var(--muted);font-size:12px">Loading…</div>';

    await fetchIssues();                       // fills S.issues from /api/issues
    const rows = S.issues || [];
    const open = rows.filter(i => i.status === 'open').length;

    const countEl = document.getElementById(listId + '-count');
    if (countEl) countEl.textContent = rows.length ? `${open} open · ${rows.length} total` : '';

    if (!rows.length) {
      /* The old stub explained where issues come from, which is the one useful
       * thing it did. Keep that; drop its false claim that the feature does not
       * exist yet. */
      el.innerHTML = `<div class="stub-view" style="height:auto;padding:28px 16px">
        <div class="stub-icon">&#9873;</div>
        <div class="stub-title">No issues</div>
        <div class="stub-msg">Issues are rows in the hub database, served by
          <code>GET /api/issues</code>. They arrive from the CLI or when the
          activity log flags something — nothing needs configuring here.</div>
      </div>`;
      return;
    }

    el.innerHTML = rows.map(i => `<div class="iss-row">
      <div class="iss-dot ${esc(i.status)}"></div>
      <div style="min-width:0">
        <div class="iss-title">${esc(i.title)}</div>
        ${i.body ? `<div class="iss-desc">${esc(i.body)}</div>` : ''}
        <div class="iss-date">${when(i.created)}${i.service ? ' · ' + esc(i.service) : ''}</div>
      </div>
      <span class="badge ${i.status === 'open' ? 'off' : 'up'}"
            style="margin-left:auto;flex-shrink:0">${esc(i.status)}</span>
    </div>`).join('');
  };
})();
