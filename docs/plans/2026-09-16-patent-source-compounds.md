# B-24 — Patent-led compound discovery (plan, 2026-09-16)

Backlog item `docs/plans/backlog.md` B-24, the P1 item after B-02. Vision check: it serves
`PROMPT.md` §2 (the user enters a patent and sees its compounds) and `AGENTS.md` §8/§9/§10/§11.
What a user can do afterwards that they cannot do now: open a publication SPAgo never
imported — or imported thinly — and ask the source what compounds it declares for that
publication, with the match rule stated, the declared set kept apart from corpus occurrences,
and an export that carries both.

## What is already there (read before planning)

- `ChEMBLDiscoveryAdapter` (`adapters/chembl_discovery.py`) already does everything *except*
  the document→activities direction: `SourceClient` (timeout, rate limit, TTL cache, bounded
  retries), `ACTIVITY_FIELDS`/`DOCUMENT_FIELDS` projections, `_to_record` (the one rule for
  "what is a kept record"), `classify_evidence`, and `_attach_document_references`.
- `spago_core/domain/patent_numbers.py` already normalizes `WO 2019/047734`, `US-5153197-A`
  and `US10508115B2` to one token — adapted from the same local project this item ports from,
  and documented in its docstring.
- The declared/corpus distinction is already vocabulary (`source_declared_patents` vs
  `patent_numbers` in the export; `N occurrences` vs `source declares …` in the candidate
  table). B-24 adds a *patent-led* read path, not a new meaning.
- The reference implementation is `BindingDB_IO` `bindingdb_io/readers/api.py::search_chembl_patent_api`
  (read 2026-09-16). Adopted: the body-based document query (`patent_id__icontains=<digits>`),
  the exact-normalization verification of what the source returned, the bounded activity pull
  by `document_chembl_id__in` with the projected field list, and the rule that a row without a
  structure is skipped. **Not** adopted: the `nM`-only / `Ki,IC50,Kd,EC50`-only upstream filter
  and the `-1`-style value rewriting. SPAgo keeps every record that carries a structure and a
  numeric standard value and lets the deterministic potency policy decide what a value means
  (§11) — a unit filter upstream would silently drop a µM record and call it absent.

## Design

| Piece | Shape |
| --- | --- |
| Adapter | `ChEMBLDiscoveryAdapter.declared_compounds(publication_number)` → `DeclaredCompounds` (documents matched exactly, near matches with their number, records, counts, warnings, status). Reuses `_to_record` and the projections; adds `PATENT_ACTIVITY_FIELDS` (the measured projection plus `molecule_pref_name`) so the measured target-path projection is not silently changed. |
| Match rule | `chembl-document-patent-body-v1`: the source's `document.patent_id` normalizes to the same token (country + digits, kind code and separators ignored). A document the body search returns that normalizes to a *different* number is a **near match**: listed with its number, excluded from the compound rows, counted. |
| Storage | Two new tables (`0017_patent_source_lookups.sql`): `patent_source_lookups` (one current row per publication+source: requested/normalized number, status, rule, documents, near matches, warnings, counts, dataset version, retrieved_at) and `patent_source_compounds` (one row per declared record, pointing at the shared `compounds` identity row). A *failed* lookup is stored as failed, so "we asked and it failed" never reads as "not queried". Compounds go through `persist_compounds`, so one structure is one compound; **no `compound_mentions` row is written** — a declaration is not an occurrence (§11). |
| Service | `services/patent_sources.py`: `lookup_declared_compounds(engine, publication_number)`, `read_declared_compounds(engine, publication_number, offset, limit)`, `render_declared_compounds_csv/sdf` (in `services/export.py`, next to the other renderers). |
| API | `POST /patents/{publication_number}/source-compounds` (the explicit user action, mirrors `POST /targets/discover`), `GET /patents/{publication_number}/source-compounds` (stored view + one page of rows, default 100 / max 500), `GET .../export?format=csv\|sdf`. Reading before any lookup returns `status: not_queried`. |
| UI | `SourceCompoundsPanel` on the patent view's main column, below the compound table: a collapsed section that states it is a source-declared set (not corpus occurrences), the rule, the source, the retrieval time and bounds; a "Look up in ChEMBL" action; then the declared table (structure, source id/name, endpoint + value + unit + class under `potency-gate-v1`, target, assay, document/DOI/PMID) with paging and the two export buttons. Scoped by the effective publication number, so switching documents cannot show another document's set. |
| Policy label | Each row's class is computed on read by the same deterministic code as the reference verdict; `k_off`/`kon`-style endpoints and non-concentration units read `not applicable`, never compared. No ranking is implied and none is displayed. |

Rejected alternatives: mixing declared rows into the family's compound table (violates §11 and
the row counts); not storing anything and re-querying on every view (no "when did we ask", no
export without a new upstream request, and B-26's `not_queried` vs `absent` needs the record);
resolving each distinct target's ChEMBL type to refine `evidence_class` (2 extra requests per
lookup for a field this view does not claim — the class stays `unspecified` here and the assay
type/endpoint are shown verbatim instead).

## Bounds (stated in the UI and the artifact)

