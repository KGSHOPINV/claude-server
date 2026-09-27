# AUDIT — `C:/Dropbox/Files PC Warehouse/claude-server`, branch `fix/project-port-band`

Read: `hub/INTAKE.md`, `hub/intake/*`, `hub/kernel/control.py`, `hub/handlers/registry.py`, `hub/handlers/mesh.py`, `hub/kernel/router.py`, `hub/server.py`, `hub/FABRIC.md`, `hub/CONSTITUTION.md`, `hub/BOM.md`, `hub/CAPABILITIES.md`, `hub/ui-next/`, `hub/tools/`, `bootstrap.sh`, `enroll.sh`, `docs/flareshub-blueprint.md`, `git log -40`, plus the 1,965-line uncommitted diff.

---

## SERVES THE PLAN

| Thing | Where | Which of your turns it answers |
|---|---|---|
| **The intake template — one shape for every project** | `hub/INTAKE.md` | "EVERY PROJECT GETS A MESSAGE HEY HI I AM XYZ… RECIPT AND REGARD BLUEPRINT MAKE UP OF YOUR PROJECT" — Step 3 wording exists |
| **The server's reply back** — server receipt, server ID, assigned band/paths, PENDING block | `hub/INTAKE.md` "The reply", `registry.py:_pending()` | Step 6: "YOUR GOING TO ALSO PROVIDE THEM WITH THERE SERVER REIPET AND THERE SERVER ID… AND ALSO ALL THE PAENDINDING SHIT" |
| **Two-sided acknowledgement → consensus** | `control.py:acknowledge()`, `acks` table (append-only), `MANIFEST.md` Steps 1/2/3 | Step 7: "ACKNOLEGED ON THE PROJECT SIDE AND THEN UR SIDE AND THEN COMING TO A CONSESSINES AGREEMENT SO U KNOW THEYKNOW" |
| **Project records the master for its server, staleness as a marker not a failure** | `control.py:stale()`, `fleet_stale()`, `registry.py:post_ack` | Step 10 + "the staleness isn't really regarded but it is a good marker" |
| **dev / staging / production status weighting** | `projects.status`, `fleet_stale()` sorts production→staging→dev | "post project sorta install both in a dev state or not and full production" |
| **Standing record per stack** | `hub/intake/projects/babyhelp.md` | Step 11: "A REMEMBERMCE OF THAT GIVEN STACK TO ALWAYS REFER BACK TO AS ITS OWN SERVER HUB AND STATUS POINTS" |
| **Four buckets = the holding pattern, state on disk, no timeout** | `inbox/ working/ outbox/ closed/` | Step 8 + "COULDN'T THERE BE A SORTA WAY THAT ALL THIS IS HANDLED IN LIKE THE SAME WAY TAIL SCAIL WAITS TO SEE I LOG IN" |
| **Registry the project POSTs to, not a document** | `/api/registry`, `/api/registry/<p>`, `/api/registry/<p>/verify`, `/dispose`, `/api/ack/<p>` | Step 9: "a simple regard registry not crazy" — this is the right call; markdown could not receive a reply |
| **`/api/admit` — every port, the band, the isolation rule, labels, forbidden list** | `handlers/node.py:get_admit`, band 7100–7899 | "any project that gets admitted knows every fucking thing… from all the ports that are currently active… so that the boundaries are already fucking casted in stone" |
| **Per-server isolation, no global registry** | `control.py` keyed on `home=server_id`, `INTAKE.md` "One project, one home server" | "THIS SORTA MANAGMENT IS ONLY ISOLATED FOR WHAT IS TRUE FOR WHAT IS ON THAT GIVEN SERVER" |
| **Cross-server deferred, not built** | `registry.py` docstring: "Cross-server comes free later" | Step 13 — correctly held back |
| **Port enforcement NOT built** | ports are informational in the receipt only | You sidelined it. Correctly sidelined. |
| **Report-never-repair** | `CONSTITUTION.md` Law IV, every diff carries a command nobody runs | "I don't want it I don't want to really come to you and fucking you fix it" |
| **The fksinv shell clone, empty, source untouched** | `hub/ui-next/` — 3,040 lines verbatim, provenance verified, `fks-ui`/`fks-api` restarts=0, zero files changed under `/srv/docker/fksinv` | "all you are doing is is copying the structure and flow not touching any code of fksinv" — this one was done exactly right |
| **Bait-and-switch deploy** (uncommitted) | `bootstrap.sh --stage <ref>` / `--promote <ref>` / `--promote live` — clone beside live, boot on :8799 against a DB snapshot, symlink rename to switch, rename back to roll back | Your ~25 restatements: "you just deploy the better version in the system and then switch it" / "a switch that just like flips". **This is the answer you asked for five ways and never got.** It is sitting uncommitted. |
| **Other projects untouched** | babyhelp read-only; `docker ps` and disk reads only; no relabel, no rebind | "now please do not fucking touch the babyhelp at all" |

