# B-36 — Reopen every saved target/family scope in a mixed project

Date: 2026-09-16 · Register: `docs/plans/backlog.md` B-36 · Class CORE · P1.

## Vision alignment

`PROMPT.md` §1's saved decision and §2.5 workflow continuity: a scientist who
saved a mixed selection — two target investigations plus a patent family —
could previously reopen only whichever scope happened to be first in the items
list; the others were unreachable without re-typing the original searches. After
this round, every saved scope of an opened project is one labelled control away
in both views.

## The gap (static finding, confirmed before the fix)

`App.tsx::openProject` opened the first usable item only. The family view's
banner enumerated families alone; the target view's banner had no switcher at
all. A project holding IL6 + TSLP + DEMO-FAMILY-1 opened one scope and gave no
path to the other two.

## Delivered

- `openProjectTarget(project, targetId)` — the target-reopen path extracted from
  `openProject` into the sibling of `openProjectFamily`: sets the saved
  compound pins for exactly that target, restores the saved scope's URL state
  (`t`, `q`, first saved compound as `c`), clears evidence-class filters, and
  cancels any in-flight project navigation so an older response cannot overwrite
  the scope the reader just chose (`apps/web/src/App.tsx`).
- `openedProjectScopes` — every saved scope (families and targets) with its
  saved-item count; scopes whose rows all vanished stay listed and labelled
  rather than dropping out.
- One "Saved scope" switcher, rendered in both banners (family view and target
  view), replacing the families-only select. The target banner now also shows
  the missing/updated drift labels the family banner already showed.

## Verification

- Browser (Playwright against the rebuilt local stack, served build
  `d9f441a-dirty`, viewport 1600×1000): created a project holding one DEMO
  family compound + one IL6 candidate + one TSLP candidate through the real
  dialogs; reopened it from **Projects**; the family scope opened with the
  switcher offering all three; switched to IL6 (target view, banner states
  "reopened from saved target scope", saved compound pinned), to TSLP, and back
  to the family — each switch is one action and the banner keeps labelling the
  open scope. The project's shape was verified in the database (1 family item +
  2 target items across 2 distinct targets); test projects removed afterwards.
- Frontend typecheck + production build green; the B-17 family-view smoke and
  the CI full-stack job (below) pass with the change in the tree.

## Not verified in this round

Owner isolation in the browser (local stack runs with auth disabled; the
projects API is owner-scoped and covered by `test_online03_auth.py`), a
withdrawn candidate inside a reopened target scope (the D2 pin behaviour is
unit-tested; no withdrawal was performed on the operator's stored stack data),
and a genuinely missing scope (the drift label is the same rendering the family
banner already ships).

## Along the way

The B-35 CI full-stack job (run 35113553962) executed this round's frontend
from the same tree: full backend suite **793 passed** on the runner's shipped
db image, served `build_id d9f441a` matched by the recorder, browser smoke
green — recorded as B-35's delivery evidence in the register.
