# B-02 — Live source-declared patent linkage (plan, 2026-09-16)

> Archived 2026-09-17 — round closed. Delivered record and open remainder: [backlog register](../plans/backlog.md) §1–§2.

Backlog item `docs/plans/backlog.md` B-02, the P1 item after B-10. Vision check: it
serves `PROMPT.md` §2 (`patents → structures → bioactivity → evidence`) and `AGENTS.md`
§9/§10/§11 — the product's central relation is "this compound, in this document", and
the rules require a source-declared patent and a corpus occurrence to stay two labelled
facts. What a user can do afterwards that they cannot do now: see, for a target's
retrieval, how much of what a source returned can actually be linked to a patent/DOI and
*why the rest cannot* — so "no patent" stops being read as "this compound is not
patented".

## What is already there (read before planning)

- `ChEMBLDiscoveryAdapter` resolves `document_chembl_id` → patent/DOI/PMID
  (`documents()`, `_attach_document_references`, bounded by `MAX_DOCUMENT_LOOKUPS`) and
  stores them on `measurements.document_*` (migration 0013).
- The candidate table shows `N occurrences` (corpus) and `source declares <number>` as
  two separate lines; the measurement context line shows `patent declared by source …`;
  the CSV/SDF export has `patent_numbers` and `source_declared_patents` as separate
  columns. The display/export half of B-02 is therefore already shape-correct.

## The three real gaps

1. **Nothing counts what happened.** `_attach_document_references` sets the fields it
   can and leaves the rest `None` — a record whose document the source never returned is
   indistinguishable, in the stored data, from one whose document carries no patent
   field. Only the bound-reached case leaves a sentence in `warnings`.
2. **Warnings never reach a reader.** `SourceRetrieval.warnings` is persisted and
   returned by the API, and no frontend component renders it (verified: no `warnings` in
   `apps/web/src`). "A bound being reached is reported" is false in the UI today.
3. **No live declaration measurement on the acceptance cohort**, which is the item's
   acceptance sketch and the honest input to the capability statement.

## Plan

| Step | Change | File |
| --- | --- | --- |
| 1 | Per-record outcome + disjoint tally over kept records | `adapters/bioactivity_base.py`, `adapters/chembl_discovery.py` |
| 2 | Persist the tally per retrieval (forward-only migration + comment) | `migrations/0016_reference_counts.sql`, `domain/models.py`, `services/discovery.py` |
| 3 | Read path: service reads and API response | `services/discovery.py`, `api/routes.py` |
| 4 | Surface: per-target collapsed source notes + reference coverage (the warnings that were invisible) | `apps/web/src/components/TargetHeader.tsx`, `api/types.ts`, `styles.css` |
| 5 | Operator artifact: live declaration measurement on the acceptance cohort | `scripts/cohort_coverage.py` (`--declarations`), `benchmarks/*` |
| 6 | Tests, docs, plan record | `tests/`, `docs/`, `README.md` |

### Vocabulary (disjoint buckets, one per kept record)

`patent_declared` · `doi_only` · `pmid_only` · `no_reference_on_document` ·
`document_unknown_to_source` · `document_not_retrieved_bound` ·
`document_not_retrieved_failure` · `activity_without_document`

Ordered by strength (patent > DOI > PMID); a record lands in exactly one bucket, so
`sum(counts) == records_kept` holds as a testable invariant. Per-record detail stays in
the `measurements` columns; the tally is a summary and says so.

