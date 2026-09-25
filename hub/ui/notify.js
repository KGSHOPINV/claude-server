/* 20301711  notify.js — the client half of the notification path.
 *
 * THE CHAIN THIS SITS IN
 *   flarevault.dev            splash, public, says nothing about the fleet
 *     -> Cloudflare Access    Google login. ONE login.
 *       -> hub tile/dashboard which server
 *         -> a server         you are here
 *
 * The login above is what makes this file work with no credential of its own.
 * Once Access has vetted you, the hub's check_auth accepts the request on the
 * Cf-Access-Authenticated-User-Email header alone -- so EventSource, which
 * cannot set headers, still authenticates. Over Tailscale, where there is no
 * Access, it falls back to the session token in the query string.
 *
 * That is the whole reason the notifications depend on the gate order: fix the
 * login chain and notifications come free; leave two logins and the stream has
 * to carry a token the PWA cannot reliably keep.
 *
 * HONEST SCOPE. This delivers while the hub is OPEN -- a tab, or the installed
 * PWA, in the foreground or backgrounded by the OS. It does NOT deliver when
 * the app has been fully closed; that needs Web Push and a VAPID key pair, and
 * is not built. Nothing here pretends otherwise.
 */
(function () {
  const LAST_KEY = 'hub_notify_last_id';
  const LEVEL_KEY = 'hub_notify_level';
  let es = null, backoff = 2000, worker = null;

  function token() {
    try { return sessionStorage.getItem('hub_token') || localStorage.getItem('hub_token') || ''; }
    catch (_) { return ''; }
  }
  function lastId() { try { return parseInt(localStorage.getItem(LAST_KEY) || '0', 10) || 0; } catch (_) { return 0; } }
  function setLast(n) { try { localStorage.setItem(LAST_KEY, String(n)); } catch (_) {} }
  function level() { try { return localStorage.getItem(LEVEL_KEY) || 'warn'; } catch (_) { return 'warn'; } }

  // 20301712  register — the service worker. Its absence is why "Install app"
  // never appeared and why no notification could ever be shown.
  async function register() {
    if (!('serviceWorker' in navigator)) return null;
    try {
      const reg = await navigator.serviceWorker.register('/sw.js', { scope: '/' });
      await navigator.serviceWorker.ready;
      worker = reg;
      return reg;
    } catch (e) {
      console.warn('[notify] service worker refused:', e && e.message);
      return null;   // http:// over LAN has no secure context; the stream still works
    }
  }

  function show(ev) {
    const title = (ev.source ? ev.source + ': ' : '') + (ev.action || 'Server event');
    const body = ev.detail || ev.category || '';
    if (worker && Notification.permission === 'granted') {
      // Through the worker, so it survives the tab losing focus.
      navigator.serviceWorker.controller
        ? navigator.serviceWorker.controller.postMessage(
            { type: 'notify', title, body, tag: 'hub-' + (ev.category || 'general'), url: '/' })
        : worker.showNotification(title, { body, tag: 'hub-' + (ev.category || 'general') });
    }
    document.dispatchEvent(new CustomEvent('hub:event', { detail: ev }));
  }

  // 20301713  connect — one open connection; the server pushes down it.
  function connect() {
    if (es) { try { es.close(); } catch (_) {} }
    const q = new URLSearchParams({ since: String(lastId()), level: level() });
    const t = token();
    if (t) q.set('token', t);      // Tailscale path; unused behind Access
    es = new EventSource('/api/events/stream?' + q.toString());

    es.addEventListener('open', () => { backoff = 2000; });
    es.addEventListener('activity', (m) => {
      let ev; try { ev = JSON.parse(m.data); } catch (_) { return; }
      setLast(ev.id);
      show(ev);
    });
    es.addEventListener('bye', () => { try { es.close(); } catch (_) {} connect(); });

    // Not an error path worth shouting about: the server closes every stream at
    // 10 minutes by design, and EventSource reconnects. Nothing is lost,
    // because the rows sit in activity_log whether anyone is listening or not.
    es.onerror = () => {
      try { es.close(); } catch (_) {}
      setTimeout(connect, backoff);
      backoff = Math.min(backoff * 2, 60000);
    };
  }

  // 20301714  catchUp — what happened while nothing was connected
  async function catchUp() {
    try {
      const t = token();
      const r = await fetch('/api/events/since?id=' + lastId() + '&level=' + level()
                            + (t ? '&token=' + encodeURIComponent(t) : ''),
                            { headers: t ? { 'X-Hub-Token': t } : {} });
      const d = await r.json();
      if (d && d.events && d.events.length) {
        setLast(d.last_id);
        // One summary, not thirty. A queue that dumps a week of backlog as
        // individual notifications is a queue you turn off.
        if (d.events.length > 3) {
          show({ source: 'hub', action: d.events.length + ' events while you were away',
                 detail: d.events[d.events.length - 1].action, category: 'catchup' });
        } else { d.events.forEach(show); }
      } else if (d && typeof d.head === 'number' && !lastId()) {
        setLast(d.head);
      }
    } catch (_) {}
  }

  // 20301715  enable — called from a click. Browsers refuse the permission
  // prompt outside a user gesture, so this cannot be done on page load.
  async function enable() {
    await register();
    if (!('Notification' in window)) return 'unsupported';
    let p = Notification.permission;
    if (p === 'default') p = await Notification.requestPermission();
    try { localStorage.setItem('hub_notify_on', p === 'granted' ? '1' : '0'); } catch (_) {}
    return p;
  }

  async function start() {
    await register();
    await catchUp();
    connect();
    document.addEventListener('visibilitychange', () => {
      if (document.visibilityState === 'visible' && (!es || es.readyState === 2)) connect();
    });
  }

  window.HubNotify = {
    start, enable, connect,
    status: () => ({
      permission: (window.Notification && Notification.permission) || 'unsupported',
      worker: !!worker,
      stream: es ? ['connecting', 'open', 'closed'][es.readyState] : 'not started',
      last_id: lastId(), level: level(),
    }),
    setLevel: (l) => { try { localStorage.setItem(LEVEL_KEY, l); } catch (_) {} connect(); },
  };
})();
