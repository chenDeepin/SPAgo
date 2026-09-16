# B-38 — Browser regression for failures, stale responses and saved work

> Archived 2026-09-17 — B-38 delivered; the screen-reader pass from B-19 is register item **B-44**, and the hermetic resolve fixtures named below are **B-45**.

Date: 2026-09-16 · Register: `docs/plans/backlog.md` B-38 · Class NEXT · P2.

## Vision alignment

`PROMPT.md` §2.5: the workflow stays trustworthy when a request fails or the
scientist changes context. These specs pin the high-risk states so they no
longer depend on a person remembering to check; each asserts a user-visible
outcome on the shipped UI. They run in the existing Playwright runner and in
the CI full-stack job (B-35 wired `npm run test:e2e` into every push).

## Delivered (subagent round, coordinator-reviewed; final suite verified by the coordinator)

| Spec | Scenario | Injection (labelled in the spec) |
| --- | --- | --- |
| `stale-response.spec.ts` (2) | a slow family response cannot overwrite a fast switch to the target scope; a slow evidence fetch for compound A cannot replace the selected compound B (mechanism-agnostic: the app may abort or ignore the late response — the user-visible contract is pinned) | 20 s delayed route with the real body |
| `unavailable-source.spec.ts` (2) | a failed **candidates** fetch renders an error with Retry, the "no candidates" banner and table stay absent, recovery works; a failed **coverage** fetch states the failure — never the false "No retrieval has been run" (the defect B-38's round found, fixed and pinned in the same round) | one route aborted, then unblocked |
| `source-retry.spec.ts` | the "Retry pubchem" control asks exactly `["pubchem"]`, the run note names the sources not asked, the other chips' stored outcomes are unchanged, the retried chip takes the new outcome | discover POST answered from a fixture built from the live coverage rows |
| `save-reopen.spec.ts` | the local auth shape is asserted (mode disabled); select → new project → full reload → reopen restores the family, the item count and the selection | none (one uniquely named project per run) |
| `export-contents.spec.ts` | with a 5 µM threshold override and the evidence-class filter, the CSV's data-row count equals the menu's claimed count and every row states `reference_threshold_nM == 5000` under `potency-gate-v1` (quote-aware parsing) | none |

Row locators are scoped by checkbox labels, so the specs work on both the
pre- and post-B-19 table structures; virtualized rows use force-click with
asserted outcomes.

## The defect the round found (fixed before commit)

Blocking `GET /targets/{id}/coverage` rendered **"No retrieval has been run for
this target yet."** — an authoritative-sounding false statement with no error
and no retry (`App.tsx` passed `coverageQuery.data ?? []` and never surfaced
the error; `TargetHeader` rendered the never-run text for an empty list).
Direct violation of AGENTS.md §22, and the exact distinction the candidates
route already got right. Fixed: `TargetHeader` takes `coverageError` /
`onRetryCoverage`, the strip renders the failure with a retry (and suppresses
the never-run text and the chips while failed), and a new spec variant pins
the failure state and the recovery. Evidence: the subagent's screenshot of the
defect (`/tmp/b38-coverage-error-evidence.png`, described in its report); the
fix verified by the committed spec on the rebuilt stack (`50caf8f-dirty`).

## Verification

`npx playwright test` — **8 passed** (smoke + 7; the coverage variant included),
coordinator run on the rebuilt stack, viewport 1280×720 default / 1600×1000 for
target-view specs, stored data only.

**CI shape (found the hard way, run 35125516718):** the first push failed the
full-stack job because `export-contents` and `source-retry` read *stored*
investigation rows, which the freshly seeded demo stack does not hold (its only
target has zero candidates). Both specs now skip loudly on a bare stack
("no stored IL6 investigation on this stack") instead of failing on absent
data — manufacturing the rows would mean live source calls, which a browser
spec must not make. On any workstation with a stored investigation (the beta
shape) they run. Recorded with it: the IL6-URL specs' *resolve* step reaches
the live UniProt endpoint even on a fresh stack — free, but an external
dependency; hermetic resolve fixtures are a later polish.

## What the specs do not prove

Live-source behaviour (the discover POST is fixture-answered: no real
PubChem/ChEMBL/BindingDB round-trip, retraction or partial-refresh semantics),
hosted mode (auth is exercised only in the local single-user shape), and
anything about B-31's gate. A screen-reader pass remains open from B-19.
