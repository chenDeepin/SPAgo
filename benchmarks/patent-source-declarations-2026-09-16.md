# B-24: what a source declares for a publication (live)

Measured 2026-09-16 on the local development stack (docker compose, database
`spago`) against the **live** ChEMBL web services, through the shipped code path:
`PatentSourceService.lookup` → `ChEMBLDiscoveryAdapter.declared_compounds` →
`patent_source_lookups` / `patent_source_compounds`, then `read_all` and the CSV/SDF
renderers. Raw record: `patent-source-declarations-2026-09-16.json`.

Row payloads are **not** copied into this repository: they are public ChEMBL
records, and the artifact records counts, metadata, the CSV header and the export
checks instead (AGENTS.md §34). Any reader can reproduce the files from the app's
export controls or from `scripts/patent_source_lookup.py`.

## Why this was measured

The product's first promise — *enter a patent, see its compounds* — used to stop at
the loaded corpus. A publication that was never imported (or imported thinly) showed
an empty table even when a public source indexes compounds under it, and the search
box's 404 was a dead end. This round adds a **patent-led read path** that asks the
source what it declares for a publication number, independent of the corpus.

The measurement answers the two questions that decide whether that is usable:

1. Does the name-matching rule actually resolve a real publication on the live API,
   and how much of what comes back is usable?
2. What does the *other* answer look like — a number the source does not know?

## Results

| Asked | Status | Declared records | Compounds | Records seen | Not usable | Lookup time |
| --- | --- | --- | --- | --- | --- | --- |
| `US10508115` | `complete` | 134 | 73 | 402 | 268 (`missing_standard_value`) | 16.0 s |
| `US12345678` | `empty` | 0 | 0 | 0 | — | 5.9 s |

`match_rule = chembl-document-patent-body-v1` in both rows: the rule travels with
the answer, so the empty one is readable as "this source, under this rule" rather
than as a fact about the patent.

### The matched publication

- The source's document `CHEMBL5727449` declares patent `US-10508115-B2`, which
  normalizes to the requested `US10508115`. The document row is stored with the
  number **the source recorded**, not the query string.
- Every declared record carries that number in `document_patent_number`, its
  ChEMBL activity id as `source_record_id`, and a `source_url` that re-finds it.
- All 134 kept records are `EC50` (100 of them on *Toll-like receptor 7*, 34 on
  *Interleukin-6*), all `small_molecule`, 2 carry the source's preferred name
  (`RESIQUIMOD`, `VESATOLIMOD`), and the source flags none as duplicates.
- Under `potency-gate-v1` at 10 µM, all 134 are `active` — computed on read from the
  stored value, unit and relation, not stored.

### What was not usable, and why it is reported

268 of 402 activity records were excluded, every one of them for
`missing_standard_value`: the document's kinetic rows (`kon`/`k_off`, `Kd`, `Ki`
expressed without a numeric `standard_value`) cannot be compared with a potency
threshold. They are counted and reported rather than dropped silently, so
"134 declared records" is not read as "the source declares 134 things about this
patent". This is the same exclusion the target-led path applies, with the same
reason vocabulary.

### The two non-answers that stay distinct

- `empty` (`US12345678`): the source was asked, and no document normalizes to that
  number. The stored warning names the rule. There is no export file; the export
  endpoint refuses with the reason instead of writing an empty CSV.
- `failed` (source unreachable): covered by tests, not by this live run. The stored
  status is `failed`, the previous rows are kept with their own
  `rows_retrieved_at`, and the response says the set shown is from the last
  successful retrieval. `not_queried` is a third state: nobody asked.

## Export

Both exports cover the whole stored set (server-side), not the loaded page.

| Check | Result |
| --- | --- |
| CSV | 135 lines (header + 134 rows), every row `source_declared_compound`, every row carrying `chembl-document-patent-body-v1`, `reference_policy_version` and `reference_threshold_nM` in its own columns |
| SDF | 134 records; 134/134 parse back in RDKit; the first record retains `record_kind`, `publication_number`, `match_rule`, `activity_class`, `potency_label`, `inchikey`, `reference_policy_version` |
| Empty set | export refused with "holds no declared records (status: empty), so there is nothing to export" (HTTP 422 through the API) |

## What this measurement is not

- It is **not** a claim that ChEMBL holds every compound in `US10508115`. It is what
  one source declares under one body-search rule; a different rule (or a source with
  a different patent field) may reach a different set.
- It is **not** a corpus occurrence measurement: the lookup wrote no
  `compound_mentions` row and moved no family count (pinned by
  `tests/test_patent_source_compounds.py::TestStoredLookup`).
- It is **not** a coverage claim over the patent corpus: one publication was resolved
  by name match here. The interesting rate — how many requested numbers a source can
  resolve at all — is not established by this record, and a 4-number sample would not
  establish it.
- Fetch cost is one bounded pair of requests per publication (documents, then
  activities), bounded at 20 documents and 500 records; 16.0 s is the live network
  time for a 402-record document, not an interactive-path latency claim.