- 100 documents per body search (the source's own page), 20 documents per activity query.
- 500 kept records per lookup (~3 pages), then `partial` with a warning.
- 1 lookup per publication+source, refreshable; re-running replaces the rows in one transaction.

## Verification plan

- Unit (`tests/test_patent_source_compounds.py`): exact match vs near match; a deliberately
  wrong number returns empty *with the rule stated*; a bound reached → `partial` + warning; a
  source failure → `failed` (not empty); records without a structure or a numeric value counted
  in `rejection_counts`; a declared record carrying a document reference without a second
  lookup; the potency class of a `k_off`/`s-1` row reading `not applicable`.
- Integration: lookup → stored rows → API page; the family's `mention_counts` and compound
  count are unchanged by a lookup (the declared set never becomes an occurrence); a second
  lookup replaces rather than duplicates rows; a compound already in the corpus keeps one
  identity row.
- Live (recorded artifact): US10508115 (ChEMBL document `CHEMBL5727449`, 402 activities,
  73 molecules) — bytes/latency for both requests, kept/excluded counts, and the class split.
- Browser: the panel on a real family, the not-queried state, the lookup, the rule text, the
  near-match/absent case for a wrong number, and a download.
- Docs/notices: `README.md`, `docs/online-capability.md` §3, `docs/runbook.md`, fixture README,
  `benchmarks/README.md`, backlog, this record.

## Status

Planned 2026-09-16. Implementation proceeds step by step; results are appended below as they
are verified.

## Result (2026-09-16)

Delivered as planned, with two naming changes: the service is `services/patent_sources.py`
with `PatentSourceService.lookup/read/read_all/export` (the names in the Design table were
sketched before the file existed), and the UI component is
`apps/web/src/components/SourceDeclaredCompounds.tsx`.

**Live evidence — `benchmarks/patent-source-declarations-2026-09-16.md`** (raw `...json`):

| Asked | Status | Declared | Compounds | Seen | Not usable | Lookup |
| --- | --- | --- | --- | --- | --- | --- |
| `US10508115` | `complete` | 134 | 73 | 402 | 268 (`missing_standard_value`) | 16.0 s |
| `US12345678` | `empty` | 0 | 0 | 0 | — | 5.9 s |

The match rule resolved the source's document `CHEMBL5727449`, whose declared patent
`US-10508115-B2` normalizes to the requested number; the stored rows carry that declared
number, the activity id, the source URL and `chembl:2026-09-16` as the dataset version. All
134 kept records are `EC50` (TLR7 and IL-6); the 268 excluded rows are the document's kinetic
records, counted in `rejection_counts` rather than dropped. The empty answer keeps the rule in
its warning, and its export is refused with the reason instead of writing an empty file.

**Files changed:**
- vocabulary: `DeclaredCompounds`, `MATCH_RULE = chembl-document-patent-body-v1`,
  `PATENT_ACTIVITY_FIELDS = ACTIVITY_FIELDS + ",molecule_pref_name"`, `ActivityRecord.source_molecule_name`.
- adapter (`chembl_discovery.py`): `declared_compounds()` — body search, exact-normalization
  verification (a document normalizing elsewhere is a *near match*, listed and excluded),
  bounded activity pull by `document_chembl_id__in`, no evidence class claimed on this path.
- service (`patent_sources.py`), storage (`migrations/0017_patent_source_lookups.sql`),
  renderers (`services/export.py`: `render_declared_compounds_csv/sdf`, `DECLARED_RECORD_KIND`).
- API: `POST`/`GET /patents/{publication_number}/source-compounds`, `GET .../export?format=csv|sdf`
  (the service is a FastAPI dependency so a test can drive a stub source).
- UI: `SourceDeclaredCompounds` — collapsed strip with the count and one action, the declared
  table (lazy depictions, source-record links), rejected/near-match disclosures, server paged
  "load more", both exports. It appears under the corpus compound table **and** on a
  publication the corpus does not hold, where the search box's 404 used to be a dead end.
- operator tool: `scripts/patent_source_lookup.py` (the artifact-producing path, no browser).

**Checks run:** `services/core` suite 600 passed after the new tests (27 in
`tests/test_patent_source_compounds.py`: adapter, storage, API including export and 422s);
`npm run build` clean; `tests/test_online00_discovery.py::...projected_to_the_mapped_fields`
updated to the union of the two projections (it correctly caught `molecule_pref_name` being
read without being projected).

**Defect found and fixed by the browser check (not by the unit tests):** the panel compared
the answer's canonical `publication_number` with the number as typed (`US10508115B2`), so a
successful lookup was discarded and the panel stayed on `not_queried`. The identity check now
uses the answer's `requested_number`, which is what was asked; re-verified in the browser
(134 records appear, the button becomes "Ask ChEMBL again").

**Browser check (loopback `127.0.0.1:8130`, current build, dev database, live ChEMBL):**
`?q=US10508115B2` → 404 state plus the panel with `not_queried` and its reason → "Ask ChEMBL
what it declares" → 134 records for 73 compounds, 100 rows rendered with lazy depictions, "Load
more (100 of 134 shown)" → 134 rows and the control gone; the rule, the 268-excluded tally and
"Documents the source matched: US-10508115-B2" all rendered; after a reload the stored set
opens by itself. Screenshots: panel expanded, panel after the live lookup.

**Gap recorded, not passed:** the export *button click* could not be performed — the workspace
scrolls inside its own container, which the browser tooling could not scroll to reach the
footer controls. The export URL the button calls was fetched from that same browser tab (200,
`content-disposition: attachment`, `x-spago-source-set: source_declared`) and the file's content
was verified over HTTP (CSV 135 lines, SDF 134 records parsed back by RDKit). The client-side
download helper is the one already used by the analysis export.

**What this does not prove:** the resolution rate of the name match over a real cohort (one
publication was resolved here); that the declared set is complete for the publication (one
source, one rule); and any corpus occurrence (a lookup writes no `compound_mentions` row — the
family's compound count is unchanged, pinned by test).

