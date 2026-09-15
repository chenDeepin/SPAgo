# Round plan — defect round: investigation scope, withdrawal, refresh integrity (2026-09-16)

> Archived 2026-09-16 (all defects D1–D10 implemented, tested and shipped; the
> focused fixes D9/D10 landed in the backlog round's commit with
> `benchmarks/online01-llm-eval-2026-09-16-sparse.md` and the demo deep link).
> What was deferred there is delivered in
> [the backlog round](2026-09-16-backlog-round.md) §5; the capability gate stays in
> `docs/online-capability.md` §6.

Status (at the time of writing): **active**. Owner: coordinating agent. Baseline
commit: `9848e5c`.

Inputs: the user's request (point three acceptance pointers at
`docs/online-capability.md`; walk the product as a real external user with the browser;
fix the defects; then deliver the remaining backlog by priority), the ONLINE-07
findings section of `docs/plans/2026-09-15-bindingdb-io-port.md` §8, and the
browser pass recorded in §2 below.

---

## 1. Pointer change (done)

The live gate is `docs/online-capability.md` §6 (checklist + invited-user
script). Three pointers were repointed to it and now describe the gate rather than
the archived register:

| Pointer | Before | After |
| --- | --- | --- |
| `PROMPT.md` §20 "First Engineering Task" | "the next work is ONLINE-04/ONLINE-05 in the beta acceptance record" | "the gate the next work has to satisfy is `docs/online-capability.md` §6" |
| `docs/plans/2026-09-15-online-llm.md` §4 | gate in capability §6 **and** the dated register linked as the record | gate + script in capability §6; that section is what a deployment is checked against |
| `docs/online-capability.md` §6 | "The gate itself. The dated register … is [the beta acceptance record]" | "This section is the gate: this checklist and the script below"; the archived register is named as history, not as the gate |

`PROMPT.md` (handoff block, ×2) and `README.md` (± the milestone table) already
pointed at capability §6. The dated register stays in
`docs/archive/2026-09-15-beta-acceptance.md` and is referred to only as a past run.

## 1b. Defect fixes (D1–D8, all landed with tests)

| id | fix | where | test |
| --- | --- | --- | --- |
| D1 | Measurements are scoped by an explicit `target_relations` row: the `investigation_measurements` view keeps a measurement when its assay target *is* the investigation target or a related member, so an unrelated target's number can no longer be aggregated into this target's verdict, drawer, export or AI snapshot | `migrations/0015_*`, `services/discovery.py`, `services/reference.py`, `services/plan_execution.py`, `services/ai.py`, `services/export.py` | `tests/test_investigation_scope.py` |
| D2 | No silent scope flip on reopening a project; the selected compound **and every item the project saved for that target** come back as labelled `outside_filter` rows (repeatable `include_compound_id`), while the filter, counts and total stay as the reader set them | `apps/web/src/App.tsx`, `api/client.ts`, `api/routes.py`, `services/discovery.py`, `CandidateTable.tsx` | `TestPinnedCompound` (incl. the two-item project case) |
| D3 | A hand-added row can be taken back with a required reason: `measurements`/`target_supplement_remarks` carry `retracted_at`/`retracted_reason`, the verdict reports `withdrawn_supplements`, the dialog lists withdrawn rows with their reason, and re-posting the same row restores it | `services/supplements.py`, `api/routes.py`, `SupplementDialog.tsx`, `TakeBackControl.tsx`, `TargetEvidencePanel.tsx` | `TestWithdrawal`, `test_online07_supplements.py` |
| D4 | A source refresh retracts what the release no longer contains (mention + evidence), stamped with the version that dropped it; a later release carrying the row again restores it. Bookkeeping is guarded on the 0015 columns so the forward-upgrade tests can still seed an older schema | `seed.py` | `test_real_source_import.py::test_a_release_that_drops_a_row_retracts_it` |
| D5 | A killed import is recoverable: a new import marks stale `running` jobs `interrupted` with a reason and a finish time, and `import_package --status` lists jobs | `import_package.py` | `test_real_source_import.py::test_a_killed_import_is_recovered_as_interrupted` |
| D6 | ChEMBL activity requests carry an explicit field projection | `adapters/chembl_discovery.py` | `test_online00_discovery.py` request-capture test |
| D7 | `target_construct` is gone from the contract, the domain model and the write path: no adapter can map a construct, so nothing promises one. `measurements.construct` stays migrated, written and read by nothing | `adapters/bioactivity_base.py`, `domain/models.py`, `services/discovery.py`, capability §8 | full-suite regression |
| D8 | The class-scoped fixture is a classmethod again (pytest 10) | `tests/test_online01_scoped_summaries.py` | full-suite regression |

