# Documentation consolidation + leak surface — 2026-09-16

Status: **done** (2026-09-16; execution record in §4).

Scope: `AGENTS.md`, `README.md`, `PROMPT.md`, `docs/`, `.gitignore`. No product code,
no schema, no API change. This round is a documentation/hygiene round, so §36's
browser requirement does not apply; the checks are reference, scope and consistency
checks against the current files (plus the mechanical link verification in §3).

## 1. Facts checked before planning (current files, not remembered state)

| Finding | Evidence |
| --- | --- |
| `AGENTS.md` is 958 lines / 27.7 KB, and much of its bulk is formatting (a fenced block per enumeration) plus rules restated in several sections | file read; 39 numbered sections |
| Section numbers are load-bearing: ~60 references across code, tests, migrations, docs (`AGENTS.md §10` in `discovery.py`, §11 in `chemistry/engine.py`, §22 in `export.py`, §23 in `THIRD_PARTY_NOTICES.md`, …) | `rg "AGENTS\.md §"` |
| `README.md` (1,010 lines) duplicates most of `PROMPT.md` (1,040 lines): product idea, differentiation, architecture, data layers, domain model, evidence model, data sources, chemistry/LLM layers, roadmap, non-goals | both files read |
| `README.md`'s "Repository Layout" describes a structure that does not exist (`packages/domain`, `backend/api`, `docs/data-model`, …) | `ls -d */` vs the README block |
| Three documents link to `docs/plans/ui-round-verification/online-beta-acceptance-2026-09-15.md`, which was **deleted from HEAD** in `61f0686` (with the screenshots) and is not in `.gitignore`'s scope any more | `find`, `git show --stat 61f0686` |
| Seven plans/records in `docs/plans/` are finished rounds; only the ONLINE direction and the BindingDB_IO port record are still active | plan headers read |
| `.gitignore` misses banal leak paths: extracted bulk packages, DB dumps, exports, PDFs/spreadsheets, `.env.*` variants, compose overrides | `.gitignore` read; `git ls-files` shows no tracked `.csv/.sdf/.pdf/.dump` |

## 2. Decisions

1. **Keep every `AGENTS.md` section number (0–38).** Only its prose is condensed: one
   home per rule, no fenced block for a plain list, no rule restated in three sections.
   The potency-gate subsection under §11, the §23 license table and the §36 definition
   of done stay intact — they are cited by code and by other documents.
2. **One home per topic.**
   | Topic | Home | Others |
   | --- | --- | --- |
   | Rules, process, DoD, scope control | `AGENTS.md` | `PROMPT.md` points |
   | Product decision, differentiation, domain/evidence model, data sources, query and UI model, milestone status | `PROMPT.md` | `README.md` points |
   | Public entry: what it is, status, quick start, real data, LLM config, license | `README.md` | — |
   | As-built architecture and data paths | `docs/architecture/overview.md` | — |
   | Supported/unsupported scope statement | `docs/online-capability.md` | — |
   | Operations | `docs/runbook.md` | — |
3. **Archive finished rounds** under `docs/archive/` (verification and open issues
   preserved, header notes linking back), and update every referring file:
   `rename-to-spago`, `apache-2-license`, `llm-interface`, `ui-review-next-round`,
   `llm-live-smoke`, `llm-eval-and-demo-open`, `product-readiness`,
   `design/imagegen-prompts` (superseded design-generation history).
   Stay active: `2026-09-15-online-llm.md` (direction + ONLINE-00…05 record) and
   `2026-09-15-bindingdb-io-port.md` (ONLINE-06/07 record; §7.4 open items are live).
4. **Restore the beta-acceptance text record as an archived document**, without the
   screenshots that were deliberately removed: three documents cite it, and its
   "not verified / required before admitting users" list plus the acceptance script is
   the live gate for the next stage. The file's own counts (397 tests) are stale and
   the restored copy says so.
5. **Harden `.gitignore`** against target-information and private-data leaks
   (investigation exports, extracted bulk packages, DB dumps, private PDFs/structure
   files, `.env.*`, compose overrides, screenshots of a running build), while keeping
   the fixture directories tracked.
