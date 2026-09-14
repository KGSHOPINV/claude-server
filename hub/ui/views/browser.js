/* 20404802  ui.views.browser — Browser pane
 * Migrated verbatim from the mountPaneContent switch. Behavior unchanged.
 * Note: the switch also carries a `_browser_old` case that nothing routes to —
 * dead code, left in place for now rather than removed as a silent side effect. */
(function () {
  window.HUB_VIEWS.browser.mount = function (wsId, paneId, viewConfig, body, key) {
    body.innerHTML = `<div class="stub-view"><div class="stub-icon">🌐</div><div class="stub-title">Browser</div><div class="stub-msg">Use your real browser. Services are accessible via the Services nav — click any to open in an iframe pane.</div></div>`;
  };
})();
