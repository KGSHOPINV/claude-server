# Task docket — there isn't one here any more

This file was the control experiment, and it failed exactly as predicted.

It was a hand-maintained roadmap: what was done, what was next, what needed the
operator. It was last true on **2026-09-16**. It then sat in the tree for weeks
looking precisely as authoritative as it had on the day it was written, while
its "Done" column went stale, its "Up Next" column listed work that had shipped,
and its route counts disagreed with four other files and with the route table.

**Nobody noticed, and nobody could have** — a document has no way to disagree
with the machine. That is the whole defect, and it is why `hub/tools/tracks.py`
names this file by name at its own foot as the thing it exists to replace.

---

## What answers the questions this file used to answer

| Question | Command |
|---|---|
| Which track is next, and why that one? | `python3 hub/tools/tracks.py` |
| Which step of the build order are we on? | `python3 hub/tools/step.py` |
| What is built, what is hand-built, what is phasing out? | `python3 hub/tools/atlas.py` |
| What do the five checklists say **today**? | `python3 hub/tools/matrix.py` |
| What is serving, what is exposed, what could I not see? | `python3 hub/tools/situation.py` |
| Is this node at the installer's standard? | `bash bootstrap.sh --check` |
| What external systems do we touch? | `python3 hub/tools/edges.py` |

`atlas.py` prints the phase-out list with the one condition that makes each item
next, and `tracks.py` prints the operator decisions that nothing proceeds on by
itself. Between them they replace every column this file used to carry.

---

## The one thing a command cannot answer

A standing operator item, kept here because it is a decision and not a status:

**The sudo password that appeared in public git history must be rotated by
hand, and reuse checked** on every service that was given it. Nothing in this
repo can do that, and nothing can verify it was done. It stays written down
until the operator says it is done.

If you want to add a task to this file, add a check to a tool instead.
