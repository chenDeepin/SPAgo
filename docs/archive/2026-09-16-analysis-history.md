# B-10 — Summary archive and retrieval (delivered 2026-09-16)

> Archived 2026-09-17 — round closed. Delivered record and open remainder: [backlog register](../plans/backlog.md) §1–§2.

Backlog item: `docs/plans/backlog.md` B-10, the top P1 item after B-01. Vision check
before starting and before closing: it serves `PROMPT.md` §2 (the analyst loop ends in
"AI-assisted interpretation → saved project") and §1's provenance rule — an analysis a
scientist paid for must be findable, and it must stay visibly an inference. What a user
can do afterwards that they could not do before: read back any summary they generated,
see what it cost and what it was based on, and take it out as a file that still says so
— without paying the provider twice.

## 1. What was built

| Piece | Where | Why this shape |
| --- | --- | --- |
| Read path over `ai_analyses` | `spago_core/services/analyses.py` | One module owns the owner predicate, the scope labels, the staleness reasons and the export rendering, so the list, the detail and the file cannot disagree. |
| List | `GET /api/v1/analyses` | Owner-scoped, newest first, filter by scope, label search, bounded page (default 50, cap 200). Cheap staleness only: entity gone, prompt version changed, policy version changed, dataset version moved. |
| Detail | `GET /api/v1/analyses/{id}` | Stored text + citations + **the exact check**: the stored input snapshot's fingerprint is compared with a freshly recomputed one, using the same pure function the write path uses. No model call. |
| Export | `GET /api/v1/analyses/{id}/export` | Markdown whose header carries scope, provider, model, mode, provenance sentence, prompt version, data version (then and now), billed tokens, citation count and the staleness verdict. `X-Spago-Analysis-Stale` lets a caller check without parsing. |
| History surface | top-bar **Analyses** → `AnalysesDialog.tsx` | The AI panel is scope-bound and only visible with something selected, so a history needed its own on-demand surface. It reuses the existing `Modal` contract and the existing search for "Open scope" — no new routing. |

## 2. Verification (commands and observed results)

```
cd services/core && .venv/bin/python -m pytest tests/test_analysis_history.py
# → 16 passed
cd services/core && .venv/bin/python -m pytest        # whole suite
# → 547 passed  (was 531 before this item)
cd apps/web && npx tsc -p tsconfig.app.json --noEmit  # clean
```

The module's own tests pin the contract, not the implementation: a generated summary
appears with its label and no staleness; the list is newest-first; the scope filter and
label search work and a literal `%` is not a wildcard; an unknown scope is 422; a page
request is clamped; reading one back needs no provider; an unknown id is 404; **the
exact check flips to `false` when a measurement is added inside the family's scope**;
a deleted target leaves the text readable, the scope named as gone and no navigation
offered; a dataset change is reported for patent scopes; the export states what it is
and quotes the *stored* text rather than regenerating; a stale entry says so in the body
and in the header; another owner's analysis is neither listed, opened nor exported.

Live checks against the local stack (rebuilt from this checkout, `spago-app-1`,
`127.0.0.1:8000`), on the 15 analyses accumulated by earlier sessions:

```
GET /api/v1/analyses
# total 15 · current dataset demo-fixture-v1
# newest: family DEMO-FAMILY-1 · deepseek-flash · stale=false
# older : "Generated with prompt family-summary-v5; the current build uses family-summary-v6." (and v4, v3, v2)
GET /api/v1/analyses/<id>
# exact_check {'same_inputs': True, 'note': "The scope's inputs are unchanged …"}
# total_tokens 4691  usage keys [total_tokens, prompt_tokens, completion_tokens]
GET /api/v1/analyses/<id>/export      # 74 lines
# content-disposition: attachment; filename="spago-family-analysis-baa7889d.md"
# x-spago-analysis-stale: false · content-type: text/markdown; charset=utf-8
```

Browser walkthrough (same stack, viewport 1440×900), driven through the real UI:

