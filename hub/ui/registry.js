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
 * mount: null  -> render via the legacy switch in app.html (not yet migrated)
 * mount: fn    -> render via ui/views/<key>.js  (migrated)
 * Views migrate one at a time and each one is independently reversible.
 */
window.HUB_VIEWS = {
  dashboard:  {icon:'⊞',  title:'Dashboard',  mount:null},
  terminal:   {icon:'⌨',  title:'Terminal',   mount:null},
  logs:       {icon:'📋', title:'Logs',       mount:null},
  docs:       {icon:'📚', title:'Docs',       mount:null},
  map:        {icon:'🗺', title:'Infra Map',  mount:null},
  vault:      {icon:'🔐', title:'Vault',      mount:null},
  issues:     {icon:'⚑',  title:'Issues',     mount:null},
  network:    {icon:'🌐', title:'Network',    mount:null},
  chat:       {icon:'🤖', title:'AI Chat',    mount:null},
  browser:    {icon:'🌐', title:'Browser',    mount:null},
  settings:   {icon:'⚙',  title:'Settings',   mount:null},
  storage:    {icon:'💾', title:'Storage',    mount:null},
  dockermgr:  {icon:'🐳', title:'Docker',     mount:null},
  files:      {icon:'📁', title:'Files',      mount:null},
  journal:    {icon:'📓', title:'Journal',    mount:null},
  runbooks:   {icon:'▶',  title:'Runbooks',   mount:null},
  iframe:     {icon:'🔗', title:'Service',    mount:null},
  blank:      {icon:'○',  title:'New Pane',   mount:null},
  federation: {icon:'🛰', title:'Federation', mount:null},
};

/* Resolve a migrated view's mount function, or null to fall back to the
 * legacy switch. This is the flip-switch: a view is live from its own file the
 * moment its mount is set, and reverts by setting it back to null. */
window.HUB_VIEW_MOUNT = function (viewType) {
  const def = window.HUB_VIEWS[viewType];
  return (def && typeof def.mount === 'function') ? def.mount : null;
};
