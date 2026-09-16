# Live LLM smoke with a real provider (DeepSeek) — 2026-09-15

> Archived 2026-09-16 (execution record, closed). Cited as evidence by
> `docs/online-capability.md` and `docs/archive/2026-09-15-online-llm.md` §4; the
> provider-compatibility findings in §9 stay binding.

Status: **execution record.** Opens PROD-07 / ONLINE-01 item "one real model
provider configured, with a live call per scope recorded". Baseline HEAD
`41ef768` plus the uncommitted ONLINE-00…05 working tree.

## 1. Scope of this turn

Configure exactly one real Chat Completions endpoint and record real model
generations through the existing service/API path. No adapter, prompt, schema or
UI change is in scope: the adapter's documented subset is
`model` + `messages` + `stream:false` + `max_tokens` → `choices[0].message.content`
with `finish_reason == "stop"`. Any unsupported-provider behaviour found here is
recorded as a finding, not silently patched.

## 2. Secret handling (AGENTS.md §35)

- The API key is written **only** to the gitignored root `.env` (`.gitignore`
  already lists `.env`). It is not committed, not written into this record, not
  placed in `README`/`PROMPT.md`/`.env.example`, and not printed by any command.
- Requests read the key from the file, so it never appears in a command line.
- If this key was shared over an unencrypted channel, rotation remains the
  operator's call; nothing in the repo depends on this specific value.

## 3. Configuration chosen

| Setting | Value | Why |
| --- | --- | --- |
| `SPAGO_LLM_BASE_URL` | `https://api.deepseek.com/v1` | Adapter appends only `/chat/completions`; the `/v1` segment is DeepSeek's documented OpenAI-compatible alias. HTTPS, so the adapter's plain-HTTP loopback restriction does not apply. |
| `SPAGO_LLM_MODEL` | `deepseek-flash` | Current model id per DeepSeek's 2026-09-10 release notes. `deepseek-chat` is a legacy alias past its announced discontinuation date and must not be depended on. |
| `SPAGO_LLM_API_KEY` | operator-provided | Sent as `Authorization: Bearer …` only to the configured endpoint. |
| quota limits | defaults (200k user / 2M deployment) | Non-zero so a misconfigured deployment cannot offer unlimited paid usage. |

Initial assumption (corrected in §5): "non-thinking mode is the default for this
model id; the adapter sends no `thinking`/`reasoning_effort` parameter." The
measurement showed the opposite — `deepseek-flash` reasons by default — so the
deployed configuration sets `SPAGO_LLM_DISABLE_THINKING=true` and
`SPAGO_LLM_JSON_MODE=true`; see §5 for the evidence and §3 of `.env.example` for
the switches themselves.

## 4. Verification steps

1. `GET /api/v1/ai/status` → expect `state=configured`, sanitized target, model id.
2. One live `POST /api/v1/families/{id}/summary` with `{"mode":"llm"}` on the
   loaded demo fixture: real generation, recorded latency, provider, model,
   provenance (`llm_inferred`), citations, token usage.
3. Repeat the identical request → expect the stored analysis to be reused
   (`cached`), i.e. no second paid call.
4. One live `POST /api/v1/documents/{id}/summary` with `{"mode":"llm"}` for the
   document scope, and one target-scope call if the loaded data supports it.
5. Confirm the offline path still works and that a wrong-key request fails with a
   mapped error rather than a fake success.

Acceptance for this turn: a real generation is observed per scope attempted, the
recorded metadata matches the response, cache reuse is demonstrated, and every
unattempted check is listed as not checked.

## 5. Decision taken before implementation (measured, not assumed)

The first live call through the API failed with `502 "Model did not finish
normally."` A read-only diagnostic reproduced the provider call with the real
family snapshot (same system/user prompt, same `max_tokens`):

| Request | `finish_reason` | `completion_tokens` | content |
| --- | --- | --- | --- |
| adapter subset, `max_tokens=1500` | `length` | 1500 (all `reasoning_tokens`) | empty |
| `thinking:{"type":"disabled"}`, 1500 | `length` | 1500 | 3805 chars, invalid JSON (cut mid-object) |
| adapter subset, `max_tokens=8192` | `stop` | 5371 | 4705 chars, valid JSON |
| `thinking:{"type":"disabled"}`, 4096 | `stop` | 1906 | 5471 chars, valid JSON |