| Step | Observed |
| --- | --- |
| Top bar | `Analyses` button beside `Projects`; the dataset badge is unchanged |
| Open | dialog `My analyses`, `15 stored analyses · this deployment serves demo-fixture-v1` |
| List rows | scope noun + label, timestamp, model (`deepseek-flash` / `offline, no model`), provenance label, citation count; stale rows carry `May be out of date.` with the prompt-version reason |
| Expand newest | `Prompt family-summary-v6 · data demo-fixture-v1 · the inputs are unchanged, so this is what the same request returns now`, then the stored text and 20 citations with labels (`evidence DEMO-PATENT-B · claim`, `measurement IC50 = 22 nM (DEMO-ASSAY-1)`) |
| Export .md | button goes `Exporting…` and returns to `Export .md`; no error banner |
| Open patent family | dialog closes and the workspace navigates to `?q=DEMO-PATENT-A` (family view loads) |
| Escape | dialog closes; `document.activeElement` is the `Analyses` button |

Not exercised, and therefore not claimed: the **empty** state of the dialog (this
account owns 15 analyses; it is reachable only on an account with none) and the **error**
state (not induced). Both are code paths only. The **LLM-mode** list was exercised (the
newest entries really are DeepSeek summaries), but no *new* model call was made in this
round — that path was already covered by the hosted-acceptance rehearsal.

## 3. A defect found while building it (test isolation, not product)

The first full-suite run after adding the module produced ten failures in
`test_export_scope.py` and `test_integration_pg.py` — all 401s. Cause: `Settings` is
cached process-wide, and this module's ownership test flips `SPAGO_AUTH_MODE=required`
via `monkeypatch`; `monkeypatch` restores the environment but the cached `Settings`
object survived into the next module. `test_online03_auth.py` already carried an autouse
`get_settings.cache_clear()` fixture for exactly this reason; this module now carries
one too, with the comment naming the failure it prevents. Re-run of the three modules
together: 61 passed. Full suite: 547 passed.

## 4. Deliberate scope decisions

- **Cheap staleness in the list, exact staleness on open.** Recomputing 50 snapshots for
  one page would make the list as expensive as 50 generations. The list therefore names
  only what it can prove from the row and the deployment's constants; opening one
  analysis does the real work. The UI and the export both state which of the two they are
  reporting, so "no stale reason" is never read as "verified current".
- **The exact check compares snapshots, not the full cache key.** The write path's key
  also includes provider, model and request shape. Comparing the snapshot alone answers
  the data question ("have the inputs moved?") without claiming a cache hit the write
  path might not produce — e.g. after switching from offline to LLM mode.
- **No delete, no rename, no "pin".** The backlog asked for retrieval; deletion is a
  different workflow (and a destructive one) with no reviewed ask. B-29 records the
  related idea (attach an analysis to a project) as LATER rather than building it here.
- **Scope reopening reuses the search box.** It submits the family's publication number
  or the target key through the existing `handleSearch`, so there is exactly one
  navigation mechanism and no second route to keep in sync.

## 5. Files changed

- `services/core/spago_core/services/analyses.py` (new)
- `services/core/spago_core/api/routes.py` (`AnalysisEntry`, `AnalysisListResponse`,
  `AnalysisDetailResponse`, the three GET routes)
- `services/core/tests/test_analysis_history.py` (new, 16 tests)
- `apps/web/src/components/AnalysesDialog.tsx` (new), `TopBar.tsx`, `App.tsx`,
  `api/client.ts` (`downloadGet`, analyses calls), `api/types.ts`, `styles.css`
- `docs/plans/backlog.md` (B-10 delivered, B-29 recorded, B-02 promoted to top P1),
  `docs/online-capability.md` §4, `docs/runbook.md` §H6, `README.md`

## 6. Left open

- The dialog's empty and error states are code-path only (§2).
- A stored analysis cannot yet be attached to a project (B-29, LATER) and cannot be
  deleted; neither was asked for.
- The list is not paginated in the UI (it requests 50 and shows them). At the current
  scale of one owner's history that is honest; the API has the cursor for a caller that
  needs it.
