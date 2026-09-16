# B-26 — Patent coverage audit (per publication, from stored rows)

**Round:** 2026-09-16 (after B-25) · **Class NEXT · P1** · **Owner:** coordinating agent
**Backlog entry:** `docs/plans/backlog.md` §2 B-26 (promoted to P1 when the B-25 round
emptied the P1 group; §4 there argues the promotion)
**Reference read (not copied):** `/media/chen/Machine_Disk/Datasets/BindingDB_IO/` —
`cli/audit_patent_coverage.py` (the status vocabulary and the per-source counts with
samples) and `patents.py` (`search_tsv_by_patents`, `search_supplements_by_patents`) read
in the 2026-09-16 review. Source, license and destination are recorded in
`docs/plans/backlog.md` §3; nothing is imported from that project.
**Vision served:** `PROMPT.md` §2.1 (patents → structures → evidence) and `AGENTS.md`
§10/§11. What a user can do afterwards that they cannot do now: **see, for one
publication, what SPAgo holds and where it came from** — corpus occurrences, a
source-declared set, hand-added rows — and which of those were never asked, instead of
reading three surfaces and a database to find out.

---

## 1. The problem, exactly

Four paths now contribute chemistry to a publication, and nothing puts them side by side:

| Path | Stored in | Read today by |
| --- | --- | --- |
| the imported corpus (an occurrence) | `patent_documents` + `current_compound_mentions` | the compound table, the sidebar's per-document count |
| a source-declared set for the number (B-24) | `patent_source_lookups` + `patent_source_compounds` | the declared-compounds panel, per publication, one at a time |
| hand-added rows citing it (ONLINE-07 / B-25) | `measurements.document_patent_number`, `target_supplement_remarks.patent_number` | the target's supplement dialog only |
| a target-led source record that declares it (B-02) | `measurements.document_patent_number` (+ the retrieval tally) | the target header's reference-coverage disclosure |

So the question "what do we have for this publication, and what is missing?" is answered
by no surface. The failure this causes is a scientific one: a reader concludes "this
patent has no compounds" from a table that only shows the imported corpus, when a source
declares a set, or a colleague added rows, or nobody ever asked. The distinction that
must survive is **`not_queried` ≠ `empty`**.

## 2. What is deliberately *not* built

- **No new source, no new external call.** Every leg is a read of stored rows. The audit
  can therefore run without a user action (unlike B-24's declared lookup, which calls
  ChEMBL and stays user-triggered, `AGENTS.md` §16).
- **No stored verdict.** The report is computed on read, like the potency class, so a
  later retrieval or import cannot leave a stale status behind (`AGENTS.md` §11).
- **No snapshot leg.** B-23 does not exist, so a snapshot leg could only ever read "not
  configured". The report *says* so in its notes instead of carrying a dead column.
- **No claim about the family's complete publication set.** SPAgo knows the documents it
  imported; the true sibling set needs a bibliographic source (B-22). The report states
  this limit next to the rows rather than implying completeness.
- **No cross-leg totals.** Each leg is its own fact (§10/§11): a declared compound is not
  an occurrence, and the report never sums them into one "compounds" number.
- **No new UI destination.** One compact strip in the patent view, collapsed by default,
  reusing the existing coverage-chip vocabulary (`§17`, `§18`).

## 3. Design

### 3a. The rule (`patent-coverage-v1`)

Per publication, three **legs** (each with its own state and counts) and one **headline
status** derived by a fixed order. The rule version travels with every row and export.

Legs and their states:

| Leg | `has_records` | `asked_empty` | `failed` | `not_queried` |
| --- | --- | --- | --- | --- |
| `corpus` | live mentions > 0 | the document is imported, 0 live mentions | — | the document is not in the corpus |
| `declared` | a lookup declares ≥ 1 compound | the lookup ran (`complete`/`partial`/`empty`) with 0 compounds | the lookup is `failed` | no lookup stored |
| `supplement` | confirmed (`user_curated`) rows cite it | — (a leg nobody used is `not_queried`) | — | no rows cite it |

The `supplement` leg additionally reports `unconfirmed` rows (a stored proposal that no
person has confirmed, B-25) as their own count, never mixed into `has_records`.

Headline order, each naming the leg it came from:

1. `corpus` — the corpus holds live mentions (the strongest stored answer: an actual
   imported occurrence).
2. `declared` — a source's declared set exists for this number.
3. `supplement` — confirmed hand-added rows cite it.
4. `proposed` — only unconfirmed proposals exist (a bundle awaiting review).
5. `empty` — no leg has records and **at least one applicable leg was asked**.
6. `failed` — nothing was found and an asked leg failed (the ask did not complete).
7. `not_queried` — nothing applicable was ever asked.

