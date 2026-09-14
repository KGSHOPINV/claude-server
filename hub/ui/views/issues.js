/* 20404801  ui.views.issues — Issues pane
 * Migrated verbatim from the mountPaneContent switch. Behavior unchanged. */
(function () {
  window.HUB_VIEWS.issues.mount = function (wsId, paneId, viewConfig, body, key) {
    body.innerHTML = `<div class="stub-view"><div class="stub-icon">⚑</div><div class="stub-title">Issues</div><div class="stub-msg">Issue tracking will be available once you start adding issues via the CLI or the activity log flags them automatically.</div></div>`;
  };
})();
