# design/console

The new server console. **Nothing here is deployed** — `deploy-notify` is what
the servers run, and this branch never merges into it until the console is
approved.

## Why a branch

The last stretch mixed live fixes with exploration on one branch, and a blanket
`git add -A` during a conflict swept the live `control.db` into the deploy
branch. Both servers refused the checkout; git stopped it, not me. Design work
that can touch what is serving is design work that will eventually break it.

## What it holds

- `hub/ui-next/` — a React + Vite + Tailwind shell, a byte-for-byte clone of
  fksinv's UI, already in this repo. Adopted deliberately: the operator's
  words, "i don't mind it looking like fksinv its basically the same idea as
  our current console".
- Mockups, which are **owed before any build**.

## The rules this branch works under

1. **Mockups first.** A picture, judged, before five thousand lines exist.
2. **Never touch fksinv.** `hub/ui-next/` is our copy. `/srv/docker/fksinv/**`
   is another team's production and is out of bounds — read the copy.
3. **Build on the PC, commit the output.** ksgcohub has no node; fks has v22.
   Servers stay dumb and serve byte-identical assets, so "two servers, one
   build" is literally true rather than hoped for.
4. **One surface.** `mobile.html` dies here. It is a second frontend and it
   drifted today — a login fix landed in `app.html` and silently missed it.
5. **Unison first.** `hub/tools/tracks.py` reports NEW UI as BLOCKED until the
   build order completes, and that block is the point, not an inconvenience.

## Where the truth lives

Run these rather than trusting a document — `TASKS.md` has been stale since
2026-09-16 and nobody noticed:

    python3 hub/tools/tracks.py        three tracks, what is next
    python3 hub/tools/step.py          the build order, checked against the machine
    python3 hub/tools/situation.py     what serves, what is exposed, what I could not see
