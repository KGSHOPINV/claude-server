/* 20301704  sw.js — the service worker. Two jobs, and deliberately no third.
 *
 * WHAT IT DOES
 *   1. Exists. A service worker at root scope is the requirement for "Install
 *      app" to appear -- without one the manifest alone does nothing.
 *   2. Owns the notification. showNotification() must be called on a service
 *      worker registration; a page calling new Notification() is not the same
 *      thing and does not survive the tab losing focus.
 *
 * WHAT IT DOES NOT DO, ON PURPOSE
 *   No offline cache of API responses. A control panel that shows you a cached
 *   view of a server is worse than one that says it cannot reach the server --
 *   the whole point of the page is to tell you what is true right now. Stale
 *   container states presented as current is exactly the failure this project
 *   has spent a fortnight removing everywhere else.
 *
 *   The shell (HTML/JS) is cached so the app opens without the network. The
 *   data never is.
 */
const SHELL = 'hub-shell-v1';
const SHELL_FILES = ['/', '/manifest.json'];

self.addEventListener('install', (e) => {
  e.waitUntil(caches.open(SHELL).then((c) => c.addAll(SHELL_FILES)).catch(() => {}));
  self.skipWaiting();
});

self.addEventListener('activate', (e) => {
  e.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== SHELL).map((k) => caches.delete(k))))
      .then(() => self.clients.claim())
      .catch(() => {})
  );
});

self.addEventListener('fetch', (e) => {
  const url = new URL(e.request.url);
  // Never serve API from cache. See above -- stale truth is the bug.
  if (url.pathname.startsWith('/api/')) return;
  if (e.request.method !== 'GET') return;
  e.respondWith(
    fetch(e.request).catch(() => caches.match(e.request).then((r) => r || Response.error()))
  );
});

/* The page hands events here, because the worker outlives the page's focus. */
self.addEventListener('message', (e) => {
  const d = e.data || {};
  if (d.type !== 'notify') return;
  self.registration.showNotification(d.title || 'Server Hub', {
    body: d.body || '',
    tag: d.tag || 'hub',            // same tag replaces rather than stacks
    renotify: !!d.renotify,
    data: { url: d.url || '/' },
    badge: '/manifest.json',
  });
});

/* Push, for later. The hub sends nothing to it today -- that needs VAPID keys
 * and a push subscription, which is the BACKGROUND layer and is not built.
 * The handler is here so that when it is, the worker does not need changing. */
self.addEventListener('push', (e) => {
  let d = {};
  try { d = e.data ? e.data.json() : {}; } catch (_) { d = {}; }
  e.waitUntil(self.registration.showNotification(d.title || 'Server Hub', {
    body: d.body || '', tag: d.tag || 'hub', data: { url: d.url || '/' },
  }));
});

self.addEventListener('notificationclick', (e) => {
  e.notification.close();
  const target = (e.notification.data && e.notification.data.url) || '/';
  e.waitUntil(
    self.clients.matchAll({ type: 'window', includeUncontrolled: true }).then((wins) => {
      // Focus the hub if it is already open rather than opening a second copy.
      for (const w of wins) { if ('focus' in w) return w.focus(); }
      return self.clients.openWindow(target);
    })
  );
});