Two independent causes:

1. **`deepseek-flash` reasons by default.** Without any parameter it spent the
   entire output budget on hidden reasoning (`completion_tokens_details.
   reasoning_tokens == max_tokens`) and returned no `content` at all, so the
   adapter's `finish_reason == "stop"` check failed closed. Thinking can only be
   turned off with the documented `thinking` request parameter; the adapter's
   minimal subset does not send it.
2. **1500 output tokens is below what the required JSON answer needs** for this
   snapshot even when thinking is off (1906 tokens for a complete answer).

Chosen change, kept as small as the evidence allows:

- `MAX_OUTPUT_TOKENS` 1500 → 4096 (the measured need is ~1.9k; the constant is
  part of the cache key, so stale entries cannot be served afterwards).
- A new **opt-in, default-off** setting `SPAGO_LLM_DISABLE_THINKING` that adds
  `thinking: {"type": "disabled"}` to the request. Default-off is deliberate:
  stricter OpenAI-compatible endpoints reject unknown parameters, and the
  existing contract test asserting the minimal request subset must keep
  meaning what it says. Content that depends on thinking therefore must be
  re-requested, so the flag is part of the cache key.

Not chosen: leaving thinking enabled and raising the budget above ~6k tokens.
It costs ~2.8× the output tokens for ~2.5× the latency, and reasoning length is
unbounded, so a larger snapshot could still exhaust the budget and fail closed.

### Second and third causes, found after the first fix

With thinking disabled and the cap raised, calls reached the model and produced
content, but two further contract gaps appeared, each measured:

1. **A cap the instructions never stated.** The schema allows at most 5
   `limitations`, and 3/3 family calls returned 6–9. Fix: state the limits in the
   instructions and derive both the prompt text and the pydantic fields from one
   pair of constants (`MAX_PARAGRAPHS`, `MAX_LIMITATIONS`), so the model can
   never be judged against a contract it was not told. A regression test asserts
   every scope states both caps.