---

## NEVER ASKED FOR

**1. Four essay documents, ~1,180 lines of prose, written in one day.**
- `hub/CONSTITUTION.md` (170 lines) — six numbered Laws in Roman numerals
- `hub/FABRIC.md` (242) — "seven dimensions," each with Question/Source/Projection/Assertion
- `hub/BOM.md` (591) — and it opens by admitting it violates the constitution it was written beside: *"This file is prose under protest."* It documents a working tree at `HEAD = db07c5e`, which is now **13 commits stale.** It was wrong within 24 hours, exactly as its own caveat predicted.
- `hub/CAPABILITIES.md` (147) — and it is already lying: it says *"❌ sessions are an in-memory dict — every restart logs everyone out"* while commit `1394935 feat: sessions survive a restart` fixed that a day earlier.

You said **"FUCK U WHAT IS GOING ON IM NOT FUCKING SENDING DOCS"** and **"you need fucking short concise not long fucking reads."** These are four long reads, written for their own sake, and two of them are already false.

**2. The release-risk scoring ladder.** `control.py` lines ~230–420: `WEIGHT_ZERO/LOW/MEDIUM/HIGH`, `PROMOTE_CLEAN_HOURS = 24`, `weight()` returning `{weight, rung, why, next}`, `rollback_target()` with two exclusion rules, `release_history()`, `_preflight_passed()`, `_drift()`, `routes_diffed()`, `stage()`, `promote()`. You asked to **flip a switch.** This is a four-rung maturity model with a numeric risk score and a 24-hour soak clock, complete with a comment explaining the gaps between constants are reserved for future emitters. Nothing in 303 turns asks for any of it. Keep the symlink swap; the scoring is invention.

**3. Two intake systems, built four days apart, both live.**
The markdown one (`INTAKE.md`, `MANIFEST.md`, `projects/`, `claims/`, `verified/`, `diffs/`, four bucket directories) was built commits `b604f34`→`6dbef0a`. Then `control.py` was built at `3d89b9c` with a SQLite `projects`/`acks`/`releases`/`diffs` schema doing the same job, and its own docstring says the markdown version *"was the mistake."* **The mistake was not deleted.** Every bucket directory is empty except `.keep`. `MANIFEST.md`'s board and `control.db`'s `projects` table are now two sources of truth for project state — the precise disease `FABRIC.md` was written to condemn.

**4. `hub/docs/flarevault-designator.md`.** A designator document for someone else's project, written from an August 2026 relay. FlareVault's session's words, in this repo. You said **"the fucking elephant in the room is this is actually server hubs main objective even if flavorful isn't actually online yet."** Stop carrying their paperwork.

**5. `tools/check-views.py` + `routes_diffed()` + the `_drift()` parser.** A route-registry drift checker, whose output is parsed back out of a text field by regex (`routes:\s*(\d+)\s*drift`) to feed the scoring ladder in #2. Self-referential machinery. Never requested.

**6. The telescope-code namespace reservation block** in `router.py` (modules 00–49 carved up across ServerHub/FlareVault/Metaforge/local, `/api/vault/*` "RESERVED AND DELIBERATELY UNIMPLEMENTED"). Reserving URL space on behalf of two projects that have not asked for it.