6. **No content is deleted, only relocated or condensed**: anything leaving `README.md`
   or being compressed in `PROMPT.md` is already normative in `AGENTS.md` or stated in
   full in a kept section (§2's mapping is checked by grep before closing).

## 3. Verification plan

- Every `](…)` target in every tracked `*.md` resolves to an existing path (script
  check, no network).
- No reference to a moved path remains: `rg` for each old path name, excluding the
  archived files themselves.
- `git diff --check` clean; `git status` shows only intended paths.
- Section-number references still resolve: `rg -o "AGENTS\.md §[0-9]+"` compared
  against the section list, same for `PROMPT.md §`.
- No rule lost: `AGENTS.md` diff reviewed section by section against the old file.

## 4. Execution record

**Done 2026-09-16, documentation only.** No product, schema, API or frontend source
changed; the only code-adjacent edits are comments and docstrings that cite a moved
record (verified with `py_compile`).

### 4.1 Files

| Action | Path | Note |
| --- | --- | --- |
| Rewritten (958 → 381 lines) | `AGENTS.md` | Every section 0–38 and every rule kept; fenced blocks collapsed into lists, duplicated statements merged, §21 now defers to §13/§14 for the limits stated there |
| Rewritten (1,010 → 242 lines) | `README.md` | Public entry only: status, quick start, real-data and LLM configuration, how it works, **actual** repository layout, milestone states, boundaries, license. The removed product/architecture/domain/roadmap sections are stated in full in `PROMPT.md`, which the README now points to |
| Condensed (1,040 → 839 lines) | `PROMPT.md` | Handoff block rewritten with correct pointers; §4/§10/§14/§16/§17/§19/§20 condensed; §16/§17 defer to AGENTS §27–29 / §20–21; milestone list now carries per-slice state |
| Moved to `docs/archive/` | `2026-09-14-rename-to-spago.md`, `2026-09-15-apache-2-license.md`, `2026-09-14-llm-interface.md`, `2026-09-14-ui-review-next-round.md`, `2026-09-15-llm-live-smoke.md`, `2026-09-15-llm-eval-and-demo-open.md`, `2026-09-15-product-readiness.md`, `2026-09-14-imagegen-prompts.md` | Each got an archive banner with its follow-up pointer; sibling links stay valid, links to active plans became `../plans/…` |
| Restored (text only) | `docs/archive/2026-09-15-beta-acceptance.md` | Recovered from `61f0686^`, with a header explaining that the screenshots stay out of Git and that the test counts are stale |
| New | `docs/plans/2026-09-16-docs-consolidation.md` | This file |
| Hardened | `.gitignore` | See 4.3 |
| Reference fixes | `docs/architecture/overview.md` (status block + 2 links), `docs/online-capability.md`, `docs/design/2026-09-14-ui-direction.md` (3 links), `docs/plans/2026-09-15-online-llm.md` (5 links), `docs/plans/2026-09-15-bindingdb-io-port.md`, `benchmarks/online01-llm-eval-2026-09-15.md`, `benchmarks/paging-beyond-cap-2026-09-15.md`, `services/core/spago_core/config.py`, `services/core/spago_core/services/ai.py`, `services/core/tests/test_llm_adapter.py`, `services/core/tests/test_online04_usage.py` | All now point at the archived location |

Kept active in `docs/plans/`: `2026-09-15-online-llm.md` (direction + ONLINE-00…05
record) and `2026-09-15-bindingdb-io-port.md` (ONLINE-06/07 record, §6.5/§7.4 open).

### 4.2 Commands and results

| Check | Command | Result |
| --- | --- | --- |
| Full backend suite | `scripts/run_checks.sh` | **503 passed**, 3 warnings, 89 s (live PostgreSQL + RDKit scratch DB) |
| Frontend typecheck + production build | (same script) | passed; `vite build` 103 modules, 653 ms |
| Edited Python still compiles | `.venv/bin/python -m py_compile` on the four touched files | passed (comment-only edits) |
| Markdown link integrity | script over all 36 `*.md` (tracked + untracked) | all relative links resolve |
| No stale references | `rg` for every moved path name, excluding `docs/archive/` | none |
| Section numbering | `rg -o "AGENTS.md §[0-9]+"` / `PROMPT.md §[0-9]+` vs the section lists | 23 distinct AGENTS sections and 8 PROMPT sections referenced; all exist |
| Whitespace | `git diff --check` | clean |
| Rule preservation | vocabulary diff of old vs new `AGENTS.md` | 17 words dropped, all connective; §21's restated limits now defer to §13/§14 |
| Ignore rules | `git check-ignore -v` on 12 leak paths and 5 must-stay-tracked paths | leak paths ignored, fixtures/license/README/design drafts not |
| Size | `wc` | `AGENTS.md` 957 → 381 lines; `README.md` 1,010 → 242; `PROMPT.md` 1,040 → 839 |

### 4.3 `.gitignore` additions (leak surface)

New local-only paths: `/exports/`, `/dumps/`, `/logs/`, `benchmarks/tmp/`,
`data/bulk/`, `data/extracted/`; binaries `*.dump`, `*.sql.gz`, `*.sqlite*`, `*.duckdb`,
`*.db`; private material `*.pdf`, `*.sdf`, `*.mol`, `*.csv`, `*.xlsx` (with
`!data/fixtures/**` so sealed fixtures and the tracked design PNGs stay tracked);
screenshots of a running build `docs/plans/*-verification/` and `docs/verification/`,
`*.har`; environment `*.env.*` variants with `!.env.example`, and
`docker-compose.override.yml`.

### 4.4 Not checked / open

- The screenshots in `docs/plans/ui-round-verification/` stay local by design; the
  archived records describe them but do not contain them.
- No browser pass: this round changed no rendered behavior (documentation, comments and
  ignore rules only), so §36's browser requirement does not apply. The 503-test run and
  the frontend build ran before the comment-only edits; only `py_compile` was re-run
  afterwards.
- Test-suite hygiene warnings remain (3): starlette/httpx deprecation, anyio
  `BlockingPortal` alias, and a class-scoped fixture defined as an instance method in
  `tests/test_online01_scoped_summaries.py` (`PytestRemovedIn10Warning` — a real future
  breakage, not a cosmetic one).