Spec change worth naming: D2 pins **all** compounds a project saved, not just the
first one. The walkthrough below is what showed the difference — a project holding a
small molecule and a peptide reopened with the small-molecule scope, and the peptide
was saved but invisible. One saved item is not a special case of the rule.


## 2. Browser pass — external user, local build, 2026-09-16 01:44–01:55 CST

Served from the checkout at `9848e5c`, container `app` (healthy), live sources
(UniProt + ChEMBL + BindingDB + PubChem) and the configured DeepSeek endpoint.
Screenshots: `docs/plans/ui-round-verification/walkthrough-01-target-1220.png`,
`walkthrough-02-supplement-dialog-1220.png` (folder is gitignored: it shows live
target data).

Steps exercised: open → resolve `TSLP` (`Q969D9`) → review the plan → Run →
read scope, coverage and reference set → inspect a candidate's evidence → save one
candidate to a **new** project → reopen the project from the drawer → export CSV
(current candidates).

What worked: plan-then-Run is the only way a query runs; the related receptors are
offered, not merged; per-source coverage states kept/excluded counts; the potency
strip states policy, threshold and gaps; the evidence drawer groups by assay and
labels each group with its own target; the save dialog saves a target-scoped item
with an identity snapshot; the reopened project banner names the saved scope; the
export CSV carries per-source dataset versions, provenance states, the class under
the stated policy and the verdict sentence with `reference_threshold_nM` and
`reference_policy_version`.

### Pass #2 — after the defect fixes (2026-09-16 02:20–02:35 CST)

Rebuilt image from this working tree (`docker compose up -d --build`), same live
sources. Everything below was observed in the served build, not in the source:

- **D1 behaviourally fixed.** The TSLP strip now reads "Strongest reports: IC50
  250 nM" — the unrelated `DEMO-TARGET-1` value (IC50 4100 nM) that pass #1 saw is
  gone from the target's own numbers, and the strip's counts (2 in-scope compounds,
  1 at or below 10 µM, 1 not a potency, 53 actives outside the modality scope) match
  the drawer's per-assay groups.
- **D3 behaviourally fixed.** "Add a row by hand" → the stored acceptance remark
  shows its note and value; taken back through the new control with a typed reason
  ("typed to prove the take-back path during acceptance"). Result, read back from the
  page: the verdict sentence becomes "… the retrieved set can serve as a potency
  reference for this target. **1 hand-added row(s) were withdrawn by the user and are
  not counted**", the remark chip disappears, the row stays readable under "Taken back
  by you" with its reason and timestamp and the restore hint, and the same control
  appears in the candidate's measurement table for hand-added measurements
  ("Take back this row").
- **D2 behaviourally fixed, and one gap found by doing it.** A new project received a
  small molecule, then (with the modality filter turned on by hand) a peptide.
  Reopened with the filter off: the banner reads "2 saved items · reopened from saved
  target scope", the footer still reads "Showing small molecules and unclassified
  entities", and the peptide is back as a labelled row — "outside the current filter —
  shown because it is saved or selected". Pass #2 with only the *first* item pinned
  showed the gap: the second saved item was invisible. The rule is now every saved
  compound of the project (`include_compound_id` repeatable), with the footer saying
  "· 1 outside the current filter (shown, not counted)" so the row count and the total
  cannot contradict each other.

Screenshots of pass #2 (gitignored folder, live target data):
`walkthrough-03-target-scope.png`, `walkthrough-04-pinned-peptide.png`.

Not re-run in pass #2: export CSV, AI summary and the family/document paths — they
are unchanged by this round and were covered in pass #1; the suite covers the export
contract.

### Findings (all reproduced live, then confirmed in the code)