**7. `_pending()` is hardcoded.** `registry.py:180` returns one literal dict about the 10020→7100 band move, gated on `if band[0] == 7100`. The PENDING block — the thing you specifically demanded in Step 6 — is a constant in a Python file. It will report that one change forever and will never report the next one.

**8. 1,965 lines uncommitted on six files.** Your memory rule is *"every code change must be committed and pushed immediately, no batching."* `bootstrap.sh` +509, `registry.py` +705, `control.py` +313, `mesh.py` +292, `backup.sh`, `fleet-status.py`. Batched.

---

## ASKED FOR, NOT BUILT — this is the part that matters

**1. There is no outbound. At all.**
`grep -rn "outbox|outbound|send_message" hub/` returns **four hits, all of them the word `outbox/` inside prose in `INTAKE.md`.** No handler, no route, no queue, no writer. `hub/intake/outbox/` contains one `.keep` file.

Your Step 3 — *"DID I NOT SETUP THIS EXCANGE FO U TO USE THE SERVERRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR TO COMMUINCTE WITH A GIVEN PROJECT YES OR NO"* — and your resolved position after the unasked sends — *"NO YOU DO MESSAGE MOTHER FUCKER THATS WHAT I HAVE BEEN SAYIGN THROUGH THE FUCKIGN SERVER."*

What was built instead is a template you are expected to copy-paste by hand into each session, and a REST endpoint a project has to be told to call. **The server cannot initiate. It waits.** The message that was supposed to go *through the server* is a paragraph in a markdown file for you to carry. The one thing that got built in this lane was the thing you did NOT ask for — messages sent without you asking.

**2. Nothing has ever actually run.** Four projects, four rows, all `awaiting`. `acks` table: empty. `claims/`: empty. `diffs/`: empty. `working/`: empty. `closed/`: empty. **Zero intakes have been sent, zero claims received, zero diffs written, zero dispositions recorded, zero acknowledgements.** The entire Step 1→11 loop is scaffolding with nothing in it. The only populated file is `babyhelp.md`, and its own header says *"Intake state: `awaiting` — no claim filed yet."*

**3. Step 12 — circumstance broadcasts — does not exist.** *"MOVING THROUGH INFORMING THEM ABOUT THE CIRCOMSTANCES OF THE SERVER IF PORTS CHANGE"* and *"NOT JUST THAT THE WHOLE FUCKIN EXCAHNGE FOR HOW TO ALSO KNOW WHERE THE FUCKING SERVER IS GOING TO BE HAVING CHANGES OF ALSO ORGINAATION TOOO."* There is no push. A project is only told anything if it polls `/api/registry/<name>`. When the server changes, admitted projects are not informed — they are silently marked stale and have to come asking. That is the inverse of what you described.

**4. Step 1 — the terminals — has no mechanism.** *"I GET ALL THE TERMIALS LINKED UP… ONE EACH AT A TIME TOGETHER."* Nothing in the repo links a session to the server. The intake depends entirely on you being the transport.

**5. THE PREMISE. The installer does not finish the job.**
`bootstrap.sh` is 8 steps and **never calls `enroll.sh`** — `grep -n "enroll" bootstrap.sh` returns nothing. `enroll.sh` still takes `--zone` on every single run. `docs/flareshub-blueprint.md` states your three non-negotiables verbatim (ONE DOMAIN ENTRY / BILATERAL FRONTEND / THE INSTALLER FINISHES THE JOB) and then admits, in its own words, that the current build fails two of the three. **It has been a design document since 2026-09-21 and not one line of it is code.**

So: *"the main point is is that server Hub is to be a full install er for a server complete with like pretty much like no headache."* Run the installer today and you get a hub on `:8765` and a second manual step you must feed a zone to. No domain. No headache-free finish.

**6. ONE app, ONE entry point, the server picker — not built.** *"nooo were saying 1 fucking app thats what we talked about."* `grep` for a fleet/server picker across `hub/ui/registry.js` and `hub/ui-next/src/lib/registry.js`: **zero hits.** `/api/mesh/fleet` returns a fleet; no front end renders one; there is no "log in once, pick which server" screen anywhere. `ui-next/` — the shell that was supposed to become this — says in its own README: **"Status: nothing uses this. Deleting this directory changes nothing else in the repo."**

