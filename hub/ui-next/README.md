# ui-next — a cloned shell, not yet a decision

**Status: nothing uses this.** The hub still serves `hub/app.html`. Deleting this
directory changes nothing else in the repo.

---

## What it is, plainly

This is a **clone** of the shell layer from the fksinv UI
(`/srv/docker/fksinv/ui/src` on ksgcohub), emptied of that app's content.

Not an homage, not a reimplementation — the actual source files, copied byte for
byte. Saying so precisely matters, because the two projects will now drift and
whoever reads this next needs to know which direction the original lies in.

```
~3,040 lines   VERBATIM      shell components, 7 shadcn primitives, store, theme
~  145 lines   written here  emptied registry, 5 widget stubs, entry point
~  108 lines   verbatim      package.json, vite config, index.html
```

## What was taken, exactly

| | taken | of | note |
|---|---|---|---|
| `shell/` | 15 | 15 | complete |
| `components/ui/` | 20 | 20 | complete |
| `components/layout/` | 2 | 2 | complete |
| `lib/store.js` stores | 4 | 6 | `useDraftStore` and `useTruckStore` removed: zero shell references |

**The extraction is CLOSED.** Everything the shell layer needs is here: zero
dangling internal imports, every external package declared. There is no reason
to read `/srv/docker/fksinv` again, and not doing so is the point — one clean
copy, then independence. From here this shell is ours to change freely, and
changing it cannot affect that app.

**Still carries fksinv's shape in two places.** `useUserStore` (5 references —
Header, Footer, MobileHeader) is fksinv's auth model, not ServerHub's sessions.
`useScannerStore` (1 reference — MobileHeader's input-mode toggle) is a barcode
scanner ServerHub has no use for. Both stay because removing them breaks the
build; both need replacing before this ships.

## What was emptied

- `lib/registry.js` — was 186 lines of fksinv's nav tree (Catalog, Business,
  Truck, Client Portal…). Now a shape with three example items.
- `components/widgets/*` — five real widgets became five stubs. `WidgetBar`
  imports them by name, so deleting the files breaks the build, and a template
  that does not build is not a template.
- 12 dependencies dropped that the shell never imports: dnd-kit, react-table,
  react-virtual, react-hook-form, cmdk, date-fns, sonner, sql.js, zod, and the
  shadcn CLI.

## Why this shell and not a new one

Its five regions are the five ServerHub already has:

```
fksinv     AppRail | AppNav | [Header · main · Footer] | ContextPane | WidgetBar
ServerHub  catnav  | secnav | wsarea                   | wpanel      | wdock
```

Same regions, same order — independently arrived at. And `Shell.jsx` carries
this, which is the rule `hub/app.html` breaks on the first click of every
session because its boot tab is pinned:

```js
// When navigating, update the ACTIVE tab (don't create a new one)
// New tabs only created via the + button
```

It also has a registry, for the same reason ServerHub does.

## The cost, stated once

**This is a fork.** Fix `Header.jsx` here and fksinv does not get it. Two copies
of one shell drifting apart is the precise disease this project spent September
2026 curing — two installers, two schemas, two port bands, two disk readers, six
endpoints answering one question. A clone is a future divergence with a delay
fuse.

That is an argument for **deciding**, not for hesitating. Either this becomes
ServerHub's shell and `hub/app.html`'s chrome is retired, or this directory is
deleted. What must not happen is it sitting here half-adopted.

## If it becomes real

The migration does not need a rewrite, because every existing view already
produces an HTML string:

```
React shell
  └── <main>
        during migration:  dangerouslySetInnerHTML( existing render fn )
        after:             a real React view
```

So the shell can go live with all 24 views working unchanged, and each converts
when convenient. No blank template, no half-dead app.

**The one real cost is a build step.** ServerHub is stdlib-only and Python serves
files directly. Solvable without putting node on a server: commit the built
bundle, build on a dev machine or in CI, `bootstrap.sh` keeps cloning and
serving files.

## Running it

```bash
cd hub/ui-next && npm install && npm run dev
```

Shell mounts around an empty router with three placeholder routes. Nothing is
wired to the hub's API yet.

## Provenance

Cloned 2026-09-23 from ksgcohub `/srv/docker/fksinv/ui`. The source app was
**not modified**: `build: ./ui` with no bind mounts, so the container serves an
image-baked bundle. Verified after the copy — `fks-ui` and `fks-api` both
running, `restarts=0`, `:10101` serving 200, zero files changed under
`/srv/docker/fksinv`, newest source mtime still 2026-09-15.