Rejected alternatives: a per-record column in `measurements` (the outcome is a property
of the retrieval, not of the measurement, and would double-store); counting inside each
`activities()` call and summing (a record reachable through two ChEMBL target ids would
be counted twice — the tally is computed after the service's dedup); a second table
(jsonb column on the row that already owns the retrieval is the smallest honest shape).

### Live measurement (`--declarations`)

Read-only and bounded: re-resolve each cohort query, take the ChEMBL target ids the
stored scope recorded, fetch activities through the shipped adapter, tally by unique
`activity_id`, write nothing to the database. Writes a dated artifact under
`benchmarks/` for the acceptance record. The measured run is the artifact; a fixture
pass is not a live pass (§0).

## Verification plan

- Unit: every bucket, the sum invariant, the bound-reached case distinguished from "no
  reference", a failed lookup not reported as "no patent", and a record reachable
  through two target ids counted once.
- Integration: `investigate` → `source_retrievals.reference_counts` → API response.
- Live: `--declarations` on the acceptance cohort; per-source counts recorded in
  `benchmarks/`.
- Browser: the source notes and the coverage line render; the declared patent and the
  corpus occurrence remain two labelled things in the table, the panel and the export.

## Status

Implemented and verified 2026-09-16.

## Result

**What changed, and where.**

| Area | File | Change |
| --- | --- | --- |
| Vocabulary | `services/core/spago_core/domain/document_refs.py` (new) | The nine statuses, their meanings, the "missing" subset, and the two functions: `declared_reference_status(record)` (strongest declared reference) and `document_reference_counts(records)` (the disjoint tally) |
| Adapter | `adapters/bioactivity_base.py` | `ActivityRecord.document_reference_status`, `ActivityResult.document_reference_counts` |
| Adapter | `adapters/chembl_discovery.py` | `documents()` returns a `DocumentLookups` dataclass (`metadata`, `warnings`, `unresolved` → reason); `_attach_document_references` stamps each record; the result carries the tally |
| Service | `services/discovery.py` | `_tally_references` static method, called by all three source runners **after** the per-source dedup; `reference_counts` selected by `list_source_retrievals` and `coverage_matrix` |
| Storage | `migrations/0016_reference_counts.sql` (new), `domain/models.py` | `source_retrievals.reference_counts jsonb` (forward-only, default `{}`); `SourceRetrieval.reference_counts` |
| API | `api/routes.py` | `reference_counts` on `RetrievalResponse` and `CoverageMatrixRow` |
| UI | `components/TargetHeader.tsx`, `api/types.ts`, `styles.css` | The *Source notes and reference coverage* disclosure: per-source counts in strength order plus the retrieval's warnings |
| Operator | `scripts/cohort_coverage.py` | `--declarations` (live, read-only, refuses with `--investigate`), `--max-activities`; the stored matrix now renders the stored counts |
| Evidence | `benchmarks/reference-declarations-2026-09-16.{md,json}` (new) | The live measurement below |

**Deviations from the plan, and why.**

1. *The tally is computed in the service, not in each adapter.* Planned as an adapter
   output; moved after the first attempt because a ChEMBL measurement reachable through
   two target ids (CD40LG's `CHEMBL4106121/2`, EGFR's `CHEMBL2111431`) is de-duplicated
   in the service — counting in the adapter would have counted it twice. The service now
   owns one meaning of the tally for every source, including the sources whose adapters do
   no second document lookup (they report `no_reference_from_source`).
2. *`--declarations` was extended past the plan.* The plan asked for the counts; the run
   exposed that the stored matrix had no way to show them either, so `_render` now prints
   the stored counts, and `--declarations` writes the same tallies from live data.
3. *A pre-existing defect was fixed on the way.* Gap 2 of this item (warnings persisted,
   served, rendered nowhere) is closed by the same disclosure.

**Live measurement** (`benchmarks/reference-declarations-2026-09-16.md`, 2,696 kept
records, 39 s for five targets, live upstream calls, nothing written):

| Target | Kept | `patent_declared` | `doi_only` | `document_unknown_to_source` |
| --- | --- | --- | --- | --- |
| TSLP | 111 | 0 | 111 | 0 |
| CD40LG | 21 | 0 | 21 | 0 |
| IL6 | 166 | **135** | 31 | 0 |
| IL6R | 1 | 0 | 1 | 0 |
| EGFR | 2,397 | 0 | 1,187 | 1,210 |

The previous handoff could not point at a live number for its central
"patents → compounds" claim. It now can, for one target, and the same run says plainly
why the other four cannot: ChEMBL declares DOIs, not patents, for them — and for EGFR
1,210 of the records cite a document ChEMBL does not return, with CHEMBL203 stopping at
the 2,000-activity bound. None of it is a corpus occurrence.

**Verification.**

- Backend suite: 560 tests, all passing (13 of them new in
  `tests/test_b02_declarations.py`: the sum-over-buckets invariant, unknown status
  rejected, the bound named rather than reported as "no patent", a failed lookup counted
  as a failure, a record with no document counted as such, excluded records kept out of
  the tally, a twice-reachable measurement counted once, a retrieval without the tally
  reported as "not recorded", and the source that natively declares a reference).
- Frontend: production build clean (`tsc -b && vite build`).
- Migration applied on the running compose stack (advisory lock + `0016`), and the
  column verified populated after a real IL-6 investigation (`psql` read of
  `source_retrievals.reference_counts`).
- Browser (localhost:8000, 1440×900, current checkout serving the rebuilt bundle): the
  IL-6 target view's *Source notes and reference coverage* disclosure renders
  `bindingdb` "9 the source row carried no reference" and `chembl` "135 with a
  source-declared patent", "31 DOI only, no patent" — the same numbers the live
  measurement independently produced.
- Export: the candidate CSV still carries `patent_numbers` and
  `source_declared_patents` as separate columns, verified on the same view.
- Not checked: no cross-read of whether a declared patent number is the *right* patent
  for the assay (that is the invited user's job, `docs/online-capability.md` §6), and
  the DOI→patent gap is measured for ChEMBL only; BindingDB's rows carry no reference to
  resolve.
