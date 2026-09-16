# SPAgo

**Small molecule patent analysis GO**

SPAgo connects patent search, chemical structures, bioactivity, SAR, claims and source
evidence in one browser-first workflow. It is built for medicinal and computational
chemists and patent researchers who today move repeatedly between patent websites,
PDFs, chemistry tables, public databases and general-purpose LLMs.

**Where to read what:** the standing product contract (product decision,
differentiation, domain and evidence model, data sources, query and UI model, milestone
status) is [`PROMPT.md`](PROMPT.md); contributor rules are [`AGENTS.md`](AGENTS.md);
what this build supports — and deliberately does not — is
[`docs/online-capability.md`](docs/online-capability.md); deployment and operations are
[`docs/runbook.md`](docs/runbook.md); recorded measurements are in
[`benchmarks/README.md`](benchmarks/README.md).

**License:** [Apache License 2.0](LICENSE) · Copyright 2026 chenDeepin · see also
[`NOTICE`](NOTICE) and [`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md).

---

## Status — 2026-09-16

**Implemented and locally verified** (per-round records are linked at the end of this
section; local single-user mode needs no accounts, `SPAGO_AUTH_MODE=disabled`):

- **Target-led open-database investigation (ONLINE-00).** Resolve a target (UniProt),
  then retrieve bounded candidates and measurements from ChEMBL, BindingDB and PubChem,
  each with its recorded outcome (`complete` / `partial` / `empty` / `failed` /
  `not_queried`). Deterministic modality classification keeps small molecules apart from
  peptides and biologics, and every measurement carries an explicit evidence class
  (measured binding, interaction disruption, functional effect, screening).
- **Potency classes and a screening-reference verdict (ONLINE-06).** Deterministic
  classes under one versioned threshold (`potency-gate-v1`), computed from stored rows on
  read and exported together with the threshold that produced them, plus source-declared
  patent / DOI / PMID per measurement. The verdict is a **count under a stated policy, not
  a biological or legal conclusion**, and a thin set is never rendered as a negative
  result.
- **Hand-added literature rows (ONLINE-07).** `POST /targets/{id}/supplements` stores a
  user's own literature or patent rows with a mandatory note, the same RDKit normalization
  and InChIKey identity as a retrieved structure, `user_curated` provenance that nothing
  promotes, and a separate remark table for rows whose structure is not public (never
  counted as a measurement). There is no delete path yet; a corrected row is re-submitted.
- **Scoped, cited summaries (ONLINE-01)** for a patent family, one document or a target,
  with separate prompt versions and cache keys per scope, and an offline extractive
  provider that needs no model.
- **Validated natural-language search (ONLINE-02):** a request becomes a typed plan
  against a fixed operation allowlist, shown for review and executed only on explicit
  action.
- **Hosted access (ONLINE-03):** invitation-only sessions, per-owner projects and
  analyses, fail-closed anonymous access, model-usage quotas, readiness checks and a
  hosted runbook.
- **Patent chemistry, search and export (M0–M5, product readiness):** one-command local
  startup, saved projects that reopen across sessions and restarts, exact /
  substructure / similarity search on cartridge-indexed chemistry, typed
  targets/assays/measurements with provenance, a thin MV3 Chrome context bridge, and
  CSV/SDF export whose scope equals exactly the current filter (re-executed
  server-side, including rows the browser never loaded).
- **Real patent data path:** `scripts/extract_surechembl.py` extracts a patent-family
  package from the official SureChEMBL bulk release (EMBL-EBI FTP, Parquet, CC BY 4.0)
  over HTTP range reads, and `python -m spago_core.import_package <dir>` ingests it with a
  durable import job and file checksums (verified with the real losartan and sildenafil
  families).

**Not done — do not mistake implementation for acceptance.** There is no hosted
deployment, no invited user has completed the workflow, and the live model smoke covers
**one** provider (DeepSeek `deepseek-flash`) rather than compatibility in general. Source
refresh does not yet retract deleted or invalid mappings, and an interrupted import job
has no recovery protocol. The gate a deployment must pass — checklist and the
invited-user script — is
[`docs/online-capability.md`](docs/online-capability.md) §6; round records are
[`docs/plans/2026-09-15-online-llm.md`](docs/plans/2026-09-15-online-llm.md) §4,
[`docs/plans/2026-09-15-bindingdb-io-port.md`](docs/plans/2026-09-15-bindingdb-io-port.md)
§6–§7 and [`docs/archive/2026-09-15-product-readiness.md`](docs/archive/2026-09-15-product-readiness.md).

Live coverage is genuinely thin for some acceptance targets (human TSLP has one
small-molecule candidate in these sources; IL-6R has one, and BindingDB does not answer
for it). That is reported honestly rather than as promising inhibitor coverage:
[`benchmarks/online00-coverage-2026-09-15.md`](benchmarks/online00-coverage-2026-09-15.md).

The dataset shipped with this repo is a **synthetic demo fixture** (`DEMO-*`
identifiers). It is not scientific data.

---

## Quick start (local)

```bash
docker compose up -d --build
# open http://localhost:8000 and search: DEMO-PATENT-A
```

For development without Docker rebuilds, see `services/core/README.md` (backend hot
reload against the compose `db` service, Vite dev server on :5173).

### Development checks

`scripts/run_checks.sh` runs the full backend suite against a reachable scratch
PostgreSQL with the RDKit cartridge, then the frontend typecheck and production build
(`--no-pg` explicitly checks only the subset that needs no database). Recorded
measurements and their method notes are indexed in
[`benchmarks/README.md`](benchmarks/README.md).

### Loading real patent data

The demo fixture is optional. Real patent-family chemistry comes from the official
SureChEMBL bulk release: extract a family package with
`scripts/extract_surechembl.py --release YYYY-MM-DD --patent <PUBLICATION>` inside the
app container (HTTP range reads, fresh output directory, bounded package size), import it
with
`docker compose run --rm -v "$PWD/local:/import" app python -m spago_core.import_package /import/<package>`,
and set `SPAGO_SEED_MODE=none` so the demo fixture is never mixed in. Coverage is limited
to what you imported; an uncovered publication number returns an explicit not-found.
Backup, restore and upgrade steps are in [`docs/runbook.md`](docs/runbook.md).

**A list of patents, in one run.** Scaling that to a screening set or a portfolio is
`scripts/corpus_batch.py`, which chunks a publication list, extracts and imports each
chunk, and keeps a resumable `STATE.json` — a re-run skips what already landed:

```bash
services/core/.venv/bin/python scripts/corpus_batch.py \
    --patents my-patents.txt --release 2026-09-08 --workdir var/batch-2026-09-16
```

It exits non-zero and prints every requested publication that is **not** in the corpus
when the run ends, so "loaded" is never assumed.

**What is loaded.** `GET /api/v1/corpus` reports counts per dataset version, read from
the corpus tables; the top-bar dataset badge opens the same view
(`Loaded corpus`). From a terminal, the identical numbers and a list check:

```bash
python -m spago_core.corpus_status                        # table of versions and counts
python -m spago_core.corpus_status --patents my-patents.txt   # exits 1, lists what is missing
python -m spago_core.corpus_status --json > corpus.json    # for a run record
```

### Optional LLM summaries

Set `SPAGO_LLM_BASE_URL`, `SPAGO_LLM_MODEL` and, if the endpoint requires it,
`SPAGO_LLM_API_KEY` in a local `.env` (see `.env.example`), then rebuild and select LLM
mode in the existing AI tab. The base URL includes the full API prefix (for example
`https://provider.example/v1`); SPAgo appends only `/chat/completions`. These are
placeholders, not a default external target, and `configured` means the local settings
are present — not that a model call succeeded.

The request sends `model`, `messages`, `stream: false` and `max_tokens`, plus two opt-in
compatibility switches that stay off unless the operator sets them:
`SPAGO_LLM_DISABLE_THINKING=true` sends `thinking: {"type": "disabled"}` for models that
reason by default, and `SPAGO_LLM_JSON_MODE=true` sends
`response_format: {"type": "json_object"}`. Strict endpoints reject unknown parameters,
which is why neither is sent by default; the adapter does not support every vendor API.
For a host-local endpoint use `http://host.docker.internal:<port>/v1` (Compose maps that
hostname on Linux); container `localhost` addresses the app container itself.

The supported deployment uses **one app worker** — the two-call limit and
duplicate-in-flight tracking are process-local — and keeps the default app binding to
`127.0.0.1`; a shared deployment with a provider key needs deployment-side authentication
first. "Stop waiting" stops the browser from waiting; it does not acknowledge provider
cancellation. The recorded live smoke
([`docs/archive/2026-09-15-llm-live-smoke.md`](docs/archive/2026-09-15-llm-live-smoke.md))
is one provider at 85 % single-attempt compliance, not a compatibility claim.

**Stored summaries.** Every generated summary is kept (`ai_analyses`) and is readable
again from **Analyses** in the top bar — scope, model, prompt version, data version,
billed tokens — without calling the provider a second time. Each one exports as
Markdown whose header carries those fields plus the citations, and an entry whose data
or potency policy moved since it was generated is labelled out of date instead of being
shown as current.

**Where a source's own patent reference comes from — and where it stops.** A target's
header carries a *Source notes and reference coverage* disclosure: for each retrieval,
the source's notes (including "the document lookup bound was reached"), and a disjoint
count of how each kept record's source-declared reference resolved — patent number, DOI,
PubMed id, or the reason none was attached (the document declares none, the source does
not know the cited document, the bound was reached, the lookup failed, the record cites
no document). Measured live on the acceptance cohort
([`benchmarks/reference-declarations-2026-09-16.md`](benchmarks/reference-declarations-2026-09-16.md)):
135 of IL-6's 166 kept records carry a source-declared patent, TSLP's 111 carry only
DOIs, and 1,210 of EGFR's 2,397 cite a document ChEMBL does not return. A bound or a
failed lookup is reported as a fact about that retrieval — never as "no patent", and
never as an occurrence in SPAgo's corpus, which stays a separate labelled fact.

**A patent number alone can now reach compounds.** The corpus used to be the only answer
to "what does this patent contain": a publication that was never imported (or imported
thinly) showed an empty table, and the search box reported it as not covered. The patent
view now offers the other direction — *ask a public source what it declares for this
publication number* — under a stated, versioned name-match rule
(`chembl-document-patent-body-v1`: the source's `patent_id` normalizes to the same
country-plus-digits token). Live on `US10508115`: 134 declared records for 73 compounds out
of 402 seen (the 268 kinetic rows without a numeric value are counted, not dropped), on
[`benchmarks/patent-source-declarations-2026-09-16.md`](benchmarks/patent-source-declarations-2026-09-16.md).
A number the source does not know returns **empty with the rule** — a different answer from
*failed* and from *not queried* — and a document the body search returns under a different
number is a **near match**: listed with its number and excluded, never merged.

A declared compound is deliberately not an occurrence (§11): it lands in its own tables, it
writes no `compound_mentions` row, it never changes a family's compound count, and it is
shown in its own panel under its own vocabulary ("declared", the rule, the policy) with CSV
and SDF exports that name what they hold. Read [what a source declares for a
publication](docs/online-capability.md) for the served contract.

---

## How it works

The product loop the implementation is built around:

```text
Search → patent family → compounds → structure filtering → bioactivity/SAR
      → claims + evidence → AI-assisted interpretation → saved project
```

- **Adapters isolate sources.** External APIs and datasets enter through
  `external source → adapter → normalized domain model → service layer → API → UI`; UI
  code never sees a SureChEMBL, OPS, ChEMBL, BindingDB or PubChem schema. Each adapter
  reports source name and version, retrieval timestamp, errors and rate-limit state.
- **Chemistry is deterministic.** RDKit (through the PostgreSQL cartridge) owns canonical
  identity, fingerprints, substructure, similarity, scaffolds, descriptors and depictions.
  LLM output never decides molecular equivalence, and a potency class is computed from
  stored rows under a stated threshold — never written by a model.
- **Evidence and provenance are typed.** Every scientific datum carries a state
  (`source_fact`, `database_curated`, `machine_extracted`, `llm_inferred`, `user_curated`)
  and, where possible, a locator back to its document; nothing silently promotes an
  inference to a source fact.
- **Two data layers, chosen per workload.** Parquet + DuckDB for bulk patent chemistry and
  analytical filtering; PostgreSQL + RDKit for interactive structure search, projects,
  measurements and evidence. The complete bulk dataset is not copied into PostgreSQL.
- **Large data stays server-side.** Default API page 100, ordinary maximum 500, with
  server-side filtering, sorting and cancellation, virtualized rendering and lazy
  molecule depiction.

The full contract — product decision, differentiation, domain and evidence model, data
sources, query architecture, UI model, non-goals — is [`PROMPT.md`](PROMPT.md).

---

## Repository layout

```text
apps/web/                 React + TypeScript workspace (Vite)
apps/chrome-extension/    optional MV3 context bridge (URL-only detection)
services/core/            FastAPI service
  spago_core/adapters/    external sources: SureChEMBL, EPO OPS, ChEMBL, BindingDB,
                          PubChem, UniProt, LLM endpoint
  spago_core/chemistry/   deterministic chemistry: RDKit engine, modality, activity classes
  spago_core/services/    discovery, reference verdict, supplements, summaries, export,
                          projects, planner, jobs
  spago_core/api/         HTTP routes
  tests/                  unit, chemistry, adapter contract, API, integration, evaluation
migrations/               versioned SQL schema (forward-only)
data/fixtures/            small sealed fixtures + synthetic demo data
benchmarks/               recorded measurements and their method notes
scripts/                  extraction, check runner, LLM evaluation, mock endpoint
docs/                     architecture, ADRs, capability statement, runbook, plans, archive
docker/                   database image init
```

Do not read this as permission to create empty packages; create a module only when
implementation requires it.

---

## Milestones

| Milestone | State |
| --- | --- |
| M0 Foundation and benchmarks | implemented; [`docs/archive/2026-09-14-m0-foundation.md`](docs/archive/2026-09-14-m0-foundation.md) |
| M1 Patent chemistry viewer | implemented, with the embedded Ketcher editor (cost and behaviour: `benchmarks/online08-structure-editor-2026-09-16.md`) |
| M2 Structure search | implemented (exact / substructure / similarity, cartridge-indexed) |
| M3 Bioactivity and SAR | implemented for open sources; see the online capability statement |
| M4 Chrome companion | thin MV3 bridge; unpacked load, detection, handoff and side-panel render verified in a real browser (`apps/chrome-extension/verify-in-chrome.js`); toolbar click not covered |
| M5 Evidence-grounded AI | implemented offline and against one live provider |
| ONLINE-00…07 | implemented locally; see **Status** above |
| ONLINE-04 hosted deployment, ONLINE-05 invited-user acceptance | **open** — gate and script: [capability §6](docs/online-capability.md) |
| M6 PDF/OCSR fallback | intentionally not started (structured sources first) |

Deliverables and exit criteria per milestone are in [`PROMPT.md`](PROMPT.md) §14.

---

## Boundaries

SPAgo is not a patent-office replacement, an autonomous legal-advice or
freedom-to-operate engine, a complete Markush platform, a generalized AIDD IDE, a
docking/MD/FEP platform, a synthesis planner, an ELN or LIMS, a web crawler designed to
defeat access restrictions, or a full DataWarrior replacement. It does not automate
Espacenet navigation, pagination, clicks, CAPTCHAs or robot-detection bypass.

---

## License

SPAgo is licensed under the [Apache License, Version 2.0](LICENSE).

```text
Copyright 2026 chenDeepin
```

- Project attribution: [`NOTICE`](NOTICE)
- Included tools and data-source terms: [`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md)

Commercial use, modification and redistribution are permitted under Apache-2.0;
charging for support, hosting or related services is allowed, and the open-source grant
itself remains royalty-free for recipients of the code.

SPAgo may assist with patent organization and evidence-linked chemistry review. It does
not provide legal advice or definitive freedom-to-operate conclusions. External datasets
and APIs (for example SureChEMBL, EPO OPS, ChEMBL, BindingDB, PubChem and LLM providers)
remain under their own Terms of Use.
