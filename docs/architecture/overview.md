# SPAgo Architecture Overview

Status: **implemented shape with historical local/selected live-source verification;
hosted acceptance still open**, reviewed against checkout `efb1357` on 2026-09-16.
This was a static, documentation-only review, not a new runtime verification.
Scope statement: [`docs/online-capability.md`](../online-capability.md). Active
direction: [`docs/plans/2026-09-15-online-llm.md`](../plans/2026-09-15-online-llm.md).
Current findings and ordered proposals:
[`product review Q&A`](../plans/2026-09-16-product-review-qa.md) and
[`backlog`](../plans/backlog.md). The rounds this shape was built through are archived in `docs/archive/`: the M0-only
framing in `2026-09-14-m0-foundation.md`, the M1–M5 implementation in
`2026-09-14-m1-m5-implementation.md`, the readiness and repair rounds in
`2026-09-15-product-readiness.md` and `2026-09-14-ui-review-next-round.md`. Decisions
live in `docs/adr/`; source constraints in root `AGENTS.md` and `PROMPT.md`.

## Shape

SPAgo is a modular monolith deployed as two containers:

```text
apps/web (React + TypeScript + Vite)          ← browser workspace
        ↓ HTTP /api/v1
services/core (FastAPI, Python)
    ├─ api/        HTTP routes (typed request/response models)
    ├─ services/   core reads · projects · export · bioactivity ·
    │              structure search · AI summaries
    ├─ adapters/   external-source contracts: patent fixtures,
    │              real SureChEMBL bulk packages, bioactivity fixture,
    │              UniProt, ChEMBL, BindingDB REST/operator TSV, PubChem,
    │              LLM Chat Completions
    ├─ chemistry/  RDKit engine (canonicalization, InChIKey,
    │              descriptors, Murcko scaffolds, depictions)
    ├─ queries/    DuckDB bulk analytical layer (Parquet)
    ├─ db/         engine + versioned SQL migrations
    └─ domain/     typed domain models + provenance states
        ↓
PostgreSQL 15 + RDKit cartridge        DuckDB over Parquet
(molecule column + GIST/GIN indexes;   (bulk analytical reads of the
 patents, compounds, mentions,          fixture; future bulk releases)
 evidence, targets/assays/measurements,
 projects, ai_analyses)
```

No Redis, queue, search engine, or additional database exists
(`AGENTS.md` §6). `apps/chrome-extension/` is a thin MV3 context bridge:
URL-only publication-number detection → side panel → `?q=` deep link. It is checked
twice: `apps/chrome-extension/check.js` (manifest, syntax, the URL detection contract)
and `apps/chrome-extension/verify-in-chrome.js`, which loads the unpacked extension in
an unbranded Chrome/Chromium build, opens a page under the match pattern, reads the
handoff back out of the worker's `chrome.storage.session` and the rendered side-panel
page, and reads `chrome.sidePanel.getPanelBehavior()` back from the running worker so
`openPanelOnActionClick` is verified as set rather than assumed. Branded Google Chrome
137+ ignores `--load-extension`, so that script reports the browser refusal instead of a
broken extension; the physical toolbar click and the side-panel surface chrome need a
browser-chrome user gesture this checkout cannot synthesize, and are not claimed.

## Implemented workload separation (PROMPT.md §11)

| Workload | Store | Current use |
| --- | --- | --- |
| A. Bulk analytical filtering | DuckDB + Parquet | fixture adapter input; `/api/v1/bulk/compound-counts`; benchmarks |
| B. Interactive chemistry | PostgreSQL + RDKit cartridge (`mol` column, GIST/GIN) | exact / substructure / similarity search, molecule filters |
| C. Project and evidence state | PostgreSQL | patents, mentions, evidence, measurements, projects, AI analyses |

## Current data paths

```text
data/fixtures (synthetic Parquet, demo-fixture-v1; SPAGO_SEED_MODE=demo)
operator patent lists (scripts/corpus_batch.py chunks a list, extracts and
                imports each chunk, and keeps a resumable STATE.json)
real packages  (scripts/extract_surechembl.py → SureChEMBL bulk Parquet
                over HTTP range reads; import_package → import_jobs)
      ↓  adapters (DuckDB read; source envelope with provenance)
      ↓  chemistry/engine.py (RDKit canonical SMILES, InChIKey,
      ↓                        descriptors, Murcko scaffold)
      ↓  seed.ingest (idempotent upsert; dedupe by InChIKey; malformed
      ↓               structures → ingestion_issues, never compounds)
PostgreSQL  →  api routes (server-paged, cap 500)
apps/web     (search → family → compounds → evidence/structure search)
```

