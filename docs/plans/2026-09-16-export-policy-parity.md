# B-33 — Target screen/export filter and potency-policy parity

Date: 2026-09-16 · Register: `docs/plans/backlog.md` B-33 · Class CORE · P1.

## Vision alignment

`PROMPT.md` §2.5 (workflow continuity: take the current scientific selection to
CSV/SDF with the same meaning) and AGENTS.md §11 (the class is a statement about
the exported compound under the policy recorded in `reference_*`). After this
round, a scientist who filters the candidate table and changes the threshold can
trust that "Current candidates" in the file means the set and the rule the screen
showed. Before it, the file silently widened the set and re-stated the deployment
default policy.

## Browser reproduction (before the fix)

Recorded against the local compose stack (served build identity at the time:
`12aa498-dirty`), the stored IL6 investigation opened via URL state
(`?q=IL6&t=<id>`), viewport 1600×1000, source mode: stored rows only, no live
retrieval re-spent. A throwaway Playwright spec (kept out of the commit; B-38
owns permanent scenarios) drove the UI:

- evidence class filter set to *measured direct binding*, threshold override set
  to 0.001 µM;
- the export menu itself claimed **Current candidates (141)**;
- the downloaded CSV had **157 data rows** — the whole unfiltered scope, 16
  compounds the screen's filter excluded;
- every row's `reference_threshold_nM` read **10000** (the deployment default),
  not the 1 nM the screen stated.

Both halves of the static finding reproduced in a real browser.

## Delivered

- `ExportRequest.evidence_class` (validated against the five-class vocabulary;
  `extra = "forbid"` keeps the contract closed) and a 422 when a family-scope
  export sends it — a filter-looking request must not silently export an
  unfiltered family (`services/core/spago_core/api/routes.py`).
- `collect_candidate_export_rows(..., evidence_class=...)` applies the same
  `current_measurements` existence clause `list_candidates` applies, so the
  exported set is the set the screen's filter produced
  (`services/core/spago_core/services/export.py`). An explicit selection is not
  re-filtered — selection wins, the same contract modality already follows.
- The frontend passes the screen's state through: `ExportMenu` gains
  `activityThresholdNanomolar` / `evidenceClass`, `api.exportFile` carries
  `activity_threshold_nm` / `evidence_class`, and `App.tsx` passes the live
  `referenceThresholdNanomolar` and `evidenceClassFilter`
  (`apps/web/src/App.tsx`, `components/ExportMenu.tsx`, `api/client.ts`).
- The export menu's target-scope hint now states the rule truthfully: current
  results export under the active filter and threshold; a selection exports the
  chosen compounds under the same threshold even when a filter would exclude
  them (the previous hint claimed evidence class already traveled — it did not).

## Semantics decided (the item's open question)

- **Threshold** is the policy behind the class columns, not a row filter: it
  applies to both scopes, exactly as on screen (the screen computes every
  visible class under it).
- **Evidence class** is a scope constructor: results scope only. An explicit
  selection names its own rows and is not re-filtered — mirroring the table,
  where pinned/saved rows stay visible as labelled outsiders under a filter.

## Verification

- `services/core/tests/test_b33_export_parity.py` — 8 cases: per-class export ==
  screen set, a strict-subset class exists and narrows the export, modality
  focus + evidence filter combine into one scope, threshold override travels to
  every row (`reference_threshold_nM == 1`), default keeps 10000, selection is
  not re-filtered but carries the policy, unknown class refused 422, family
  scope + evidence class refused 422.
- Regression: `test_export_scope.py test_m1_projects_export.py
  test_online00_api.py test_online06_reference.py test_b34_build_identity.py
  test_b33_export_parity.py` → **104 passed**.
- Browser, after the fix, same stack/viewport/source mode: results scope
  **141 = 141 rows**, file `reference_threshold_nM` = **1**; selection scope
  with the filter active: **1 row exactly as chosen**, threshold **1** in the
  file. CSV contents compared, not just filenames.

## Found along the way (recorded, not fixed here)

At a 720 px-tall viewport the target view's accumulated header content
(TargetHeader + ReferenceStrip + candidate filters) exceeds the workspace, and
flex shrink collapses `.table-panel` to ~32 px — the virtual candidate table
renders **zero rows** while its footer still says "1–100 of 141". At 1600×1000
the table lays out normally. Recorded as a new backlog item (B-42): short
viewports must not make the candidate table disappear, and the recorded
viewport dependence belongs in its fix evidence.

## Not verified

SDF parity asserted only at the unit level (row collection is shared; only the
renderer differs). No live-source calls were made or needed. Empty-input and
bounds paths are covered by the existing `test_export_scope.py` refusal cases.
