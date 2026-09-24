/* 20404701  ui.registry — the single registration point for hub views.
 *
 * Doctrine: nav is DATA, not code. A view is one entry here plus one file in
 * ui/views/. Adding or reordering a view must never mean editing four places.
 *
 * Before this existed, registering a view meant touching all of:
 *   VIEW_DEFS          (metadata)
 *   mountPaneContent   (the switch that renders it)
 *   openView           (opening logic)
 *   buildCmdIndex      (command palette)
 * They drifted, as split sources always do: `survey` had a render case but no
 * metadata entry, and `_browser_old` was dead code still sitting in the switch.
 *
 * Loaded as a CLASSIC script (not an ES module) on purpose. app.html's script
 * block is one 5,248-line global scope; `type="module"` would move every
 * function out of global scope and break the page. This publishes a global and
 * changes nothing about how the rest of the file works.
 *
 * file: true   -> load ui/views/<key>.js, which sets mount on this entry
 * mount: null  -> render via the legacy switch in app.html (not yet migrated)
 * mount: fn    -> render via ui/views/<key>.js  (migrated)
 *
 * Adding a view is therefore one file plus one entry here. app.html is never
 * touched: the loader below injects the script tag.
 * Views migrate one at a time and each one is independently reversible.
 */
/* hidden: true  -> renders, but is not offered in nav or the command palette.
 * Two reasons a view is hidden: it is a shell (blank, iframe), or it is a
 * TOMBSTONE -- a retired view kept so that opening its key still explains the
 * retirement instead of showing an empty box.
 *
 * CORRECTION (2026-09-23): the original rationale here claimed tombstones
 * protect "a saved workspace holding that pane". They do not, because layout
 * is NOT persisted -- 18 localStorage keys in app.html cover theme, accent,
 * bookmarks, stickies and the gate token, and none cover workspaces, panes or
 * the active tab. Every session starts from createWorkspace('Home') at
 * app.html:6166.
 *
 * A justification that names a mechanism which does not exist is the same
 * defect as a document that disagrees with the machine -- it just hides in a
 * comment. The tombstones still earn their three lines, for the honest reason
 * above. Once layout IS persisted, the original reason becomes true too. */
window.HUB_VIEWS = {
  dashboard:  {icon:'⊞',  title:'Dashboard',  mount:null},
  terminal:   {icon:'⌨',  title:'Terminal',   mount:null},
  logs:       {icon:'📋', title:'Logs',       mount:null},
  docs:       {icon:'📚', title:'Docs',       mount:null},
  map:        {icon:'🗺', title:'Infra Map',  mount:null},
  vault:      {icon:'🔐', title:'Vault',      mount:null},
  issues:     {icon:'⚑',  title:'Issues',     mount:null, file:true},
  network:    {icon:'🌐', title:'Network',    mount:null},
  chat:       {icon:'🤖', title:'AI Chat',    mount:null},
  browser:    {icon:'🌐', title:'Browser',    mount:null, file:true},
  settings:   {icon:'⚙',  title:'Settings',   mount:null},
  storage:    {icon:'💾', title:'Storage',    mount:null},
  dockermgr:  {icon:'🐳', title:'Docker',     mount:null},
  files:      {icon:'📁', title:'Files',      mount:null},
  journal:    {icon:'📓', title:'Journal',    mount:null},
  runbooks:   {icon:'▶',  title:'Runbooks',   mount:null},
  iframe:     {icon:'🔗', title:'Service',    mount:null, hidden:true},
  blank:      {icon:'○',  title:'New Pane',   mount:null, hidden:true},
  federation: {icon:'🛰', title:'Federation', mount:null},

  /* Registered 2026-09-22. All nine rendered from the switch but had no entry
   * here, so a third of what the app can display was unreachable from the nav
   * — findable only by already knowing the view key. */
  survey:     {icon:'🔍', title:'Survey',       mount:null},
  guide:      {icon:'📖', title:'Guide',        mount:null},
  ports:      {icon:'🔌', title:'Ports',        mount:null},
  remote:     {icon:'🌍', title:'Remote Access',mount:null},
  activity:   {icon:'📜', title:'Activity',     mount:null},
  receipt:    {icon:'🧾', title:'Receipt',      mount:null},
  /* Two separate chat implementations, both live and both working: `chat`
   * (sendChat) and `aichat` (sendAiChat). Registering both rather than
   * silently picking one — which survives is a product decision. */
  aichat:     {icon:'💬', title:'Hub AI',       mount:null},

  /* Tombstones — retired, hidden from nav, still render their explanation. */
  platform:   {icon:'🔮', title:'Platform',    mount:null, hidden:true},
  tasks:      {icon:'📋', title:'Task Docket', mount:null, hidden:true},
};

/* Resolve a migrated view's mount function, or null to fall back to the
 * legacy switch. This is the flip-switch: a view is live from its own file the
 * moment its mount is set, and reverts by setting it back to null. */
window.HUB_VIEW_MOUNT = function (viewType) {
  const def = window.HUB_VIEWS[viewType];
  return (def && typeof def.mount === 'function') ? def.mount : null;
};

/* 20404704  view loader — pull in every migrated view's file.
 *
 * async=false keeps execution order without blocking the parser. A view whose
 * file has not finished loading simply still has mount:null, so it renders from
 * the legacy switch for that one render. The fallback makes the race harmless. */
(function () {
  Object.keys(window.HUB_VIEWS).forEach(function (key) {
    if (!window.HUB_VIEWS[key].file) return;
    var s = document.createElement('script');
    s.src = '/ui/views/' + key + '.js';
    s.async = false;
    document.head.appendChild(s);
  });
})();