2. **The paragraph cap sat exactly on the model's natural output length.**
   Target-scope calls returned exactly 12 paragraphs (the cap) in 6/6 samples and
   broke it once. Fix: keep the hard cap and add headroom guidance ("prefer 6-10
   short paragraphs; merge closely related facts").
3. **Malformed JSON from the model, not truncation.** 2/6 family calls ended with
   `finish_reason == "stop"`, ~1.5k of 4096 tokens used, and content ending in
   `}` — but the closing `]` of the last array was missing, so the whole summary
   was refused as invalid JSON. Fix: the opt-in, OpenAI-standard
   `response_format: {"type": "json_object"}` (`SPAGO_LLM_JSON_MODE`), which
   removed that failure class in the measured sample (0/6 invalid JSON).

All three fixes are compatibility-level: no change to what SPAgo claims, to
provenance, or to the validation rules, which keep refusing anything the model
gets wrong instead of repairing it silently. Every prompt change bumps
`PROMPT_VERSION_BY_SCOPE`, so earlier cached text can never be served against the
new instructions.

## 6. Results

Environment: app container rebuilt from the current checkout; demo fixture data
(`demo-fixture-v1`); DeepSeek `deepseek-flash` at `https://api.deepseek.com/v1`
with thinking disabled and JSON mode on; `MAX_OUTPUT_TOKENS = 4096`.

### 6.1 Live calls through the running API

| Scope | Result | Latency | Tokens (total) | Citations | Text |
| --- | --- | --- | --- | --- | --- |
| family (`DEMO-FAMILY-1`) | 200 | 6.9 s | 4669 | 19 | 2796 chars |
| document (`DEMO-PATENT-A`) | 200 | 5.0 s | 3018 | 9 | 2486 chars |
| target (TSLP) | 502 then 200 on retry | 6.2 s | 13104 | 9 | 3078 chars |

All three carried `provider=llm-openai-compatible`, `model=deepseek-flash` and
`provenance_state=llm_inferred`. The target rejection was validation, not
transport: the model cited a fact reference outside the supplied set, and the
adapter refused the answer instead of persisting it.

- `GET /api/v1/ai/status` → `state=configured`, sanitized target
  `https://api.deepseek.com/v1`, model `deepseek-flash`. No key in any response.
- Cache reuse: an identical repeat request returned in 0.04–0.08 s with
  `cached=true` and the stored usage, adding no usage event (no second paid call).
- Offline mode is untouched: 200, `offline-extractive`, `machine_extracted`, no
  usage, `model=null`.
- Document discipline: the document summary mentioned only `DEMO-PATENT-A` — no
  other document and no family-wide statement.

### 6.2 Measured reliability (provider level, shipped request shape)

13 further calls made outside the API, using the same prompt and parameters:

| Scope | Valid | Median latency |
| --- | --- | --- |
| family | 6/6 | 6.7 s |
| document | 2/3 | 4.7 s |
| target | 3/4 | 7.3 s |

**11/13 ≈ 85 % per attempt.** The two rejections were different residual classes:
the model cited `dataset_version:demo-fixture-v1` / `input_note` (snapshot field
names) as if they were refs, and one call still produced malformed JSON despite
JSON mode. Both were refused with a 502 rather than repaired, and neither
persisted anything.

### 6.3 Defects found and fixed in this turn

| # | Finding | Fix | Guard |
| --- | --- | --- | --- |
| 1 | The dev-stack image predated the checkout's `0008`-compatible seeder, so the app crash-looped on `ON CONFLICT` at startup | rebuilt the image from the current checkout (no code change) | — |
| 2 | `deepseek-flash` reasons by default: the whole output budget became `reasoning_tokens`, `content` was empty, every call failed closed | opt-in `SPAGO_LLM_DISABLE_THINKING` → `thinking:{"type":"disabled"}` | adapter + endpoint tests |
| 3 | 1500 output tokens truncated a complete answer (measured need ≈1.9k) | `MAX_OUTPUT_TOKENS` 1500 → 4096, still part of the cache key | — |
| 4 | The instructions never stated the schema caps; 3/3 family calls exceeded 5 limitations and were rejected | caps derived from `MAX_PARAGRAPHS` / `MAX_LIMITATIONS` and stated in every scope's instructions, with headroom guidance; prompt versions bumped | prompt-contract test |
| 5 | The model sometimes dropped the closing `]`, producing malformed JSON (`finish_reason=stop`, ~1.5k/4096 tokens used) | opt-in `SPAGO_LLM_JSON_MODE` → `response_format:{"type":"json_object"}` | adapter test |
| 6 | Validation ran outside the guarded region, so a rejected answer left its usage row at `outcome='reserved'` forever — and `used_tokens` falls back to `reserved_tokens`, so it kept consuming quota (3 live rows observed) | validation moved inside the guarded region; rejection settles as `invalid_output` | usage regression test |
| 7 | `/api/v1/usage` reported `failures: 0` while calls were being refused, because `invalid_output` was excluded from the count | `invalid_output` counted as a failure; the event log still distinguishes it | same test |

Items 2–5 are compatibility-level; nothing changed in what SPAgo claims, in
provenance, or in validation, which still refuses anything the model gets wrong
instead of repairing it silently. Every prompt change bumped
`PROMPT_VERSION_BY_SCOPE`, so no stored analysis can be served against
instructions that no longer exist.

### 6.4 Checks run

- `pytest` (full suite, LLM env cleared): **404 passed**, up from 397; the 7 new
  tests cover the two compatibility switches, the prompt/schema single source of
  truth, and reservation settling.
- Live API calls, cache reuse, offline mode, AI status and the usage ledger, as
  above. The three legacy `reserved` rows from before fix 6 remain in the demo
  database; they reserve 6000 tokens of the monthly limit and there is no
  reconciliation tool (a hosted-operations item, not a blocker here).

### 6.5 Not checked

- ~~The browser AI panel in LLM mode~~ — checked in §10 (browser, third round).
  Until then the deployed API path was verified and the UI step was left to the
  operator (mode can only be selected explicitly).
- Live upstream 429 / auth-failure / timeout paths, and quota exhaustion against
  the real endpoint.
- Target-scope summaries against live ChEMBL/BindingDB/PubChem retrieval (this
  run used the stored demo target).
- Anything outside the LLM path: real patent sources, OCSR, Markush, Ketcher.

## 7. Findings

1. **Measured 85 % single-attempt compliance** (11/13). Residual classes: a
   snapshot field name cited as a fact ref, and one malformed JSON that JSON mode
   did not prevent. A rejected answer costs a real call and returns a 502; the
   operator retries from the AI panel.
2. **Thinking mode is a billing trap for this provider.** With thinking on, a
   family summary cost 5371 output tokens (mostly hidden reasoning, 2.5× the
   latency) and could still fail if reasoning exhausted the budget. Disabling it
   is not an optimization but a correctness requirement for this model.
3. **An unstated contract is a validation failure, not a model error.** Two of
   the four fixed defects were SPAgo judging output against rules it never told
   the model (the limitations cap) or against a budget too small for its own
   schema. Both were fixed on the SPAgo side, not by loosening validation.
4. **Reservation hygiene matters even at demo scale.** A dangling reservation
   silently consumes quota because `used_tokens` falls back to `reserved_tokens`;
   the earlier state was invisible until the live usage rows were read.
5. **Open decision (needs the owner):** whether to add one bounded retry when
   validation rejects an answer. It would raise per-attempt success to ≈97 % at
   ≈1.15× the token cost, but the LLM plan currently states zero automatic
   retries because a failed call may already have been billed. Until that is
   decided, the honest behaviour stays: refuse, do not repair, let the user
   retry.
   → **Decision (owner, 2026-09-15): add one bounded retry.** Implemented in
   §9, which also narrows the rule so the original billing concern (a timed-out
   call may already have been billed) still holds: only a *content rejection of
   a completed response* is re-sampled.

## 8. Follow-ups for the next stage

- ~~Decide the bounded-retry question in §7.5~~ — decided and implemented, §9.
- Add the two residual rejection classes to the ONLINE-01 evaluation set so a
  prompt hardening change can be judged against a measured baseline instead of a
  single run.
- Record the deployed model/prompt versions in the capability page when the
  hosted runbook is next touched.

## 9. Bounded content retry — owner decision and implementation (second round)

### 9.1 The rule: what may be retried, and what must not

An answer is re-sampled **once** only when the provider completed a response and
SPAgo rejected its content. That is the only case where the paid call is certain:
the response arrived, `finish_reason` and usage were read. A new subclass marks
it, `LLMOutputRejectedError(LLMUpstreamError)`, so the retry cannot widen by
accident:

| Failure | Class | Re-sampled? |
| --- | --- | --- |
| Empty content; `finish_reason != "stop"` (adapter) | `LLMOutputRejectedError` | yes |
| JSON/schema violation, empty paragraph, missing citation, unknown fact ref, non-stop finish (service validation) | `LLMOutputRejectedError` | yes |
| Timeout; auth failure; upstream 429; transport error; HTTP 400/5xx; body not JSON; no choices; `tool_calls`; response-size cap | `LLMUpstreamError` and siblings | **no** |

The excluded cases are the ones the original zero-retry rule existed for: a read
timeout may already have been billed, throttling must not be hammered, and an
authentication or protocol failure is not a sampling problem. `tool_calls` stays
non-retried as policy: retrying a model that asked for tools invites the same
violation (AGENTS.md §12).

The retry **re-sends the identical request**. No prompt mutation means
`prompt_version` stays truthful — the accepted answer is still the answer the
recorded instructions produced. A deterministic endpoint (temperature 0) would
simply fail again; the bound keeps that cost at one extra call.

### 9.2 Accounting and bounds

- **One reservation per user request.** The retry does not reserve a second time
  and does not re-check quota: the user asked once, and a `429` for a retry they
  did not request would misreport why their summary failed.
- **The two attempts' tokens are summed** into the single settled row, because
  both calls were billed. `attempts` is recorded in the stored analysis usage,
  so an operator can attribute the extra spend. If any attempt's usage is
  unknown, the total is left unknown on purpose — a partial sum would understate
  a real invoice — and the row keeps its reservation instead.
- **Bounds:** at most 2 provider calls per request (≈2× `llm_reserve_tokens`
  spend and 2× the 60 s per-call deadline in the worst case); the offline path,
  the cache path and the planner path are untouched.
- The planner keeps single-attempt behaviour: it is a separate producer with its
  own validation and error mapping, and its rejection rate was not measured.
  Deciding it here would be extrapolation, not evidence.

### 9.3 Scope note (one adjacent defect)

Reading the reservation path for this change showed that the in-flight gate sat
*after* `usage.reserve`, so a request refused for concurrency
(`ContentInFlightError` / `ProviderBusyError`) left a reservation consuming quota
for a call that never happened — the same defect class as finding 6, smaller in
impact. The gate moves before quota check and reservation, with a regression
test asserting no `llm_usage` row exists after such a refusal.

### 9.4 Guards to add

- Rejected first answer + valid second answer → persisted, `succeeded`,
  `attempts=2`, tokens summed.
- Both attempts rejected → exactly 2 calls, one settled `invalid_output` row
  (no dangling reservation).
- Timeout and upstream 429 → exactly 1 call.
- Concurrency refusal → no `llm_usage` row.
- Adapter classification: empty content / non-stop finish are
  `LLMOutputRejectedError`; malformed HTTP body, no choices, `tool_calls` and the
  size cap are not.

### 9.5 Results

Implemented as planned; no scope change from §9.1–9.3.

**Code.** `LLMOutputRejectedError` marks a completed-but-unusable answer (empty
content, non-stop finish, JSON/schema violation, empty paragraph, missing
citation, unknown fact ref). `_generate_accepted` re-sends the identical request
at most `MAX_LLM_ATTEMPTS = 2` times and re-raises the last rejection unchanged.
`_combine_usage` sums both attempts' tokens and records `attempts` in the stored
analysis usage; if any attempt's usage is unknown it returns None, and the usage
row keeps its reservation instead of a partial sum. `summarize` now takes the
in-flight gate before quota check and reservation, so a concurrency refusal
leaves no row (§9.3).

**Guards.** 10 new tests: 6 service-level (`TestBoundedRetry`: re-sample kept and
summed, bound of two with a settled `invalid_output` row and nothing persisted,
unknown attempt usage keeps the reservation, timeout single-attempt, upstream
429 single-attempt, concurrency refusal leaves no row) and 4 adapter-level
(`TestRetryClassification`: the re-samplable classes, the service's validation
rejections, and the protocol/transport failures —
body-not-JSON, no choices, `tool_calls`, HTTP 400/500, size cap, timeout — that
must never be re-sampled).

**Suite.** Full run after the change: **414 passed**, 0 failed, 0 skipped
(exit 0), with `tests/conftest.py` blanking the endpoint variables; the
hermeticity finding that run produced is §9.6.

**Tooling.** `scripts/mock_llm_endpoint.py` gained a `mock-reject-once` mode: the
first request answers with an unknown `fact_ref`, later requests answer normally,
so the single re-sample is observable end to end without a paid provider
(verified locally: call 1 rejected, call 2 valid, two requests).

### 9.6 One finding from running the suite

The suite was **not hermetic about the endpoint**: this shell had
`SPAGO_LLM_BASE_URL` / `_MODEL` / `_API_KEY` exported (from the live-smoke work),
and the three tests asserting the unconfigured path
(`..._without_config_is_503` in `test_m5_ai`, `test_online01`, `test_online02`)
therefore reached the real provider: each returned `200` instead of `503`, i.e.
**three unplanned paid calls per run**, and they failed. Reading `.env` is not
the cause — with a clean environment the same command reports no endpoint
(verified). Fix: `tests/conftest.py` blanks those three variables at import, so a
developer's exported endpoint can no longer turn assertions into paid calls, while
tests that need an endpoint still set their own. Verified by running the suite
with a stub endpoint exported: the stub saw **0** requests.

### 9.7 Still not checked

- ~~The browser AI panel in LLM mode~~ — checked in §10. The retry itself stays
  service-level: the panel still shows one error with its own Retry control, and
  a live rejection in the UI was not produced (§10.4).
- Live re-sample rate on a real provider with the retry in place: the measured 85 %
  comes from the pre-retry run; confirming the expected ≈97 % per request needs
  another sample and is listed as a follow-up, not claimed here.
- The planner path (deliberately single-attempt, §9.2).

## 10. Browser check of the AI panel in LLM mode (third round)

### 10.1 What was run, and how the workspace was reached

Environment: the dev stack rebuilt from the current checkout
(`docker compose up -d --build app`), demo fixture `demo-fixture-v1`, DeepSeek
`deepseek-flash` with thinking disabled and JSON mode on, page served by the app
itself at `http://127.0.0.1:8000`, browser viewport 1080 × 927 (DPR 1). The
deployed container was confirmed to carry the retry code before the run
(`ai.MAX_LLM_ATTEMPTS == 2`, `_generate_accepted` / `_combine_usage` present,
adapter raising `LLMOutputRejectedError` for empty content).

Reaching the panel needs a loaded family, and the demo fixture's identifiers are
intentionally not publication-number shaped, so typing `DEMO-PATENT-A` in the
search box is classified as free text and routed to the planner, not to the
patent lookup. The family workspace was reached through the app's own Back/Forward
restore path (`history.pushState` + `popstate` with `?q=DEMO-PATENT-A`, the same
code path browser Back uses). No data or configuration was changed to do it; the
panel then appeared under the evidence drawer's **AI** tab with scope
`Family DEMO-FAMILY-1` / `Document DEMO-PATENT-C` and mode
`Offline summary (extractive, no model)` / `LLM summary (model: deepseek-flash)`.

### 10.2 Observed

| Step | Evidence |
| --- | --- |
| LLM mode selectable | the radio is disabled until `GET /api/v1/ai/status` answers `configured`; in the live page it became enabled and read `LLM summary (model: deepseek-flash)` |
| Live generation, family scope | `POST /api/v1/families/9eee4a75…/summary` → `200`; the stored `family-summary-v5` analysis was reused and the panel chip read `LLM inferred · llm-openai-compatible · deepseek-flash · cached · family scope` with 19 citations |
| Live generation, document scope (no cache entry) | `POST /api/v1/documents/6ce98f58…/summary` (DEMO-PATENT-C) → `200` in 4.0 s; chip `LLM inferred · llm-openai-compatible · deepseek-flash · document scope` (no `cached`), 6 citations, no error; `llm_usage` settled `succeeded` with 1406 + 853 = 2259 tokens, and the stored analysis carries the same usage with no `attempts` key, i.e. the first attempt was accepted |
| In-flight state | the panel showed `Stop waiting` and the note that a request already sent may still be billed |
| Scope isolation | switching Family → Document cleared the shown summary; the `Generate summary` control returned |

### 10.3 Residual observed in the model text (evaluation case)

The cached family summary contains the phrase "The enzymatic **DELETED**
measurements". `DELETED` does not occur anywhere in the stored
`input_snapshot` (checked against the persisted JSON: no `delet` token) — the
model inserted a placeholder token of its own. It is inside an `llm_inferred`
block with citations, so no provenance rule was broken, but it is exactly the
class the ONLINE-01 evaluation set is supposed to hold: a fluent answer with a
local defect that structural validation cannot catch. Recorded as an evaluation
case, not repaired by post-processing.

### 10.4 Still not checked after this round

- A live rejection surfacing in the UI after the retry change: the panel's error
  banner with its `Retry` control was not re-exercised against the real provider
  (producing one would mean begging for a rejection, and the mock path that does
  this deterministically works below the HTTP layer, §9.5).
- The UI path for the LLM planner: the browser never sends `use_llm: true`
  (natural-language planning is a LATER item in the LLM interface plan), so the
  offline planner card is what a free-text query produces today.

### 10.5 Incidental finding: the demo hint is a dead end — **fixed**

The empty state said "This deployment serves a synthetic demo dataset — try
`DEMO-PATENT-A`", and the 404 message said "…or try the demo patent", but
`DEMO-PATENT-A` could not be opened from the search box: the client classified it
as free text, the offline planner found no deterministic step, and the resulting
plan card had nothing to run. Navigation only worked through the restore path
above.

Resolved in the demo-open round by an explicit control rather than by loosening
the identifier rule: `EmptyState` and the 404 message now render an action that
opens the sample record through the same server lookup a search uses
(`docs/archive/2026-09-15-llm-eval-and-demo-open.md` §2; browser-verified on the
landing and 404 paths, and absent for non-synthetic datasets).

### 10.6 Re-verification of the retry on the current tree

`scripts/mock_llm_endpoint.py` in `mock-reject-once` mode again: the first answer
was refused by citation validation, the re-sample was accepted, and the run
recorded `attempts=2` with both attempts' tokens summed (1873) — the same shape
as §9.5. The two rows that run created (`ai_analyses`, `llm_usage`, both
`model=mock-reject-once`) were deleted afterwards, so the demo ledger contains
only real provider usage; the mock process was stopped.

The full backend suite was re-run on this tree: **414 passed**, 0 failed,
0 skipped (exit 0). The three pre-fix `reserved` rows (06:25:58, 06:29:40,
06:41:52 UTC — 6000 tokens of the demo window) were left untouched: they are the
operator's billing record, no reconciliation tool exists, and hand-editing them
would change the reported failure counts.