`unqueried` names the legs that were never asked and could still add records, so `empty`
is never read as "nothing exists".

### 3b. Matching a publication number

The requested number is normalized with `domain.patent_numbers.patent_tokens` — the one
definition of "the same publication" this codebase has (B-03) — and compared, in Python,
against the corpus document identifiers read in one metadata pass (`_tolerant_matches`'
approach, measured at 155 ms for 50 000 documents in
`benchmarks/tolerant-lookup-2026-09-16.md`). The declared and supplement legs store
*normalized* values already (`patent_source_lookups.publication_number`,
`measurements.document_patent_number`, `target_supplement_remarks.patent_number` written
through `normalize_patent_number`), so those two legs compare tokens exactly and stay
indexed.

A requested number that matches **two** stored documents is reported as ambiguous on that
row (both identifiers named) rather than silently picking one (`AGENTS.md` §10) — the
same rule `find_patent` follows.

### 3c. Service

`services/core/spago_core/services/coverage.py`:

- `COVERAGE_RULE = "patent-coverage-v1"`, `COVERAGE_RULE_TEXT`,
  `MAX_COVERAGE_PUBLICATIONS = 50` (refused above the bound, §13).
- `audit_publications(engine, publications) -> CoverageReport` — deduplicated, order
  preserved, bounded; the report carries `notes` (the snapshot limit, the corpus-set
  limit, a failed leg being an incomplete ask).
- `render_coverage_markdown(report)`, `render_coverage_csv(report)` — long form (one row
  per publication-leg) plus a summary block, so the operator can re-derive every number.

### 3d. Serving

- `POST /api/v1/patents/coverage` — body `{"publications": ["US10508115", "WO 2019/047734", …]}`,
  response is the report (bounded, 422 above `MAX_COVERAGE_PUBLICATIONS` / empty list).
- `POST /api/v1/patents/coverage/export?format=csv|markdown|json` — same body, a file
  with the rule in it (the B-24 export pattern; headers
  `X-Spago-Coverage-Rule` / `X-Spago-Coverage-Publications`).
- No per-row external call, no per-document fan-out: the reads are grouped for the whole
  batch (corpus metadata + mentions, declared lookups, target-led rows, supplement rows),
  all bounded by the number of publications asked about.

### 3e. Surface

`apps/web/src/components/PublicationCoverage.tsx`, mounted in the patent view under the
family heading (and on the 404 "corpus does not hold it" path, where coverage is the
question the reader actually has):

- collapsed by default: one line, `Coverage: N of M documents have compounds · k not
  asked` with the status chips;
- expanded: one row per publication (number, `doc_type`, the three legs with their
  counts/states, the headline chip, the reason sentence);
- clicking a document's number selects that document (reuses `handleSelectDoc`);
- an **Export** control for the Markdown/CSV file (operator use), reusing the existing
  quiet-button style.

### 3f. Operator script

`scripts/patent_coverage.py` — `--patents …`, `--patents-file …`, `--column`,
`--database-url`, `--json`, `--quiet`, `--out PATH |-` (mirrors
`scripts/patent_source_lookup.py` and `scripts/cohort_coverage.py`). Runs against the
database directly, no HTTP: an operator can audit a portfolio list on the workstation.

## 4. Verification

- Unit/DB: the corpus leg (mentions > 0 / imported with 0 mentions / not in the corpus);
  the declared leg (complete with compounds / complete-empty / failed / never asked); the
  supplement leg (confirmed rows, unconfirmed proposal rows, withdrawn rows excluded);
  the headline order (corpus beats declared beats supplement); `proposed`; `empty` with
  `unqueried` naming the legs nobody asked; `not_queried` for an unknown number;
  normalization (`US-10508115-B2` finds a document stored as `US10508115`); ambiguity
  reported, not guessed; the bound refused.