**7. Two modes of login, no double login — not built.** *"cuase right now its double cloudeflare log in then login again"* (9 restatements). `CAPABILITIES.md` confirms: *"Log in from the internet — Cloudflare Access + Google ⚠️ built, off until HUB_CF_TRUST_IP is set."* Still two logins. And *"Enforce per-route permissions — ⚠️ 52 of 73 routes carry a gate; enforcement is OFF. Arming it locks the UI out."* Every gate number in `router.py` is decoration.

**8. The Tailscale-only failsafe console — not built.** *"while that is still valid at any given time be it cloud flare issues right faile safe"* / *"if one falls over I don't have to go back to cloudflare and get it"* (3 restatements, part 2). No route, no page, no way to re-enter an expired CF token from 5,000 miles away.

**9. The blocking/gating question — still unanswered.** *"BUT THAT BLOCKING SHOULD BE AFTER THE REGARDS TO EVERYTHIGN YES NO OR NO."* Nothing enforces anything; `babyhelp.md` says *"Nothing is enforced. A project can sit stale forever."* That may be the right answer, but it was decided by omission, not by answering you.

**10. "Post-install" — named, never shaped.** `CONSTITUTION.md` §1 declares Install and Post-install are the two halves and §5 says the recipe and the spec *"must become one map"* — 11 steps in `MASTER.md` vs 8 assertions in the preflight, **2 in common.** Still two lists. Still not one map.

**11. The agnostic console.** *"a lot of the server stuff is like anchored to specific services when more or less the console should be actually universal agnostic to any services on a given server."* Nothing in the 40 commits touches this. `hub/app.html` is still the served UI, and `ui-next/README.md` names its pinned-boot-tab bug as *"the rule hub/app.html breaks on the first click of every session."*

---

## VERDICT

**Delete:** `hub/BOM.md` (591 lines, 13 commits stale, admits it violates the constitution it sits beside), `hub/CAPABILITIES.md` (already wrong about sessions), `hub/FABRIC.md` (a taxonomy of a thing that isn't finished), `hub/docs/flarevault-designator.md` (another project's paperwork), and **the entire markdown intake** — `hub/intake/MANIFEST.md` and the four empty bucket directories — because `control.py` already does that job in SQLite and having both is the exact two-sources-of-truth failure these documents were written to condemn. Keep `INTAKE.md`, but strip it to the template and the reply, nothing else. From `control.py`, cut `weight()`, `rollback_target()`, `release_history()`, `routes_diffed()`, `_drift()`, `_preflight_passed()`, the four `WEIGHT_*` constants and `PROMOTE_CLEAN_HOURS` — roughly 190 lines of a risk-scoring model nobody asked for — and keep `stage`/`promote`/`release`, which are the bait-and-switch you asked for twenty-five times. Keep `ui-next/` only if you decide this week that it becomes the shell; otherwise delete it, because its own README says a half-adopted fork is the one outcome that must not happen.

**Build next, in this order:** (1) **Outbound through the server** — a real `POST /api/outbox/<project>` with a queue on disk and a worker that delivers, so the intake message leaves the machine because you pressed something, not because you pasted something; this is Step 3 and it is the hole the entire eleven-step flow sits over. (2) **`_pending()` reads from the `releases` table instead of being a hardcoded dict**, so PENDING reports the next change and not just the one from last Tuesday. (3) **Push on change** — when the master moves or a port band shifts, every admitted project on that server gets told, which is Step 12 and the only thing that makes the registry worth keeping. (4) **`bootstrap.sh` calls `enroll.sh` with the zone read from fleet config, and exits printing a live hostname** — one flow, `install → hostname → reachable`, which is the premise and has never once been attempted in code. (5) Then, and only then, run **one** intake end to end — fksinv, on ksgcohub, fully reconciled — before touching a second project, because four half-done intakes tell you less than one finished one, and right now you have four not-started ones.