| id | finding | evidence | severity |
| --- | --- | --- | --- |
| D1 | **A target's investigation counts measurements of the same compound against *unrelated* targets.** The TSLP strip showed "Strongest reports: IC50 250 nM, **IC50 4100 nM**"; the drawer showed the second value as `Demo cyclooxygenase (synthetic) · DEMO-ASSAY-1 · IC50 4100 nM` — a different target entirely. `list_target_measurements`, `reference._rows`, `plan_execution` and the AI target snapshot all join measurements to `target_candidates` **by compound**, so any measurement of a candidate compound, for any target, is aggregated into this target's counts. | DB: `targets` shows TSLP 112 measurements and a separate `DEMO-TARGET-1`; screenshot 01; `rg "compound_id = tc.compound_id"` | high — a cross-target number was presented as this target's potency, in the verdict sentence and in the exported CSV |
| D2 | **Reopening a target-scoped project silently widens the modality scope.** Before reopening: footer "Showing small molecules and unclassified entities", 2 candidates, "1 of 2 in-scope compound(s) at or below 10 µM", "53 active outside the modality scope". After reopening the same project (no new retrieval — `source_retrievals` still holds one row per source): toggle checked, footer "Showing all modalities", 70 candidates, and the strip's strongest reports became peptide `KD 2–4 nM`. Cause: `App.tsx` `openProject` calls `setAllModalities(true)` unconditionally for a target item. | app log (`/reference?include_all_modalities=true` after the project GET), `source_retrievals.retrieved_at` unchanged, screenshots, `App.tsx:666` | high — the reader's scope changed without a control being touched, and the verdict sentence changed with it |
| D3 | **Hand-added rows cannot be withdrawn or corrected.** The dialog lists "Stored remarks for this target" as text only; a hand-added *measurement* is a candidate row with no action either. The acceptance row itself ("placeholder value typed to exercise the add-rows path") is stuck in the target forever. | screenshot 02; `rg -n "delete\|withdraw" services/core/spago_core/services/supplements.py` | medium — the user owns the row and must be able to take it back |

Carried forward from ONLINE-07 §8 (confirmed still true by grep): no delete/correct
path (D3), refresh does not retract (D4), interrupted import has no recovery (D5),
ChEMBL activity pages are fetched without an `only=` projection (D6),
`target_construct` is never populated (D7), and one test fixture is a class-scoped
fixture written as an instance method (D8, breaks on pytest 10).

## 3. Defence order (each step lands with its own test before the next)

1. **D8** — fixture style, trivial, unblocks a clean suite.
2. **D6** — `only=` projection on the ChEMBL activity fetch; measure the payload
   difference against the live API and record it; assert the projection in a
   request-capturing test.
3. **D7** — decide and act on `target_construct`: no adapter can fill it, so stop
   surfacing it as a field the reader expects a source to supply.
4. **D1** — one rule, one place: a `target_relations` row for every interaction /
   complex target a retrieval attaches measurements to, plus an
   `investigation_measurements` view (`assay_target = investigation target OR
   related target`) that every target-scoped read uses: verdict, drawer, candidate
   count, retrieval evidence-class groups, AI snapshot totals, target export.
   Tests: the interaction-target measurement stays in scope (existing test), a
   measurement on an unrelated target is excluded (new test reproducing D1).
5. **D2** — remove the silent scope flip; keep the saved item visible through the
   labelled scope note instead.
6. **D3+D4** — retraction as one mechanism with two triggers: user withdrawal
   (supplement measurement or remark) and source refresh (patent-side mentions and
   evidence the new package no longer contains). Retracted rows are excluded from
   current reads, counted and reported (never silently dropped).
7. **D5** — `interrupted` job state plus a recovery call, so a killed import is
   visible instead of leaving a `running` row forever.
8. Browser pass #2 on the rebuilt image to verify D1/D2/D3 behaviourally.

## 4. Backlog after this round (priority order, from `PROMPT.md` §16)

- ONLINE-04/05 hosted acceptance (operator: host, TLS, seed mode, invited user).
- ONLINE-06 next inputs: coverage matrix for the invited cohort; latency/cost budget
  on the chosen host.
- Deferred by rule, not by omission: OCSR (AGENTS.md §30 — needs a measured coverage
  gap first), Markush search claims (§31), Ketcher-class editing UI (§23 dependency
  review; the current depiction/editor split is deliberate).

## 5. Verification

- Backend: full `pytest` suite in the container; new tests per defect.
- Frontend: `tsc` + build.
- Browser: pass #2 on the rebuilt image, with the recorded screenshots.
- Text: `git diff --check`.

## 6. Results

- **D1–D8 landed in `194e953`** with the tests named in §1b; the full backend suite
  passed at that commit, and the frontend built clean.
- **D9 (the citation contract) and D10 (the demo deep link) were found after that
  commit** — D9 by the sparse-scope evaluation, D10 by cold-loading the demo deep link
  in the browser — and are fixed in the commit that closed the backlog round, with
  `benchmarks/online01-llm-eval-2026-09-16-sparse.md` as the before/after record.
- The pointer change in §1 is in `194e953`; `docs/online-capability.md` §6 is now the
  gate, and the archived beta-acceptance register is history.
- Browser pass #2 (§2) is the behavioural evidence: both screenshots of the pass are
  local (`docs/plans/ui-round-verification/`, gitignored by design).
- Left open, deliberately: the hosted acceptance gates and the operator's latency/cost
  targets — see `docs/online-capability.md` §6 and `docs/runbook.md` §H9.
