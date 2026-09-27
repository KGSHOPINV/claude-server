# events-stream — the notification unit

**Four files and one table.** Nothing else. If that stops being true, this
document is wrong and the unit has stopped being liftable.

| File | Code | Role | Without it |
|---|---|---|---|
| `handlers/events_stream.py` | 20204014 | the two endpoints + the self-check | no stream at all |
| `ui/sw.js` | 20301704 | service worker — owns `showNotification`, makes the app installable | stream works, no OS notification, no "Install app" |
| `ui/notify.js` | 20301711 | registers the worker, holds the connection, catches up | endpoints exist and nothing calls them |
| `app.html` → `enableNotifications()` | 20301716 | the Enable button | permission can never be asked for |

Endpoints: `GET /api/events/stream` (SSE), `GET /api/events/since` (catch-up),
`GET /api/events/self` (the self-check). Publishing reuses the hub's existing
`POST /api/activity` — this unit adds no write path of its own.

Ask the unit itself rather than trusting this table:

```bash
curl -s http://localhost:8765/api/events/self | python3 -m json.tool
```

Gate 0, deliberately: it returns no event content, only which files are present
and whether `activity_log` is readable. "Notifications are broken" and "I can't
log in" have the same first question, so the answer must not need a login.

## The three layers

```
  HOLDING      activity_log            already existed, already written to
     |         nothing is lost when nobody is listening
     v
  LIVE         THIS UNIT               delivers while the hub is open/installed
     |         SSE -> service worker -> OS notification
     v
  BACKGROUND   NOT BUILT               app fully closed; needs Web Push + VAPID
```

The holding layer is why the live layer can be this small. The client sends the
last id it saw; the server replays from there. A dropped connection is a
non-event, not a lost notification — so there is no queue, no ack, no retry
table, and nothing to get out of sync.

## Publishing and subscribing — the ntfy shapes, without ntfy

Publish from anything that can curl. This is the `curl -d "msg" ntfy.sh/topic`
equivalent, and it already existed:

```bash
curl -s -X POST http://localhost:8765/api/activity   -H 'Content-Type: application/json'   -d '{"action":"backup finished","source":"backup","category":"backup","level":"warn"}'
```

Subscribe to a slice rather than the firehose — ntfy's topics, as query
parameters:

| Parameter | Meaning |
|---|---|
| `level=` | minimum severity: `info` `warn` `high` `critical` (default `warn`) |
| `cat=` | categories, comma separated |
| `src=` | sources, same syntax |
| `-name` | a leading minus excludes instead of includes |

```
/api/events/stream?cat=backup,deploy      only those two
/api/events/stream?src=-docker            everything except docker
```

Filtering happens on the server, not in the client: a phone on a bad connection
should not be sent a thousand rows so the browser can drop 990.

**The cursor follows what was examined, not what was delivered.** SQL applies
its row limit before the filter runs, so a page of 50 can match nothing while
thousands of rows sit behind it. A cursor that only advanced past *delivered*
rows would re-read the same window forever and deliver nothing, permanently,
with no error anywhere — a silent stall caused by nothing worse than a quiet
filter. `/since` therefore returns `more`, and the client pages until it is
false.

## Why not ntfy

ntfy is installed on `:8085`, routed at `ntfy.ksgco.app`, correctly locked to
deny-all, and has published **zero** messages — the hub has never held a token
for it. It sat there working perfectly and delivering nothing, while the panel
in `app.html` told you push alerts were going to it.

It keeps one real advantage: native apps holding a background connection, which
reaches a phone with everything closed. This unit does not replace that and is
not trying to. What it replaces is the part where a notification has to leave
the hub and come back through a second auth system.

## Why it depends on the login chain

```
  flarevault.dev          splash, public, names nothing
    -> Cloudflare Access  Google. ONE login.
      -> hub tile         which server
        -> a server       you are here, and the stream just works
```

`EventSource` cannot set headers. Behind Access it does not need to: the hub's
`check_auth` accepts the request on `Cf-Access-Authenticated-User-Email` alone,
so the stream authenticates with no credential of its own. Over Tailscale,
where there is no Access, it falls back to `?token=` in the query string.

**So the gate order is not cosmetic.** Fix the login chain and notifications
come free. Leave two logins and the stream has to carry a token the PWA cannot
reliably keep — `sessionStorage` dies when the app closes, and moving it to
`localStorage` to compensate makes the token outlive the session on purpose,
which is a real loosening and should be a decision, not a side effect.

## Lifting it to its own repo

One hub-specific line in the Python: `from kernel.db import db_conn`. Replace
with any callable returning a DB-API connection over a table with
`(id, ts, source, category, action, detail, level)`.

Two hub-specific things elsewhere: the two route entries in `kernel/router.py`,
and the `<script src="/ui/notify.js">` tag. The two JS files have no hub
dependency at all.

`sw.js` **must** be served from `/sw.js`, not `/ui/sw.js` — a service worker
only controls paths at or below the URL it was served from.

## Known limits, stated rather than discovered

- **Closed app does not notify.** Needs Web Push. Not built.
- **`http://` on the LAN has no secure context**, so the browser refuses to
  register a service worker. The stream still works; notifications do not. Use
  the Tailscale or Cloudflare hostname.
- **Once denied, the page cannot ask again.** Only the browser's site settings
  can reset it.
- **One thread per open stream.** Fine for a handful of viewers; this is not a
  broadcast server.
- **Default level is `warn`.** `info` is every container start and every port
  appearing — a stream that fires constantly gets muted, which is the same as
  not having one.