- What the loaded corpus covers (B-01): `services/core.py::corpus_summary`
  counts families/documents/compounds/mentions/evidence/measurements per
  `dataset_version` on every request (`GET /api/v1/corpus`, the top-bar badge's
  `Loaded corpus` dialog, and `python -m spago_core.corpus_status` for the
  terminal). No maintained counter exists on purpose: a counter is a second copy
  of the truth that can drift, and the measured cost of the read (5.8–6.5 ms,
  1,907 bytes on the local database) does not justify one yet. Versions that no
  `dataset_info` row registered are still listed and labelled as not an imported
  package; a publication absent from the corpus stays an explicit not-found.

- Demo vs imported corpus: `SPAGO_SEED_MODE=none` applies migrations without
  the demo fixture; real corpus packages arrive via the explicit
  `python -m spago_core.import_package <dir>` command, which records a durable
  `import_jobs` row (status, file SHA-256 checksums, ingest summary) and is
  idempotent. `dataset_info` registers imported package sources; online/snapshot
  retrievals also enter through their service paths and use `source_retrievals`.
  The UI badge, empty
  state, table footer and save dialog label data by its actual source.
- Real SureChEMBL mapping (PROD-01): family/document ids derive from
  SureChEMBL numeric ids; a mention is one (compound, document, patent-field)
  occurrence with the field in its label; page numbers and patent-local text
  labels are not in the bulk data and display "not provided" instead of being
  invented; every evidence record links to the Espacenet publication page for
  manual verification (a link, never automation).
- Target-led discovery: UniProt resolution and reviewed scope → bounded source
  adapters → normalized candidates/assays/measurements and per-source retrieval
  outcomes. Per-source retry writes only the requested sources. The snapshot adapter
  is an operator CLI path; no interactive request scans the bulk file. Current target
  reads use `investigation_measurements`; potency classes/verdicts are computed on read.
- Patent-led declarations (B-24) live in `patent_source_lookups` /
  `patent_source_compounds`, not `compound_mentions`. Publication coverage (B-26) reads
  corpus/declared/supplement legs without upstream calls or a sum across provenance
  classes. It has no dedicated snapshot leg; its fixed snapshot-unavailable note is
  stale after B-23 (B-32), even though the operator path exists.
- Supplement bundles (B-25) record producer, search note, per-row outcomes and
  confirmation. Unconfirmed proposals remain outside candidates/verdict/exports;
  human confirmation is a recorded action, and withdrawal preserves history.
- Import review contract: packages preserve retrieval timestamps and dated source
  versions, validate manifest provenance/checksums/associations, and cap tables
  at 100,000 rows. Unknown source fields remain unknown; source-vs-normalized
  InChIKey differences are warnings, not silently upgraded scientific facts.
  Mentions upsert by stable source-occurrence UUID; local labels are not unique
  identifiers. Import issues are refreshed only for the package documents.
  Global compound version records initial identity ingestion; current scoped
  source versions come from mentions/evidence. B-04 retracts mappings within the
  package's document coverage and measurements within a complete activity source
  release, retaining reasons/versions; identity rows persist. Interrupted imports are
  recovered by an idempotent re-run whose summary names the interrupted jobs.
  Document absence beyond package coverage and online retrieval absence are not a
  complete release-replacement protocol (B-30).
- Saved projects: migration 0008 keeps family/compound UUIDs and saved identity
  snapshots when source rows disappear; project ownership deletion still cascades.
  Per-item source/version lists are scoped to its family. Reads report missing
  references and drift; retries return the original saved versions. Legacy source
  lists remain unknown when they cannot be reconstructed. The UI switches saved
  families and restores only the selected family's items.
- Family/document tables and structure hits hydrate mentions within the requested
  scope; global compound detail remains a separate cross-family record. CSV/SDF
  export uses scoped versions and rejects overflow before materializing matches;
  invalid stored structures fail SDF generation instead of silently dropping rows.
- Structure search: exact = isomeric InChIKey; substructure = cartridge `@>`
  plus a chirality-aware RDKit re-check when the query specifies stereo;
  similarity = explicit `tanimoto_sml >= threshold` (this cartridge's `%`
  operator is fixed at 0.5 and would silently drop lower thresholds). Morgan
  fingerprints do not distinguish stereoisomers — the UI states this per mode.
- Depictions: RDKit SVG per request with disk cache; only rendered rows fetch.
- Bioactivity: only typed measurements surface; cross-assay values are never
  ranked or combined into selectivity numbers.
- Export scope contract (PROD-02): `/api/v1/export` serves an explicit
  selection, a server-re-executed `structure_query` (covering matches the
  browser never loaded), a document, or a family. Mention/evidence aggregation
  follows the requested scope, so a compound occurring in another family never
  exports that family's records. The 5000-row synchronous cap is enforced in
  the counting phase; out-of-scope selected ids are rejected with a count.
- Projects (PROD-03): dataset versions are derived server-side from the saved
  rows (client labels ignored); each item stores an identity snapshot
  (inchikey, canonical SMILES) and the full version list; reading reports
  `source_updated`/`record_missing` drift instead of silently absorbing data
  changes. The UI reopens a project via Projects → Open, restoring the family
  view and the saved selection; a single target's candidates can also reopen without
  a patent mapping. Navigation across every target/family in a mixed project is
  incomplete (B-36), and analyses are not yet project artifacts (B-29).
