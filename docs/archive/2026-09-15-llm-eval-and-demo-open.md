# Demo-open affordance + ONLINE-01 evaluation baseline — 2026-09-15

> Archived 2026-09-16 (both parts implemented and measured; §7.1 closes the
> citation defect it found). Record cited by `docs/online-capability.md` and
> `docs/archive/2026-09-15-online-llm.md` §4.

Status: **implementation plan, owner-approved scope** (owner selected both items
after the browser check in `2026-09-15-llm-live-smoke.md` §10). Working tree stays
uncommitted until the owner reviews it.

## 0. What this round is for

Two items came out of the browser round:

1. **The demo onboarding is a dead end.** With the synthetic fixture, the empty
   state says "try `DEMO-PATENT-A`" and the 404 message says "…or try the demo
   patent", but the identifier cannot be opened from the search box: the client's
   deterministic shape rule (`looksLikePublicationNumber`) classifies it as free
   text, so it goes to the offline planner, which extracts no step and renders a
   plan card with nothing to run.
2. **ONLINE-01 has no evaluation baseline.** Prompt/model changes are currently
   judged against one ad-hoc 13-call run recorded in the live-smoke record; there
   is no runner and no reproducible record, so a prompt-hardening change cannot be
   compared with anything. Three residual classes are known: an unknown fact ref,
   malformed JSON despite JSON mode, and a model-invented placeholder token
   ("DELETED") that structural validation cannot see.

## 1. Facts checked before planning (current files, current behaviour)

| Question | Checked result |
| --- | --- |
| Where does the search box decide the route? | `apps/web/src/App.tsx::handleSearch` — `looksLikePublicationNumber(value)` → patent lookup, otherwise `planMutation.mutate({query})`. The rule lives in `apps/web/src/state/url.ts`: `/^[A-Z]{2}\d{5,12}[A-Z]\d?$/`. |
| Can the demo identifier ever match it? | No. `DEMO-PATENT-A` has no digit run; the fixture's identifiers are deliberately not publication-number shaped (`docs/online-capability.md` §8). |
| Is the hint actionable today? | No. `apps/web/src/components/states.tsx::EmptyState` renders `try <code>{demoHint}</code>` as plain text; `App.tsx` hardcodes `demoHint="DEMO-PATENT-A"` when `datasetInfo.synthetic`. |
| Does the 404 path offer an action? | No. `SearchBar` renders `error` as a `search-error` span; `App.tsx` appends "Check the number, or try the demo patent." |
| What can an action call? | The same server lookups the search path uses: `queryKey: ["patent", value]` (`GET /api/v1/patents/{publication_number}`). The server is authoritative; a 404 renders the existing error state. |
| Frontend test tooling? | No test runner in `apps/web/package.json` (`dev`/`build`/`preview`). Verification is `tsc -b && vite build` plus the browser check — no new dependency for one control (AGENTS.md §23). |
| Eval methodology available? | `services/core/spago_core/services/ai.py` exposes the shipped pieces: `collect_facts`, `finalize_snapshot`, `_validate_llm_output`, `_generate_accepted`, `PROMPT_VERSION_BY_SCOPE`, `MAX_OUTPUT_TOKENS`. `_generate_accepted` is the shipped bounded-retry policy (identical request, ≤ 2 calls). |
| Does the snapshot/prompt input have a single owner? | Currently assembled inline inside `summarize` (`collect_facts` → target `coverage_note` → `finalize_snapshot` → `summary_scope`). An evaluation script that re-assembles it would measure a different input than the app sends. |
| Where do benchmark records live? | `benchmarks/*.md` + `*.json` are the committed records (see `benchmarks/README.md`); `benchmarks/results/` is gitignored. |
| Cost of a baseline run? | One family + one document + one target call ≈ 2.3k–13.1k tokens each at the measured shapes; thinking is disabled, so the budget is bounded by `MAX_OUTPUT_TOKENS = 4096` per call. |

## 2. Part A — demo-open affordance

**Problem restated as a contract:** the app may open a record whose identifier the
*deployment itself* published as its sample, without turning free text into an
identifier. The search box keeps its deterministic rule; the affordance is an
explicit action with a named owner ("open the synthetic sample record").

Chosen design (smallest that removes the dead end):

- `EmptyState` gains an optional `onOpenDemo?: (identifier: string) => void`. When
  provided, the hint renders a button ("Open `DEMO-PATENT-A`") instead of a bare
  `<code>`; without it (real deployments) the hint is unchanged.
- `SearchBar` gains an optional `errorAction?: { label: string; onClick: () => void }`,
  rendered next to the existing error text; App passes it only for the
  `404 + synthetic dataset` case that already appends "try the demo patent".
