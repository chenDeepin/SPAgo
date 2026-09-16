# B-23: a target answered from a local BindingDB release (acceptance on the real file)

Measured 2026-09-16 on the local stack (docker compose, database `spago`), against
the operator's own file `/media/chen/Machine_Disk/Datasets/BindingDB_All_2609.tsv`
(8,984,698,089 bytes, 640 columns, 3,237,052 data rows). The file stays outside the
repository (`AGENTS.md` §34); what is recorded here is the run, its counts and its
timings. Raw records: `bindingdb-snapshot-2026-09-16.json` (this run) and
`bindingdb-snapshot-il6-2026-09-16-before-fix.json` (the first pass, whose defect is
described below). Produced by `scripts/bindingdb_snapshot.py`, which reads the file
and writes through the ordinary service — no source is contacted at any point.

## Why this was measured

The claim is that a target can be answered from the *whole* release, that the stored
data says which file answered, and that a bounded or incomplete scan can never read
as the snapshot. The live IL6 investigation was already in the database from the REST
path (9 kept records out of the endpoint's answer), so this run also had to show that
the two paths reconcile on the same compounds instead of overwriting each other.

## Results — one full pass

`--target IL6` (stored target `5ed5e9f2…`, UniProt `P05231`), no bounds, stored:

| Quantity | Value |
| --- | --- |
| Wall time, scan → stored rows | **113.2 s** (scan warning reports 112.7 s of it) |
| Rows scanned | 3,237,052 (the file was read to the end) |
| Bytes scanned | 8,984,698,089 (8.98 GB) |
| Throughput | ≈ 28.5 k rows/s |
| Matched rows | 153 — **153 by UniProt accession, 0 by target name** (mode `exact`) |
| Records kept | 153 (one per filled endpoint column) · excluded 0 |
| Stored | 153 measurements, 153 candidates, 0 new compounds, 133 reused |
| File digest | `sha256:66bb5f955bd88d29…`, computed in the same pass |
| Exit code | 0 |

The digest costs no second read: the file is hashed as it is parsed. Measured
separately on the same machine, a dedicated `sha256sum` over the file takes
**20.56 s**, which is what the in-pass digest avoids (D7).

Organism filter `Homo sapiens`: `organism_mismatch_rows 0`, `organism_unverified_rows 0`
for this target — BindingDB writes "Human" on most of these rows, and the canonical
form is what made them comparable (86 of 153 real IL6 rows were dropped as mismatches
before `canonical_organism` existed; see the unit test that pins it). The 13 `|r|`
CXSMILES annotations were removed before parsing and are recorded as source notes, not
as failures.

## Results — the stored row says which file answered

`source_retrievals`, bindingdb row for the IL6 target, after this run:

| Field | Value |
| --- | --- |
| `source_name` / `source_version` | `bindingdb` / `bindingdb-snapshot-tsv` |
| `dataset_version` | `bindingdb-snapshot:2609` |
| `status` | `complete` (seen 153, kept 153, excluded 0) |
| `latency_ms` | 112,918 |
| `checksum` | `aae9cff9eaf68c7a` (hash of the ask below) |
| `retrieved_at` | 2026-09-16 11:16:01 UTC |

The stored `query` is the search the run actually ran, not the caller's intent:
`snapshot_file`, `snapshot_release 2609`, `snapshot_sha256 66bb5f955bd88d29`,
`snapshot_size_bytes`, `snapshot_rows_scanned 3237052`, `snapshot_complete true`,
`match_mode exact`, `matched_by_accession 153`, `matched_by_name 0`,
`matched_aliases "Interleukin-6, IL6, IFNB2, P05231"`, `organism_filter "Homo sapiens"`,
`all_organisms false`, `uniprot P05231`.

**The defect the first pass found, and the fix.** The first run (11:08, raw record
`…-before-fix.json`) scanned and stored the same 153 records — but afterwards the
retrieval row still read `source_version=bindingdb-rest`, `dataset_version=bindingdb:2026-09-15`,
`query={"uniprot": "P05231"}` and the *old* checksum, while the measurement rows from
that run said `bindingdb-snapshot-tsv` / `bindingdb-snapshot:2609`. The upsert in
`TargetDiscoveryService._persist_retrieval` had never rewritten the ask or the version
columns on conflict, so a source re-asked through another access path kept the first
run's identity. The file identity the adapter reports was reaching `warnings` only.
Fixed in this round (`query`, `dataset_version`, `source_version`, `pages_fetched` and
`checksum` are now part of the update) and pinned by
`test_a_snapshot_run_after_a_rest_run_relabels_the_retrieval`; the table above is the
post-fix state, and the other two sources' rows were not touched by either run
(chembl `retrieved_at` 07:07:13, pubchem 10:37:54, both unchanged).

## Results — reconciliation with the REST path (same target, same database)

| Path | Measurement rows | Compounds | Dataset version |
| --- | --- | --- | --- |
| REST (`bindingdb_rest_uniprot`, 07:07 run) | 9 | 9 | `bindingdb:2026-09-16` |
| Snapshot (`bindingdb_snapshot_tsv`, this run) | 153 | 133 | `bindingdb-snapshot:2609` |
| In both (same InChIKey) | — | **9 of 9** | — |

The REST set is a strict subset of the snapshot's: every compound the endpoint
returned is also in the file's set, and both paths' rows are stored under their own
record ids and assay keys, so neither path's wording overwrites the other. The
per-request question ("how many in-scope compounds are at or below 10 µM") is
computed on read from all rows: with the snapshot rows present, IL6 reads **135 active
of 157 in-scope compounds** under `potency-gate-v1`, against the 124 of 144 the
ChEMBL-only record carried (`benchmarks/cohort-coverage-2026-09-16.md`). That delta is
what the local path buys here; it is not a claim about the literature.

The retrieval chip in the target header now reads the snapshot's own notes ("Scanned
3,237,052 data row(s) (8.98 GB) … in 112.7 s", "The file was read to the end … Release
2609, sha256:66bb5f955bd88d29…"), and the source line in *Source notes and reference
coverage* states the access path — `bindingdb · 153 kept records · 153 linked to a
document · via bindingdb-snapshot-tsv (bindingdb-snapshot:2609)` — with the same string
on the chip's tooltip, so a reader can tell the file's answer from the endpoint's
without reading the code. Browser-verified on the local stack after
`docker compose up -d --build app` (viewport 1232×927, dpr 1; the cached pre-fix
bundle had to be bypassed to see it — a stale `index-*.js` served the old UI, which is
its own reminder that a browser check must name the bundle it read: the verified run
loaded `index-CtDUnceZ.js`, the one the rebuilt image serves). Screenshots in
`/tmp/cursor/screenshots/page-2026-09-16T11-21-14-936Z.png`, not committed.

## Results — a bounded scan is a prefix, and says so

Live, on the same file: `--max-rows 20000 --dry-run` (nothing written).

| Quantity | Value |
| --- | --- |
| Rows scanned | 20,000 of 3,237,052 (61,486,331 bytes of 8,984,698,089) |
| Wall time | 0.7 s (same ≈ 28.5 k rows/s) |
| Status / exit | `partial` / **1** |
| File digest | **not recorded** — "a prefix has no file identity" |
| Zero-result wording | "No measurement was stored from this scan. The scan summary above says whether the whole file was read, so this is 'nothing in the release matched' and not a half-answer." |

## What this does and does not prove

- Proves: on this checkout and this file, one pass over the release answers IL6 (153
  kept records, 133 compounds) in 113 s with no upstream call; the stored retrieval
  and every measurement row state the release, the digest and the match rule; a
  snapshot run re-labels the retrieval row it produced and leaves the other sources'
  rows untouched; the REST set and the file's set reconcile compound by compound; a
  bound produces `partial`, no digest, and a warning that says what was not read.
- Does not prove: anything about other targets' coverage, the content of the release
  beyond this target (row counts match the file, values are as reported), or a hosted
  deployment — this is **operator tooling on a workstation**, not a feature of the
  invited beta (`docs/online-capability.md` §5), and the file must exist on the host.
- Not measured: memory high-water mark during the scan, and the run on a cold page
  cache versus the 20.56 s digest figure above (that one is warm). Both are honest
  gaps of this record rather than claims.