- API: the route's shape, the empty-list 422, the over-bound 422, the export's three
  formats and headers, and that a report row's counts equal a direct SQL count
  (reproducibility, the item's acceptance sketch).
- Script: a manifest file run against the test database prints the summary; `--json`
  round-trips.
- Browser (local stack, current checkout): the family view's strip on a family with mixed
  coverage, its expanded table, the document jump, the export control; the 404
  single-publication path.
- Docs: `docs/online-capability.md` §3a bullet, `README.md`, `docs/runbook.md` §2.6
  recipe, `benchmarks/patent-coverage-2026-09-16.{md,json}` recorded from the live local
  stack (a corpus family, a declared-only publication, and a number nobody asked about).
- Full suite + `npm run build`; `rtk git diff --check`.

## 5. Result

**Delivered** (2026-09-16). Class **NEXT → CORE for the patent loop**: it is the surface that
stops the compound table from being read as the whole answer.

| Piece | Where |
| --- | --- |
| Rule + models | `domain/models.py` (`COVERAGE_RULE`, `CoverageAnswer`, `CoverageLeg`, `PublicationCoverage`, `CoverageReport`) |
| Service | `services/core/spago_core/services/coverage.py` (`audit_publications`, `merge_coverage_reports`, `render_coverage_csv`, `render_coverage_markdown`) |
| Serving | `POST /api/v1/patents/coverage`, `POST /api/v1/patents/coverage/export?format=markdown\|csv\|json` |
| Surface | `apps/web/src/components/PublicationCoverage.tsx` — the collapsed *Coverage* strip in the patent view and on the 404 path |
| Operator path | `scripts/patent_coverage.py` (`--patents`, `--patents-file`, `--format`, `--out`, `--json`) |
| Tests | `services/core/tests/test_b26_coverage_audit.py` (39 tests) |
| Evidence | `benchmarks/patent-coverage-2026-09-16.{md,json}` |

Checks, as run (all on this checkout unless stated):

- **Backend suite**: `services/core/.venv/bin/python -m pytest tests -q` — 741 tests, exit 0.
- **B-26 suite**: 39 tests, exit 0, covering the legs, the headline order, the request bound,
  the API shape and the export formats.
- **Frontend**: `npm run build` (tsc -b + vite build), exit 0.
- **Live stack (docker compose, image rebuilt from this checkout)**: measured HTTP latency and
  payload (`benchmarks/patent-coverage-2026-09-16.md`), plus printer-side output from
  `scripts/patent_coverage.py` against the same database — identical statuses and counts.
- **Browser (live stack, production bundle served by the app image)**: the 404 path on
  `US10508115` (collapsed line = *1 of 1 publication holds compounds · 1 source-declared ·
  1 with a leg never asked*; expanded row names both declared answers — 191 rows / 73
  compounds from a stored lookup plus target-led rows — and `corpus, supplement` as never
  asked); the family view on `WO-2020-123456-A` (`1 corpus occurrence`, and clicking the
  row's number selected that document — `doc=66666666-…` in the URL); the never-asked path on
  `US9999999` (all three legs `never asked`, headline `not_queried`, reason naming the corpus
  limit); and the export control, which fired
  `POST /api/v1/patents/coverage/export?format=markdown` (fetch, 200, 2.7 KB) from the UI.
  States: loading (`— reading what is stored…`) seen on first paint; the error state checked by
  blocking `*/api/v1/patents/coverage*` (`Network.setBlockedURLs`) — after the retries were
  exhausted the strip read *the audit could not be read* with the reason banner and **no
  counts at all**, so a failed read cannot be misread as an absence; removing the block
  restored the real line. Not exercised in the browser: the ambiguous-match row (no number on
  the live stack matches two stored documents — covered by a unit test instead).

What the round changed on the way (found while verifying, not planned):

- `holds_records` was added to the report's `totals` so the strip's summary line reads the
  service's own headline count instead of re-deriving which statuses "hold" (§11) — plus a
  test that pins it.
- The strip filters its publication list with the mirrored client-side shape rule before
  asking: the synthetic fixture's ids (`DEMO-PATENT-A`) are deliberately not publication
  numbers, and a request carrying none of them is refused 422 — there is no publication to
  report on, so no strip is rendered rather than a refusal banner.
- The notes/export `<details>` is controlled state: on the local stack it snapped shut
  between opening it and clicking export (a DOM-owned marker reset by an unrelated
  re-render). Holding the open/closed state in the component keeps the reader's intent,
  matching the B-24 panel.

## 6. Open questions settled while implementing

- **Does the audit need its own leg for a licensed snapshot?** No. B-23 does not exist, so a
  snapshot leg could only ever read "not configured"; the report says so in its notes
  instead of carrying a column that cannot be filled. When B-23 lands it adds a fourth leg
  — the model already carries `answers` per leg, so nothing else has to change.
- **Does a target-led row belong in the `declared` leg or its own?** In `declared`, as a
  separate `answer` inside the leg: both are a source's statement about the number, but a
  per-publication lookup and a target-led retrieval answer different questions, and the row
  keeps them apart (counts per answer) instead of merging them into one number.
- **What happens to a publication whose number carries no digits?** It is refused with a
  reason, and the surface never asks (see §5).
- **Should the audit be persisted or cached?** No. It is computed on read from stored rows,
  so there is no verdict to invalidate; the strip marks it stale after 60 s and re-reads.