- `App` owns one new callback, `openPatent(identifier)`: the same state/URL
  transitions the publication-number branch of `handleSearch` performs
  (`setTargetQuery(null)`, `setSubmittedQuery`, `updateUrl(..., "push")`), so the
  same query key, the same 404 handling and the same URL state apply. `handleSearch`
  is refactored to call it, so there is exactly one owner of "open this patent".
- Not doing: changing the client's identifier rule, adding a demo keyword list, or
  letting the planner resolve the synthetic sample. §12 keeps free text out of
  scientific arguments; the fixture identifier stays a deliberate non-match.

Acceptance: from a cold load, the empty-state control opens `DEMO-FAMILY-1`
(3 documents, 10 compounds) and the URL carries `q=DEMO-PATENT-A`; a 404 for a
publication-number-shaped query offers the same control and it works; with a
non-synthetic dataset no new control appears.

## 3. Part B — ONLINE-01 evaluation runner and baseline

**Problem restated as a contract:** a change to prompts, budgets or the endpoint
must be judgeable against a recorded number produced by the shipped request path,
without polluting the demo ledger or the analysis cache.

Chosen design:

- **Extract the shipped input builder** in `ai.py`:
  `build_llm_snapshot(engine, scope, scope_id, include_all_modalities=False)`
  returns exactly the dict `summarize` feeds to the provider (facts → target
  `coverage_note` → `finalize_snapshot` → `summary_scope`). `summarize` calls it,
  so the evaluation and the app cannot drift. No behaviour change.
- **New runner** `scripts/llm_summary_eval.py` (tooling, like
  `scripts/mock_llm_endpoint.py`):
  - builds one provider per scope from the environment (`SPAGO_LLM_*`, plus
    `SPAGO_LLM_DISABLE_THINKING` / `SPAGO_LLM_JSON_MODE`) through the shipped
    `parse_endpoint`;
  - resolves its inputs from the database (`--family-id`, `--document-id`,
    `--target-id`; defaults: the first family, its first document, the first
    target, all recorded in the output);
  - per sample calls the **shipped policy** `ai._generate_accepted(provider, snapshot)`
    and records, per attempt, latency, usage, the model text head, and — for
    rejected attempts — the class and detail produced by the same pure validator
    the service runs (`ai._validate_llm_output`), so attempt-level compliance is
    measured rather than inferred;
  - reports request-level success (with the one re-sample), attempt-level
    compliance, per-class rejection counts, median latency and summed tokens;
  - **writes nothing to the database**: no `ai_analyses` row (no cache entry) and
    no `llm_usage` row. The framing is stated in the record: the provider bills
    these calls even though the SPAgo ledger does not, exactly like the 13-call
    measurement in the live-smoke record;
  - prints the planned call count and requires `--yes` (plus `--dry-run`) so a run
    is always an explicit spending decision; `--samples` defaults to 1.
