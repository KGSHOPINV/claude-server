# ui-next — a cloned shell, and the decision it is waiting on

**`ui-next` is adopted as the direction.** Looking like fksinv is fine. What is
not settled is *when*; until it ships, the hub serves the existing frontend.

Whether anything imports it yet is a question for the tree, not for a status
line that has already been wrong:

```bash
grep -rn "ui-next" --include=*.py --include=*.html --include=*.js hub/ | grep -v ui-next/
python3 hub/tools/tracks.py     the order: unison, then mockups, then UI
```

**Order is enforced, not preferred:** unison then mockups then UI. Mockups
before any build. `tracks.py` refuses to let the UI track start early.

---

## What it is, plainly

This is a **clone** of the shell layer from the fksinv UI
(`/srv/docker/fksinv/ui/src` on ksgcohub), emptied of that app's content.

Not an homage, not a reimplementation — the actual source files, copied byte for
byte. Saying so precisely matters, because the two projects will now drift and
whoever reads this next needs to know which direction the original lies in.

## What was taken

The shell layer, its UI primitives, its layout components, and only the stores
those actually reference — stores with zero shell references were left behind.

Line counts are not recorded here. `wc -l` the directory if you need them; two
previous copies of those numbers in this repo disagreed with each other.

**The extraction is CLOSED.** Everything the shell layer needs is here: zero
dangling internal imports, every external package declared. There is no reason
to read `/srv/docker/fksinv` again, and not doing so is the point — one clean
copy, then independence. From here this shell is ours to change freely, and
changing it cannot affect that app.

**It still carries fksinv's shape in two places.** `useUserStore` is fksinv's
auth model, not ServerHub's sessions. `useScannerStore` is a barcode scanner
ServerHub has no use for. Both stay because removing them breaks the build, and
**a template that does not build is not a template** — but both must be replaced
before this ships.

## What was emptied

- `lib/registry.js` — was fksinv's nav tree. Now a shape with example items.
- `components/widgets/*` — real widgets became stubs. `WidgetBar` imports them
  by name, so deleting the files breaks the build.
- Every dependency the shell never imports was dropped. `package.json` is the
  list of what remains; a paragraph here would be a second one.

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

So the shell can go live with **every existing view working unchanged**, and
each converts when convenient. No blank template, no half-dead app.

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

## Provenance — 2026-09-23

Cloned from another project's UI source on its own server.

**The source app was not modified, and that was verified rather than assumed:**
its containers still running with zero restarts, its port still serving, zero
files changed under its directory, and its newest source mtime unchanged.

**Law XII: never touch another project.** Read to describe; never change. The
check above is what "never changed it" looks like when you have to prove it
instead of claiming it.