- AI summaries: default is the offline extractive provider
  (`machine_extracted`). With `SPAGO_LLM_BASE_URL`/`SPAGO_LLM_API_KEY`/
  `SPAGO_LLM_MODEL` configured, the AI tab can call one OpenAI-compatible
  Chat Completions endpoint (`adapters/llm.py`): bounded fact input
  (SQL selects ≤50 measurements, ≤50 evidence excerpts and a capped scaffold list;
  excerpts are byte-bounded at 1 KiB that is measured on the *annotated* body), typed fact
  citations validated server-side, content-key caching (zero provider calls on cache hit),
  LLM output labeled `llm_inferred`. If the irreducible metadata alone exceeds the 32 KiB
  budget the request fails before any provider call. `GET /api/v1/ai/status` reports
  offline/configured/config_invalid without calling the provider. The planner
  handles deterministic publication identifiers and reviewed target entities offline;
  the configured model may propose typed allowlisted operations, validated and shown
  before explicit execution. Analyses can be listed/reopened/exported without a model
  call (B-10), with a recomputed staleness check. Exact citation navigation remains
  incomplete in several UI paths (B-37).
- LLM execution uses one shared synchronous HTTP client and process-local in-flight
  tracking (two calls, one worker); no provider fallback exists. Failures that may
  not have been billed — timeout, upstream throttle, auth, transport, protocol —
  are never retried; the only re-attempt is one identical re-sample after a
  *completed, billed* answer was rejected by validation (owner decision
  2026-09-15). The declared budget is attached to each outbound request (connect
  5 s, read = total deadline 60 s) and the deadline is re-checked between response
  chunks; upstream throttling answers 429 with a validated `Retry-After`, distinct
  from other upstream failures (502). See
  [the LLM contract record](../archive/2026-09-14-llm-interface.md) and
  [the live-smoke record](../archive/2026-09-15-llm-live-smoke.md).
- URL state: `?q=&doc=&c=&t=`; new searches push history entries, selection
  replaces; Back/Forward restore encoded identifiers via popstate. Target modality,
  evidence-class filter and threshold override remain in component state (B-39).
- Deployment shape: both published ports bind to loopback by default
  (`SPAGO_APP_BIND`/`SPAGO_DB_BIND`); backup/restore/upgrade are documented and
  drilled in [docs/runbook.md](../runbook.md).

## Deliberate boundaries

- Export is synchronous up to 5000 rows (documented cap); larger scopes need
  the future persisted background-job mechanism.
- The embedded Ketcher editor is loaded on demand in the structure-search dialog
  (packaging fixes and the measured first-open cost: 5.2 MB compressed, 20.3 MB
  decoded, `benchmarks/asset-compression-2026-09-16.md`; the app compresses its own
  responses, so no proxy is required for that figure); typing or pasting a SMILES
  string stays equivalent, and the editor is not the renderer for result rows.
- No PDF/OCSR (M6), no live ChEMBL/BindingDB calls in the demo seed, and no
  cross-family structure search (family-scoped by contract).
- Pagination: default 100, hard cap 500, enforced server-side on every list
  and search endpoint. This caps a response, not a result set. Both the ordinary
  list and the structure-result list page by server-side offset and append: each
  request asks for one page (100 rows), the next page continues from
  `offset + items.length`, and Load more stops on the last page. Loaded rows survive a
  paging failure, which is shown as a retryable error owned by the request it came from;
  changing family, document, query or structure filter discards stale pages and errors.
  Verified with a 601-compound synthetic fixture
  (`benchmarks/paging-beyond-cap-2026-09-15.md`); the 150-row historical check is kept
  as a separate, narrower record.
- Source evidence includes real SureChEMBL imports, bounded open-database retrievals,
  an operator snapshot and one measured model provider. Independent scientific
  cross-reading and hosted user acceptance remain open; different cohort workspaces
  must not be treated as identical source-only baselines (B-32).
- Target export differs from the family/structure export path: the browser currently
  omits its active threshold and evidence filter, and the backend export contract has
  no evidence-class parameter (B-33). Static inspection establishes the missing
  parameters; a browser download reproduction remains to be done.
- Hosted mode implements invitations, sessions, owner-scoped projects/analyses and
  quotas; local mode disables auth deliberately. Both published ports default to
  loopback. A real host/TLS/backup/restore/user run is still required by capability §6.
- CI uses the selected `--no-pg` check path, not the full database suite or browser
  smoke (B-35). `/healthz` reports a package API version, not an immutable build
  identity (B-34). Prior passing runs are not evidence for an unverified server.

## Performance baseline

Tracked by `services/core/benchmarks/run_benchmarks.py`;
`benchmarks/m0-baseline.json` (fixture scale) and
`benchmarks/paging-measurement-2026-09-14.md` (150-compound paging /
virtualization round) are retained measurements — neither is overwritten by
later runs.