- **Recorded baseline** `benchmarks/online01-llm-eval-2026-09-15.md` + the runner's
  JSON at `benchmarks/online01-llm-eval-2026-09-15-run1.json` and `-run2.json`,
  stating model, endpoint fingerprint, prompt versions, budgets, flags, per-scope
  numbers and the residual classes. The three known residual classes are listed
  there as the judgment set a prompt change must move (they are the "evaluation
  set" until a sealed input fixture exists). Each scope's exact provider input is
  stored in the JSON, so a later run can diff what changed rather than only see
  that a hash moved.

Bounds: scopes × samples × 2 provider calls maximum, printed before the run; the
runner refuses to start without a configured endpoint, and per-call latency is
recorded (the adapter's 60 s deadline already bounds a hung call).

Acceptance: the runner reproduces the recorded baseline shape on demand
(`--samples 1` finishes in one pass with the recorded numbers), the JSON contains
per-attempt classes, no `ai_analyses`/`llm_usage` row appears for the run, and the
record names what the numbers do and do not prove (one provider, synthetic demo
input, one business day).

## 4. Verification plan for this round

- Frontend: `npm run build` (includes `tsc -b`), then browser checks at 1080×927
  for the two Part A paths, plus a non-synthetic negative check (the control must
  not appear when `dataset_info.synthetic` is false — checked through the API
  response the UI reads rather than by mutating the demo dataset).
- Backend: full `pytest` suite after the `build_llm_snapshot` extraction.
- Evaluation: one baseline run per scope with `--samples 3` (≈ ≤18 provider calls),
  recorded in `benchmarks/`; the runner's own dry-run output is kept.
- Docs: this record gets the results section; `docs/online-capability.md` §8
  (demo-hint gap), the live-smoke record §10.5 and `docs/archive/2026-09-15-online-llm.md`
  §4.5 are updated to point at what is now fixed or measured.

## 5. Part C — the baseline's first finding, and the fix it justifies

The baseline (2 runs, 18 requests, 23 calls, 141,648 billed tokens) is recorded in
`benchmarks/online01-llm-eval-2026-09-15.md`. Its dominant refusal class is a
contract defect, not model noise: 4 of 7 refused calls cited an *input key*
(`coverage`, `measurement_total`, `modality_breakdown`, …) as a fact ref, because
aggregate blocks in the snapshot have no `ref` while the prompt required every
paragraph to cite one. Re-sampling does not correct it (one request repeated the
class), so "retry harder" is not a fix.

Scope for the fix (smallest change that removes the contradiction):

- **Input contract, not snapshot shape**: keep the snapshot byte-identical, so the
  before/after comparison isolates the instruction. Do not add ref namespaces that
  the citation UI would have to learn (`coverage:…` renders as an unknown kind).
- `_COMMON_RULES` rule 3 states what a ref is ("only the `ref` fields inside the
  input; an input key such as `coverage` is not a ref") and how a coverage or total
  statement is cited (with the input's root `family:`/`document:`/`target:` ref,
  which is already allowed and already renders as a scope chip).
- Bump the three prompt versions (`family-summary-v6`, `document-summary-v5`,
  `target-investigation-v5`). The version is part of the analysis cache key, so
  cached summaries produced under the old instruction are not served as if they
  came from the new one.
- Correct the stale version list in `docs/online-capability.md` §1 (it still said
  v2/v1/v1) and the adapter's fallback default.

Acceptance: the same runner, same model, same scopes, `--samples 3`, recorded as
`benchmarks/online01-llm-eval-2026-09-15-run3-after.json`; the aggregate-ref class
must be gone or clearly reduced, request success must not regress, and both facts
must be stated together in the record — including the possibility that the change
does nothing.

### 5.1 Result (run 3, same runner, same day)

- Family and document: **6 of 6 calls accepted on the first attempt, zero
  citation refusals** (before: 10 of 12 first-attempt, 5 refusals). The class this
  change targeted is gone in those two scopes.
- Target: unchanged (1 of 3 requests answered, 1 first-attempt call of 5). The
  model now cites the per-source `dataset_version` strings instead of the key
  names — same contradiction, different token — because `sources[*]` coverage
  blocks still carry no `ref` to cite.
- Pooled request success 89% → 78% over 18 → 9 requests: not evidence of a
  regression, and not evidence of an improvement; it is too small a sample to
  claim either. Per-scope first-attempt rates are the defensible measurement.
- Therefore: *not* "the citation problem is fixed". Instruction wording is
  exhausted; the remaining class needs the structural fix (per-source refs plus a
  `source` citation kind in `_build_citations`) and its own run, with the UI
  consequence (a ref with no metadata is currently dropped from the citation
  list, not rendered) checked in a browser. Recorded as the next round's
  acceptance, not begun here.

## 6. Round result
Delivered:

- **Part A (demo open)**: `EmptyState` and the 404 message carry an explicit
  control; both paths open `DEMO-PATENT-A` through the same server lookup the
  search box uses, and the URL carries `q=DEMO-PATENT-A`. Verified in the browser
  at 1080×927 when the change was made and re-verified at 1510×927 on the rebuilt
  image afterwards (landing control → `?q=DEMO-PATENT-A`, family `DEMO-FAMILY-1`
  with 3 documents / 10 compounds; a `US99999999A1` search renders the 404 text
  plus an `Open DEMO-PATENT-A` control that opens the same record). The control is
  absent when `dataset_info.synthetic` is false (checked against the API response
  the UI reads). `npm run build` (`tsc -b` + `vite build`) clean.
- **Part B (runner)**: `scripts/llm_summary_eval.py` plus two recorded runs
  (18 requests / 23 calls / 141,648 billed tokens). No `ai_analyses` or
  `llm_usage` row was written (13 rows before and after each run), and the family
  and document input hashes equal the app's own stored rows, so the runner sends
  what the product sends. Each scope's exact provider input is now stored in the
  artifact, so a future run can diff *what* changed instead of only seeing a
  different hash.
- **Part C (the fix the baseline found)**: rule 3 corrected, three prompt versions
  bumped, run 3 recorded (§5.1). Family and document reach 6/6 first-attempt calls
  with no citation refusal; the target scope does not move, and both the record
  and §5.1 say so instead of averaging the result into a single flattering number.
- Tests: backend suite **417 passed**, 0 failed, 0 skipped — including two new
  guards (the root ref is citable in every scope; a prompt-version change
  invalidates the cached analysis) and one that pins the named rejection class in
  the error detail. Frontend `npm run build` clean; `tsc -b` included.

Not done in this round, stated rather than implied: the structural per-source ref
fix and its `source` citation chip, the browser check that chip needs, any second
provider, a non-demo family in the evaluation set, and live re-verification of the
demo-open control at viewports other than 1080×927.

## 7. Part D — structural fix for the target scope's coverage citations

Owner decision (2026-09-15): take the structural fix now, then re-measure.

**Why instruction wording cannot fix it.** The target snapshot's `sources[*]` rows
and its `coverage[*]` rows carry the per-source status, counts and
`dataset_version` strings, and neither carries a `ref`. Run 3 shows what the model
does with that: it cites the version string (`uniprot:2026-09-15`) or the key
(`coverage`, `measurement_total`) because *some* citation is mandatory. The
information is real and the summary is expected to state it, so the input must
expose a legal citation for it.

**Design (target scope only, so family/document measurements stay comparable):**

- `sources[*]` gains `"ref": "source:<source_name>"`; the same ref is added to the
  matching `coverage[*]` rows (which also gain `source_name`, so the mapping is
  visible in the input rather than inferred). A source that failed with no version
  still has a ref — the retrieval's identity is the source, not the version string.
- `allowed_refs` accepts any `ref` present in `sources`/`coverage` (absent refs are
  still skipped, so family/document snapshots are unaffected).
- `_build_citations` gains a `source` kind with a label that states the retrieval's
  facts (`chembl · complete · 111 kept · chembl:2026-09-15`). Frontend: the panel
  renders `kind` + `label` generically, so no component change is expected — the
  stale `CitationRef.kind` union in `apps/web/src/api/types.ts` is extended to the
  kinds the API already emits (`document`, `target`, `candidate`, `source`).
- **Click destination (added while implementing, 2026-09-15).** A generic chip is
  not enough: clicked, it would switch the inspector tab and go nowhere, which
  §18 rules out. The per-source coverage strip in `TargetHeader` is the surface
  that owns those facts, so a `source:<name>` citation now focuses its chip —
  `TargetHeader.coverageChipId(name)` gives both sides one id convention, the chip
  takes a transient `coverage-chip-focused` ring, and `TargetEvidencePanel` routes
  only `source:` refs out to `App::focusSourceChip` (scroll + 2.4 s flash). No new
  panel, no new permanent control, and family/document citation behaviour is
  untouched.
- Target system prompt: state the per-source ref rule (one sentence); the shared
  rules stay unchanged, so `family-summary-v6` / `document-summary-v5` and their
  cached analyses are untouched. `TARGET_PROMPT_VERSION` → `target-investigation-v6`.
- Snapshot byte budget: the target input measured 30,231 B against the 32 KB
  bound, so the added refs must still leave `measurements_listed` unchanged —
  checked in run 4 rather than assumed.

**Acceptance:** unit tests (every `sources` ref is allowed and renders as a
`source` citation with a label; a paragraph citing one validates); `npm run build`;
run 4 with the same runner, target scope plus family/document, with zero
`not-an-input-ref`/`key-cited` refusals in the target scope; a browser check that
the chip renders for a target summary — live if the model cites it, otherwise
through `scripts/mock_llm_endpoint.py`, labelled as the fixture path it is.
Recorded in the benchmark record either way, including "the model still refuses
for an unrelated reason" if that is what happens.

**Sample count for run 4 (decided while running it):** `--samples 6`, not 3. Run 3's
target result was 1 clean first attempt in 3 requests, so the claim under test is a
rate, and n=3 cannot separate "fixed" from "less likely". Family and document run at
the same n so the three scopes stay comparable; the record states the counts rather
than only a percentage. The extra spend is bounded by the plan's own formula
(3 scopes × 6 samples × 2 calls = 36 calls maximum, printed before the run).

### 7.1 Result (run 4, same runner, same day)

Recorded in `benchmarks/online01-llm-eval-2026-09-15.md` §"After the structural
per-source ref fix" with the raw JSON as
`benchmarks/online01-llm-eval-2026-09-15-run4.json`.

- **Unit tests**: `tests/test_online01_scoped_summaries.py` gains
  `test_every_retrieval_is_citable_by_its_own_ref` — the refs in `sources` are the
  ones in the allowed set, the `coverage` projection reuses them, a paragraph citing
  them validates, `_build_citations` returns `kind: source` with `source_name` and a
  label carrying status/kept counts, and a `source:` string the snapshot never
  contained is still refused. Full suite: **418 passed**, 0 failed, 0 skipped.
  `npm run build` (`tsc -b` + `vite build`) clean.
- **Run 4**: 18 requests / 19 calls, **18/18 answered**, 17 first-attempt, 132,574
  billed tokens. Target scope: **6/6 first-attempt, zero citation refusals** (was
  4 refusals in 5 calls in run 3). The accepted JSON in the artifact was read
  directly: all six target runs cite `source:bindingdb`, `source:chembl` and
  `source:pubchem` in dedicated per-source paragraphs, so the new refs are used,
  not merely permitted. The one remaining refusal is another scope and another
  class: a document request wrote `facce3fd-…` without its `document:` namespace.
- **Snapshot budget**: target input 30,231 → 30,411 B against the 32,768 B bound,
  citable refs 52 → 55, `measurements_listed` unchanged (50 of 114) — verified from
  the artifact, as this plan required, rather than assumed.
- **Browser (1510×927, image rebuilt from this checkout, `spago-app-1` healthy)**:
  a live LLM target summary produced 3 stored `source` citations (`ai_analyses`
  row `f1df060f-…`, `target-investigation-v6`); the panel renders them; clicking the
  chembl chip focuses `#coverage-source-chembl` for 2.4 s (class + computed outline
  recorded); a `measurement` citation in the same panel still switches to the
  Evidence tab. The coverage chips carry their ids, and the served bundle contains
  `coverage-chip-focused`, so the check ran against current code rather than a
  cached page.
- Cost of the browser check, stated plainly: it wrote one `ai_analyses` cache row
  and one `llm_usage` row (13,922 tokens) — product behaviour, unlike the runner.

**Not done, stated rather than implied:** the sparse/failed-source target case
(`DEMO-TARGET-1` was not exercised), any second provider, a sealed non-demo
evaluation family, and a citation chip for per-source facts in the *family*
snapshot (the family and document scopes have no per-source blocks, so nothing was
added there).

### 7.2 Files touched and commands run (this round)

Code — backend: `services/core/spago_core/services/ai.py` (`allowed_refs` collects
`sources`/`coverage` refs; `_build_citations` maps a `source` kind with
`source_name` + retrieval label; `TARGET_PROMPT_VERSION` → `target-investigation-v6`
with the reason recorded above the constants);
`services/core/spago_core/adapters/llm.py` (target system prompt states the
per-source ref rule); `services/core/tests/test_online01_scoped_summaries.py` (new
`test_every_retrieval_is_citable_by_its_own_ref`, root-ref test docstring corrected
because target aggregates now *do* have refs).
Code — frontend: `apps/web/src/components/TargetHeader.tsx` (exported
`coverageChipId`, chip `id`, `focusedSource` prop),
`apps/web/src/components/TargetEvidencePanel.tsx` (`onFocusSource`, `openCitation`),
`apps/web/src/App.tsx` (`focusedSource` state, `focusSourceChip`, prop wiring),
`apps/web/src/api/types.ts` (`CitationRef.kind` union + `source_name`),
`apps/web/src/styles.css` (`.coverage-chip-focused`).
Docs: `benchmarks/online01-llm-eval-2026-09-15.md`, `benchmarks/README.md`,
`docs/online-capability.md`, `docs/archive/2026-09-15-online-llm.md` §4.5,
`PROMPT.md` handoff, this file.

Commands, with results:

| Command | Result |
| --- | --- |
| `.venv/bin/python -m pytest --junitxml=…` in `services/core` | **418 passed, 0 failed, 0 errors, 0 skipped** (61.8 s) |
| `npm run build` in `apps/web` | clean (`tsc -b` + `vite build`, 602 ms) |
| `.venv/bin/python scripts/llm_summary_eval.py --dry-run --target-key TSLP` | target 30,411 B / 55 refs, no provider call |
| `.venv/bin/python … --yes --samples 6 --target-key TSLP --publication-number DEMO-PATENT-A` | run 4, 18/18 answered, 132,574 tokens, artifact written |
| `docker compose up -d --build` | image rebuilt, `spago-app-1` healthy, `/healthz` ok |
| Browser at 1510×927 against `127.0.0.1:8000` | chip ids present; live target summary with 3 `source` citations; flash 50 ms → 2,407 ms; `measurement` citation still switches tab |
| `git diff --check` | clean |
| `docker compose exec db psql …` | `ai_analyses` row `f1df060f-…` (`target-investigation-v6`, 18 citations, 3 `source`); `llm_usage` 13 → 14 rows (app call only) |

Working tree remains uncommitted, per the owner's instruction; nothing was staged,
committed or pushed.


