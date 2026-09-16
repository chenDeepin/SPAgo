# Round plan — hosted-acceptance rehearsal, then the backlog queue (2026-09-16)

Status: **recorded local rehearsal; original queue superseded**. Hosted operator and
independent-human criteria remain open. The planning-only review at `efb1357` did not
rerun this record; current proposals are in [backlog §1](backlog.md#1-priority-order).
The initial sequence below is historical, not an instruction to restart execution.
Owner of the recorded round: coordinating agent. Baseline commit: `e1a69a8` plus the
uncommitted documentation round of 2026-09-16 (backlog register + `AGENTS.md` rules).

Inputs: the owner's instruction of 2026-09-16 (run hosted acceptance first, then work
`docs/plans/backlog.md` in priority order, re-sort when the backlog changes, commit and
push important updates, do not pause for questions, verify every item against the
product vision); `AGENTS.md` §0 "Working mode"; `docs/online-capability.md` §6 (gate,
success criteria, script); `docs/runbook.md` §H1–§H10.

## 1. What this stage does, in order

1. **Hosted-acceptance rehearsal.** Stand up an isolated hosted-shape stack (auth
   required, private database, TLS terminated, real secrets, non-zero quotas), and run
   everything of §6 that does not require a human or a purchase: readiness, invitation
   and session flow, two-account isolation, model smoke on the configured provider,
   coverage matrix on live sources, restore rehearsal, latency/cost measurement, and the
   browser path of the acceptance script. Record per criterion: passed / failed /
   blocked-with-reason, and never call the result "hosted acceptance".
2. **Adjustments.** Fix what the rehearsal finds; re-verify in the same stack.
3. **Backlog queue.** Work `docs/plans/backlog.md` §1 in priority order — P1 items first
   (B-13, B-01, B-10, B-02), then P2 in the order shown. Before continuing after any
   change to the backlog, re-sort and record what moved.
4. **Per-item discipline.** Plan the item in this file, implement, test, check vision
   alignment (`PROMPT.md` §1/§2, `AGENTS.md` §2/§3), record the result, commit and push.

## 2. Scope boundary

- Operator-only criteria (real host/domain and TLS chain, provider contract and budget
  sign-off, an invited non-implementer, independent human cross-read) stay with the
  operator. The rehearsal records them as **blocked**, not as passed.
- No new infrastructure service, no new dependency without the §23 notices update, no
  Espacenet automation, no OCSR, no Markush, no XLSX (§5 of the backlog).
- The local `.env` model key is used for one bounded smoke (per-scope calls, quota
  limits in force); the amount is recorded in the rehearsal record.

## 3. Rehearsal environment

