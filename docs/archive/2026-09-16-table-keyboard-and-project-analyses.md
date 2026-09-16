# B-19 + B-29 — Table keyboard accessibility; a stored analysis as a project artifact

> Archived 2026-09-17 — B-19 and B-29 delivered; the screen-reader announcement pass is register item **B-44**.

Date: 2026-09-16 · Register: `docs/plans/backlog.md` B-19, B-29 · Class NEXT · P2.

## Vision alignment

B-19 (`PROMPT.md` §2.5 / AGENTS.md §3): a scientist who operates by keyboard
keeps inspection, selection and export in the existing layout — the tables'
existing actions become correctly operable, no new controls. B-29
(`PROMPT.md` §1's saved decision): the analysis that explains a selection
travels with the project instead of being copied out by hand and losing its
scope/version header.

## B-19 — keyboard and table semantics

Both virtualized tables (`CompoundTable.tsx`, `CandidateTable.tsx`):

- The `role="table"` container (name + `aria-rowcount`) now owns its header
  row (moved onto the `.table-scroll` div; the body became `role="rowgroup"`),
  and every header cell is a `role="columnheader"` — the header previously sat
  outside the table it claimed to head.
- Row key handling gained one guard — `if (e.target !== e.currentTarget)
  return;` — so nested focusable controls own their keys: Space on a row
  checkbox toggles exactly the selection (previously the row handler ate the
  key *and* fired inspection, so the checkbox never toggled), Enter on a row
  still inspects, and keys on the structure button / source-record links /
  select-all no longer leak into row inspection.
- No CSS or layout change: the same elements kept the same parents and styles;
  the global `:focus-visible` outline already covers the rows' `tabIndex={0}`.
- The smoke's data-row locator was scoped to the rowgroup (the header is now
  the table's first row — the cross-workstream catch from the implementation
  round, fixed before it could break CI).

**Verification** (rebuilt stack, `a8a0c4e-dirty`, Chromium 1600×1000):
header owned by the table (`ownsHeader: true`), 6 columnheaders + 1 rowgroup
in the DOM, row Enter opens the evidence inspector, and Space on a row
checkbox toggles the selection with **no** inspector opening
(`spaceTogglesOnly: true`). The B-17 smoke passes on the new markup. Not
covered: a screen-reader pass (announcements were not recorded) — the
structure the reader consumes is now correct, but AT evidence remains open.

## B-29 — stored analyses as project artifacts

- Migration `0022_project_analyses.sql`: a project references analyses by id
  with the identity snapshot at attach time (scope, label, provider, model,
  prompt + dataset version, analysis timestamp) — a vanished analysis row
  leaves a readable, marked reference, the migration-0008 contract applied to
  analyses.
- Service (`projects.py`): `attach_analysis` (idempotent; the analysis must
  exist and belong to the same owner), `list_project_analyses` (live join only
  to detect a missing row), `remove_project_analysis` (removes the pointer,
  never the artifact).
- Routes: `POST /projects/{id}/analyses` (201), `DELETE
  /projects/{id}/analyses/{ref}` (204), and `analyses` on the project detail.
- UI: the Analyses dialog attaches a stored analysis to a project from the
  expanded entry (progressive disclosure — an earlier draft rendered the
  control on every row and was fixed before commit); both project banners show
  "Saved analyses (N)"; `ProjectAnalysesDialog` reads the stored text with its
  staleness statement and export — a pure read, no provider call — and marks a
  gone reference from its snapshot.

**Verification**: `tests/test_b29_project_analyses.py` (5 cases: attach/list/
read-back without a provider, idempotency, unknown analysis 404, remove leaves
the artifact, vanished row leaves a marked readable reference with a clean 404
on the direct read); regression `test_analysis_history + test_project_versions
+ test_m1_projects_export + b29` → 41 passed. Browser on the rebuilt stack:
attach from the dialog (outcome shown), the reopened project banner offers
"Saved analyses (1)", and reading renders the stored text
(`readStoredText: true`); the test project was deleted afterwards. Owner
isolation is API-level here (local auth disabled), consistent with B-36's
recording.

## Deliberate limits

The project export keeps its current shape; the analysis export (with its
scope/model/prompt header) is reachable from the project view's dialog, which
is what B-29's acceptance asked to preserve. No analysis deletion UI exists —
the missing-row path is tested at the storage layer where it will meet one.
