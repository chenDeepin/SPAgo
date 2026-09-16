# B-04 — Import refresh completeness and interrupted-import resume

> Archived 2026-09-17 — round closed. Delivered record and open remainder: [backlog register](../plans/backlog.md) §1–§2.

Date: 2026-09-16 · Backlog item: B-04 (NEXT, P2 head, ungated) · Status: **delivered
2026-09-16** — full suite 773 → 779 all passing; backlog §1 records the artifact.

## Problem (from the register)

D4 retracts `compound_mentions` + `evidence_records` only (`seed.py`); measurements a
release drops stay current. D5 marks a dead job `interrupted`, but the record does not
show which run completed the work, and README/runbook still state the limitation as
open ("refresh does not yet retract …; an interrupted import job has no recovery
protocol").

## Scope

1. **Measurement retraction in the corpus path.** A bioactivity fixture load *is* the
   whole content of its source, so its rule is source-scoped (the mention/evidence rule
   is document-scoped because a package carries the whole source content *for the
   documents it holds*): after an ingest whose activity release is version V, rows of
   that activity source still at another version are retracted — `retracted_at`,
   `retracted_reason = "not in dataset_version V"`, `retracted_by_dataset_version = V`
   (new column, migration 0020) — never deleted; rows V carries again are restored
   first, the same identity rule hand-added rows follow. Hand-added rows
   (`user_supplement`) carry a different source name and are never touched. A package
   that carries no bioactivity source retracts nothing.
2. **Compounds are identity, not mappings.** A compound row is never retracted: it is
   keyed by InChIKey, shared across sources and referenced by projects. What a release
   drops is the compound's *occurrences* — its mention (existing rule), its evidence
   (existing rule), its measurements (this round) — and every current read joins
   through those, so a fully dropped compound leaves every current surface while the
   identity row stays readable as history. Test proves that shape.
3. **Current-state reads.** `bioactivity.py::compound_activity` / `family_activity`
   read the `measurements` base table, so a withdrawn hand-added row renders today.
   They move to `current_measurements`, as do `ai.py`'s family/document measurement
   totals and rows; `discovery.py`'s evidence-class filter gains `retracted_at IS NULL`.
   (`coverage.py` and `supplements.py` already state their own filters.)
4. **Resume is a recorded re-run.** Import is one transaction per package, so a killed
   run wrote nothing; resume = re-running the same command (stable ids + upserts: no
   duplicates). The completed job's summary names the interrupted jobs whose package it
   re-imported (file-checksum equality), so the resume is visible in the record, not
   folklore. `scripts/corpus_batch.py` already resumes at chunk level from STATE.json;
   the runbook states both policies.

## Out of scope (stated)

- Document-level retraction ("the release no longer contains this document at all"):
  absence beyond the documents a package holds is the same absence problem B-30 defers
  for source refreshes; it needs its own design.
- Retracting `targets`/`assays`/`compounds` rows: dimension/identity tables, not
  mappings; retraction would misstate identity as absence.

## Files

- `migrations/0020_measurement_retraction.sql` — `measurements.retracted_by_dataset_version`,
  recreate the m.* views (`current_measurements`, `investigation_measurements`).
- `spago_core/seed.py` — `SeedReport.retracted_measurements`, restore-then-retract for
  the activity source.
- `spago_core/import_package.py` — recovered job ids, `resumed_jobs` in the summary,
  `retracted_measurements` in the summary.
- `services/bioactivity.py`, `services/ai.py`, `services/discovery.py` — current-state
  reads.
- `tests/test_b04_import_refresh.py` — the round's tests.
- `README.md`, `docs/runbook.md`, `AGENTS.md` §10, `docs/plans/backlog.md` — contract
  updates.

## Verification

- Full backend suite against the scratch database; the new tests cover: measurement
  retraction + restore, hand-added rows untouched, compound fully dropped leaves the
  family page but keeps identity, current-state reads exclude withdrawn rows, resume
  recorded without duplicates, an unknown interrupted job not claimed as resumed.
- `rtk git diff --check`; frontend build untouched (no web changes).