| Element | Choice |
| --- | --- |
| Compose project | `spago-accept` (isolated volumes/ports; the running `spago` stack is untouched) |
| App port | `127.0.0.1:8100` |
| DB port | `127.0.0.1:55432` |
| Auth | `SPAGO_AUTH_MODE=required`, invitations only |
| Seed | `SPAGO_SEED_MODE=demo` for the script walkthrough, then `none` for the readiness verdict (the note it raises with `demo` is expected and was observed) |
| Cookies | `SPAGO_COOKIE_SECURE=true`, served through a local TLS terminator |
| TLS | self-signed cert + `socat` on `127.0.0.1:8443` (rehearsal only; the real deployment terminates TLS at its own proxy) |
| Quotas | user 200,000 / deployment 2,000,000 tokens, window `month` |
| Env file | `/tmp/spago-accept.env` (outside the repo; no secret is committed) |
| Model | `deepseek-flash` at `https://api.deepseek.com/v1` (the deployment's configured provider) |

## 4. Result

Filled in after the run, below.

### 4.1 Rehearsal record

Build: `api_version 0.1.0` from `/healthz`, image built from this checkout. Corpus:
demo fixture plus the imported extraction (2,639 compound rows, all with a non-NULL
RDKit `m` value). Criterion numbers are `docs/online-capability.md` §6.

| # | Criterion | Result | Evidence |
| --- | --- | --- | --- |
| 1 | Deployment shape | **partly verified** | `SPAGO_AUTH_MODE=required`, `SPAGO_COOKIE_SECURE=true`, `SPAGO_SEED_MODE=none`, app and DB ports bound to `127.0.0.1`, TLS terminated in front of the app. The real domain, certificate chain and an off-host connection attempt belong to the operator. |
| 2 | Readiness clean | **passed** | `/api/v1/readyz` → `{"status":"ready","notes":[]}` after the seed switch; `/healthz` → `api_version 0.1.0`, database up, RDKit cartridge installed. |
| 3 | Budget bounded and known | **partly verified** | Both quotas non-zero and enforced; `/api/v1/usage` + `/usage/events` account every call (table below). §H9 still has blank operator targets, and no price is configured, so no currency cost is claimed. |
| 4 | One provider real from this host | **passed** | `deepseek-flash` live on family, document and target scopes; token usage, latency and cache behaviour recorded per call. |
| 5 | Coverage re-recorded | **passed** | `benchmarks/cohort-coverage-2026-09-16-accept.json` — five requested targets: 3 stored (TSLP, CD40LG, EGFR), 2 not stored (IL-6, IL-6R, i.e. `not_queried`, not "empty"); BindingDB returned 0 hits for CD40LG (an honest empty, with its warning text); potency threshold 10 µM recorded next to every verdict. |
| 6 | Restore rehearsed | **passed** | 1.0 MB dump restored into `spago_restore`; ownership split matched the source; chemistry intact (2,639 structures, RDKit substructure query returns rows). Two procedures were wrong as documented and are fixed in §H7 (see 4.2). |
| 7 | Isolation verified | **passed** | Two accounts, one project each: neither list nor project fetch crosses owners; a summary cached for one user is not served to the other (`cached:false` on the second user's identical request). |
| 8 | Non-implementer completes the script | **blocked** | No invited external person participated. The browser walkthrough was executed by the implementing agent against the rehearsal stack: sign-in, target discovery, candidate inspection, AI summary, citation chip → measurement, project save, CSV/SDF export. This is a rehearsal, not acceptance. |
| 9 | Chemistry read by a human | **blocked** | Requires an independent reader; not performed. |

Measured calls (`/api/v1/usage/events`, one row per paid call; seconds = reserved →
settled):

| Scope | Outcome | Model | Tokens (prompt + completion) | Seconds |
| --- | --- | --- | --- | --- |
| family | succeeded | deepseek-flash | 3,018 + 1,427 = 4,445 | 5.7 |
| document | succeeded | deepseek-flash | 1,938 + 1,072 = 3,010 | 4.1 |
| target | succeeded | deepseek-flash | 9,545 + 2,410 = 11,955 | 10.2 |
| target | succeeded | deepseek-flash | 9,545 + 2,128 = 11,673 | 9.2 |
| target | refused (before the fix) | deepseek-flash | reservation only | 20.5, 19.1 |
| family | failed (transport drill) | mock | reservation only | 0.0 |
| family | refused (refusal drill) | mock | 2 + 2 = 4 | 0.0 |

What the run does **not** prove, in the terms of §6: no scientific truth, no general
provider compatibility, no coverage completeness, no legal or druggability conclusion,
and none of the unsupported capabilities.

### 4.2 Adjustments made

Each one is reproduced by a test or by the drill named in the last column.

| # | Defect found | Change | Evidence |
| --- | --- | --- | --- |
| 1 | Target summaries were refused as `too_long` (two live calls billed and discarded, ~11k tokens each) because the answer schema capped the limitations list at 5 while a target investigation legitimately produces 6–8. | `MAX_LIMITATIONS` → 8; a refusal now names which bound broke (`limitations: 9 returned, at most 8 allowed`) instead of a bare `too_long`. | `test_llm_adapter.py` bound cases; live target summary succeeded twice afterwards |
| 2 | A refused-but-billed answer settled with its 2,000-token reservation, so repeated refusals under-reported real spend and let a caller outrun the quota. | `AIError.usage` carries the provider's measured usage; a rejected run settles with the sum of its billed attempts when every attempt reported usage, and keeps the reservation otherwise. | `test_online04_usage.py` (4 and 84 token totals); drill B settled 4 tokens for two billed refusals |
| 3 | A transport failure (`ConnectError`) was recorded with outcome `invalid_output`, which reads as "the model's answer was rejected" when the endpoint was never reached. | New `LLMTransportError` (still a 502, never re-sampled); `invalid_output` is now reserved for an answer that arrived and was refused. | drill A → `failed` + the ConnectError text; drill B → `invalid_output` |
| 4 | §H8 told the operator to reproduce the refusal drill with "a mock mode that returns invalid JSON twice" — no such mode existed. | `scripts/mock_llm_endpoint.py` gained `mock-reject-twice`; §H8 names it and notes that a containerized app needs `--host 0.0.0.0`. | drill B used exactly that mode |
| 5 | §H7's chemistry check referenced a column named `mol`; the RDKit column is `m` (type `mol`). | §H7 now runs the correct count and an RDKit substructure query, both executed against the restored database. | restore rehearsal |

### 4.3 Backlog queue results

For each item: what was built, what verified it, and where the artifact lives. The
product-vision check is the same for every item (does it strengthen
`patents → families → structures → examples → activity → evidence → interpretation`
rather than add a toolbox entry?) and is stated once here.

**B-13 — Gate support kit (P1).** Built: `scripts/restore_check.sh`, a scripted §H7
rehearsal that reads the live deployment's role/database, records source counts before
dumping, restores into a scratch database, compares the documented counts plus the
per-user split, runs an RDKit substructure query in the restored database, and exits
non-zero on mismatch. Documented: the §H2 "what the app does not do" table (TLS,
compression with the measured editor figure, request throttling, log retention, backup
schedule), and §H7 now names the script while keeping the manual commands for
non-compose hosts. Verified: two clean runs against the rehearsal stack (3 users,
3 projects, 8 analyses, 2,639 structures, 2,593 benzene-containing rows) and a
deliberate-mismatch run that reported the exact drifted metrics and exited 1. Vision
check: it removes hand-error from the one checklist entry that is mechanical, and it
makes the ingress gaps (compression, throttling) an operator decision that is written
down instead of assumed — it adds no user-facing surface.
