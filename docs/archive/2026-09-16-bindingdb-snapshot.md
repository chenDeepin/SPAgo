# B-23 — Local BindingDB snapshot search (TSV first)

> Archived 2026-09-17 — B-23 delivered; the operator gate on the file's terms, its location and any future release is unchanged. Delivered record and open remainder: [backlog register](../plans/backlog.md) §1–§2.

Round opened 2026-09-16. Class **NEXT · P1 · M (TSV)**. Register entry:
`docs/plans/backlog.md` §B-23. Port source (read-only, author's own project):
`/media/chen/Machine_Disk/Datasets/BindingDB_IO/bindingdb_io/readers/{tsv,multi}.py`,
`match.py`, `targets.py`, `patents.py`. Operator dataset (outside the repo, §34):
`/media/chen/Machine_Disk/Datasets/BindingDB_All_2609.tsv` (8.9 GB, 640 columns,
3.2 M data rows).

## What a user can do afterwards that they cannot do now

On a workstation that holds the dump, ask a target against the *whole* BindingDB
release with no upstream call and no rate limit, and see in the target view that the
answer came from that file — release, file digest, rows scanned, match mode and the
aliases used — next to the bounded REST answer, so a thin REST result can be checked
against a complete local one instead of being taken on trust.

## The problem, in the current checkout

`adapters/bindingdb_rest.py` is the only BindingDB path. `getLigandsByUniprot` returns
what it returns within its caps (IL6: 9 rows), states no unit, no organism and no
assay context, and cannot be checked against anything else in the build. The research
workflow this product serves already keeps the full local snapshot and searches it
directly; SPAgo has no reader for it, no way to record which release answered, and no
way to tell a zero result from a partial scan.

## Decisions

- **D1 — One source, two access paths, and the version says which.** The snapshot is
  BindingDB, so it is recorded as `source_name="bindingdb"` — not a fourth chip in the
  coverage matrix and not a second concept for a reader. What differs is the access
  path, and that is what the version fields carry: `source_version="bindingdb-snapshot-tsv"`
  (vs. `bindingdb-rest`) and `dataset_version="bindingdb-snapshot:<release>"`, both on
  the retrieval row *and* on every measurement row, so a stored number can always be
  traced to the file it came from (§10/§25).
- **D2 — Operator-only, never an interactive path.** The app keeps the REST adapter;
  the snapshot adapter is constructed *only* by `scripts/bindingdb_snapshot.py`. A
  config knob that made the running app scan a multi-GB file inside `POST /targets/discover`
  would violate §21, so no such knob exists. The stored rows are visible in the app
  afterwards (they are ordinary measurements of that target) — the *scan* is not
  reachable from a browser.
- **D3 — Accession first, name second, and never substring by default.** The dump's
  `Target Name` is often a construct (`Dimer of Gag-Pol polyprotein [501-599]`), so
  the reviewed UniProt accession is the primary match: every
  `UniProt (SwissProt|TrEMBL) Primary ID / Secondary ID(s) / Alternative ID(s) of
  Target Chain N` column is checked (N = 1…50). Names are a *secondary* exact
  (case-folded equality) match from the target's own reviewed labels — its `name`,
  `gene_symbol` and `aliases`. The source project's looser substring matching
  ("interleukin-6" ⊂ "Interleukin-6 receptor subunit alpha") merges a *related*
  target's rows and is therefore not the default; `--name-mode contains` runs it
  deliberately, and the report always says how many rows matched by which rule.
- **D4 — Species is filtered, counted and stated.** The dump carries
  `Target Source Organism …`; the REST path cannot. Rows whose organism is neither the
  target's own nor unstated are excluded and counted (`organism_mismatch`), and the
  report names them — mixing a rat assay into a human reference set is a silent
  scientific error (§11), not a coverage gain. `--all-organisms` widens it explicitly.
- **D5 — One record per (row, endpoint), value as reported.** Each filled potency
  column (Ki, IC50, Kd, EC50) and each kinetic column (kon, koff) becomes its own
  record, so the deterministic classifier decides what is comparable: the potency
  columns are a concentration, kon/koff are not, and `chemistry/activities.py` reports
  them `not_applicable` instead of comparing them with a potency threshold.
  Censored values (`<`, `>`, `~`) keep their relation. Unit is nM for the potency
  columns (BindingDB's own unit, stated by the column name) and `M-1 s-1` / `s-1`
  for the kinetics. Nothing is rounded, averaged or ranked.
- **D6 — The scan is its own record and cannot look complete when it is not.** The
  retrieval's query carries the search parameters the run actually used
  (`snapshot_file`, `snapshot_release`, `snapshot_sha256`, `snapshot_size_bytes`,
  `snapshot_rows`, `match_mode`, the accession and the names tried), and the adapter
  reports `complete` only when it reached EOF; a run stopped at `--max-rows` /
  `--max-seconds` is `partial`, says how many rows it read of how many it did not, and
  records no file digest (a prefix has no file identity). A zero-result run therefore
  reads as "the whole file was scanned and matched nothing", never as a silent empty.
- **D7 — The digest is free.** The file is read in binary and hashed as it is parsed,
  so the release's identity costs no second pass; the runtime is one pass.
- **D8 — Idempotent by the source's own key.** `source_record_id` is
  `bindingdb-snapshot:<Reactant_set_id>:<endpoint>`, stable across releases, so
  re-running the same query updates rows instead of duplicating them
  (`measurements` upserts on `(compound_id, assay_id, standard_type, source_record_id)`,
  §22). A *new* release that drops a row leaves the stored row in place — retraction
  on a complete refresh is B-30.
- **D9 — Publication-number mode is the second half of this item and is not in this
  round.** `patents.py::search_tsv_by_patents` in the source project is a different
  workflow (patent-led declared compounds) whose SPAgo storage already exists as the
  B-24 tables. Building it here would mean a second rule/version and its own
  acceptance; recorded in the register rather than half-built (§37).

## Steps

1. `domain/models.py` / `adapters/bioactivity_base.py` — `ActivityResult.query_context`
   (the search parameters a retrieval actually ran with), merged into the retrieval's
   stored query by `_run_bindingdb`.
2. `adapters/bindingdb_snapshot.py` — streaming reader and matcher, one pass, hashing
   as it reads, `ActivityRecord` per endpoint, rejection/organism counts, scan report.
3. `scripts/bindingdb_snapshot.py` — the operator entry point: target from the
   database (no resolver call, no upstream request), bounds, `--dry-run`, JSON output.
4. `data/fixtures/open_sources/bindingdb_snapshot_sample.tsv` (+ the fixtures README) —
   a small synthetic slice of the real 640-column schema with the cases the reader must
   get right.
5. `services/core/tests/test_b23_bindingdb_snapshot.py` — reader semantics, matching
   modes, species filter, endpoint split, censored values, rejection counts, release
   and digest recorded, partial vs complete, idempotent re-run, service-level write
   (only the snapshot source is touched), and the fixture-only reconciliation with the
   REST fixture (same compounds, both paths, duplicate flag).
6. Docs — `docs/runbook.md` (the operator call and what it spends), `docs/online-capability.md`
   (the honest limit: local-only value), `THIRD_PARTY_NOTICES.md` (the port and the
   BindingDB data terms), `README.md` operator section if it lists loading paths.
7. Acceptance on the real file — `benchmarks/bindingdb-snapshot-2026-09-16.{md,json}`:
   one full pass for an acceptance target with scan time, rows scanned, rows matched by
   accession vs name, digest time, the stored retrieval's version/checksum fields, and
   the reconciliation against the stored REST rows for the same target.

## Result

**Delivered 2026-09-16.** A target can be answered from the whole release held on
disk, and the stored data says which file answered.

- **Adapter** (`adapters/bindingdb_snapshot.py`) — one streaming pass over the TSV
  (stdlib only, no new dependency): required/endpoint columns read from the header,
  accession first across every `UniProt … of Target Chain N` column, then `Target Name`
  exactly (`--name-mode auto` for the substring rule), organism canonicalized and
  filtered with counted exclusions, one `ActivityRecord` per filled endpoint, the file
  digest computed in the same pass, and a `query_context` carrying the search the run
  actually ran. Port provenance: `THIRD_PARTY_NOTICES.md`.
- **Operator entry point** (`scripts/bindingdb_snapshot.py`) — target from stored rows
  (never resolved, never invented), `--dry-run`, `--max-rows`/`--max-seconds`, JSON
  output, exit codes `0`/`1`/`2`. The app has no path to it: a multi-gigabyte scan
  inside a request would violate §21 (D2).
- **Fixture + tests** — `data/fixtures/open_sources/bindingdb_snapshot_sample.tsv`
  (synthetic, 17 rows; documented in the fixtures README and `THIRD_PARTY_NOTICES.md`
  §5), `tests/test_b23_bindingdb_snapshot.py` (36 cases: file identity, scan honesty,
  matching modes, organism verdicts, endpoint split, censored values, store path,
  idempotent re-run, REST/snapshot reconciliation).
- **Acceptance on the real file** — `benchmarks/bindingdb-snapshot-2026-09-16.md`
  (raw `…json`): 3,237,052 rows / 8.98 GB / 3,237,052 scanned in **113.2 s**, 153 kept
  records from 153 accession matches (0 by name), 0 new compounds (133 reused), digest
  `66bb5f955bd88d29`; the stored retrieval now names the file, and a bounded dry-run
  shows a prefix is `partial` with no digest. Reconciled against the stored REST rows:
  the endpoint's 9 compounds are a strict subset of the file's 133.
- **Defect found and fixed in the round** — the retrieval upsert never rewrote
  `query`, `pages_fetched`, `dataset_version`, `source_version` or `checksum` on
  conflict, so the first snapshot run left the row claiming `bindingdb-rest` with a
  REST-only query (D1/D6 violated in the stored artifact, invisible to the unit tests
  because they ran the snapshot first). `discovery._persist_retrieval` now updates
  them; `test_a_snapshot_run_after_a_rest_run_relabels_the_retrieval` pins it, and the
  B-06 record carries the correction.
- **UI** — the target header's source line and chip tooltip state the access path
  (`via bindingdb-snapshot-tsv (bindingdb-snapshot:2609)`), browser-verified on the
  rebuilt image; the scan summary was already visible in the chip's source notes.
- **Docs** — `docs/runbook.md` §2.8 (the operator call, what it spends, the bounds and
  refusal codes), `docs/online-capability.md` §5 (the honest limit: operator-only,
  local value, not a hosted capability), `README.md` feature list, fixtures README,
  `THIRD_PARTY_NOTICES.md` (the port and BindingDB's data terms).
- **Not built, on purpose (D9)** — patent-number mode from the same file
  (`search_tsv_by_patents` in the source project): a different workflow on the B-24
  tables, with its own rule/version and acceptance. Recorded in the backlog, not
  half-built.
