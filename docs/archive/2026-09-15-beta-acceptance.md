# Invited-beta acceptance record — 2026-09-15

> Archived 2026-09-16. The original file lived in `docs/plans/ui-round-verification/`
> and was deleted from HEAD in `61f0686` together with the screenshots of that round
> (those stay out of Git: a screenshot of a running build shows a live target's rows).
> The text is restored here because `PROMPT.md`, `README.md` and
> `docs/plans/2026-09-15-online-llm.md` cite it as the verified/open register, and its
> §5 is the script the next stage runs. **The counts below are as of 2026-09-15 and are
> stale** (the suite has since grown past 500 tests); the ONLINEd records in
> `docs/plans/2026-09-15-online-llm.md` §4 and
> `docs/plans/2026-09-15-bindingdb-io-port.md` are the current verification state.
> §4 "Not verified" remains the live gate.

Status: **implementation complete; hosted acceptance NOT yet performed.** This
file records what was actually verified, what was not, and exactly what remains
before invited users are admitted. Nothing below is inferred from a passing test.

## 1. What was verified, and how

| # | Item | Method | Result |
| --- | --- | --- | --- |
| 1 | Full backend suite | `pytest` against a live PostgreSQL + RDKit scratch database | **397 passed** |
| 2 | Frontend typecheck + production build | `tsc -p tsconfig.app.json --noEmit` and `vite build` from the current checkout | passed |
| 3 | Target investigation end to end | Browser, server built from this checkout: resolve TSLP → live retrieval from ChEMBL/BindingDB/PubChem → candidate table → assay evidence panel → save → reopen from Projects | passed (screenshots/state captured in the session record) |
| 4 | Plan interpretation and execution | Browser: free-text request → plan card with editable parameters → explicit Run → target investigation | passed |
| 5 | Candidate without a patent mapping | Browser: select / save / reopen, export menu present | passed |
| 6 | Invitation-only hosted mode | Browser + `curl`: anonymous workspace request 401; invitation link pre-fills and redeems; signed-in save works through the CSRF header; sign-out returns to the gate | passed |
| 7 | Live source coverage for the acceptance targets | Real retrieval, recorded in `benchmarks/online00-coverage-2026-09-15.{md,json}` | recorded (see §3) |
| 8 | Performance baseline | `benchmarks/run_benchmarks.py` against the running server, 50/20/10 samples per case, 0 errors | recorded in `benchmarks/online-baseline-2026-09-15.md` |
| 9 | Backup/restore with ownership | Real `pg_dump` → `pg_restore` into a fresh database, ownership counts compared | passed, with two operational findings recorded in runbook §H7 |
| 10 | Scientific invariant evaluation | `tests/test_online05_evaluation.py` (modality, evidence classes, summary claims, citation scope) | passed |
| 11 | Cross-user isolation | `tests/test_online03_auth.py`, direct API calls with guessed UUIDs, two accounts | passed (19 tests) |

## 2. Defects found by this work, and their status

| Defect | Found by | Status |
| --- | --- | --- |
| The reviewed scope catalog did not ship inside the installed package, so related-partner expansion silently disappeared in the container while working from a source checkout | Deployed-artifact browser check | **fixed** (`package-data` + a degraded-but-honest failure mode); regression is covered by the container build check |
| Externally discovered compounds were stored with `has_stereo = false` regardless of structure, so a peptide with specified stereocentres was reported as having none | ONLINE-05 scientific evaluation (re-deriving the flag from the stored structure) | **fixed** (full `NormalizedStructure` is persisted); regression test added |
| Plan-step totals (`scaffold_total`, `candidate_total`) were dropped from the model input, so a bounded list could be summarised as if complete | Writing the document/target summarisers | **fixed** (totals stay in the snapshot; omission counters report the difference) |
| Evidence-class counts in a target summary described only the bounded sample, not all measurements | Manual review of a real target summary | **fixed** (counts computed in SQL over every measurement; the listed subset is stated) |
| One activity reachable through both a single-protein and an interaction target kept the *stronger* evidence class | Writing the ONLINE-00 tests | **fixed** (the weakest claim wins; documented) |
| Duplicate measurements from the same paper were flagged by document alone, marking unrelated compounds as duplicates | Reading a real TSLP result set | **fixed** (keyed on document + compound + endpoint + value) |

## 3. Live coverage reality (do not overstate)

Recorded 2026-09-15 against the live sources; details in
`benchmarks/online00-coverage-2026-09-15.json`.

| Target | Small-molecule candidates | Honest reading |
| --- | --- | --- |
| human TSLP (Q969D9) | 1 | 110 of 111 qualifying ChEMBL activities are peptides. Essentially no small-molecule coverage in these sources. |
| human CD40LG (P29965) | 10 | Only appears when the CD40L–CD40 interaction target is queried; labelled `interaction_disruption`. BindingDB returned zero hits. |
| human IL-6 (P05231) | 144 | The only acceptance target with substantial small-molecule activity data. |
| human IL-6R (P08887) | 1 | BindingDB did not answer at all (recorded `failed`, not empty). |
| human EGFR (P00533, positive control) | 2531 | Proves the adapters return qualifying small molecules, so a thin acceptance target is a coverage fact, not a broken pipeline. |

## 4. Not verified — required before admitting users

- [ ] **A real model provider — smoke recorded 2026-09-15, acceptance still
      partial.** One endpoint (DeepSeek `deepseek-flash`) was reached for family,
      document and target scopes through the running API and through the browser
      AI panel: latency, token usage, cache reuse and the failure classes are
      recorded in
      [the live-smoke record](2026-09-15-llm-live-smoke.md), where 85 %
      single-attempt compliance over 13 typed calls is the measured baseline and
      one bounded content re-sample is now in place. This is one provider, not a
      compatibility claim, and the entailment evaluation below stays open.
- [ ] **Hosted deployment.** No TLS ingress, no chosen host, no secret injection,
      no restore rehearsal against the real host. ONLINE-04's acceptance is open.
- [ ] **A user who did not implement the application.** Usability acceptance
      requires a real scientist; no external participant has used this build.
- [ ] **Independent scientific cross-reading** of retrieved structures,
      stereochemistry and occurrence fields against the original sources by a
      second person. The automated invariants are not a substitute.
- [ ] **Scientific evaluation against a live model's summaries** (does a cited
      summary statement follow from the cited record?). Manual evaluation is
      required because a valid citation does not prove entailment.
- [ ] **Multi-worker behaviour** (unsupported by design; single worker only).
- [ ] **Latency/cost targets** for the chosen host and model, defined and then
      measured for go/no-go.

## 5. Acceptance script for the invited-beta run

A scientist using only the browser must be able to complete, in one sitting:

1. Open the invitation link, sign in.
2. Resolve a requested target (TSLP, CD40L, IL-6, IL-6R, or another) and read
   the scope: what was resolved, what was excluded, which partners are related.
3. Run a supported natural-language request (review the plan, then Run) **or**
   use manual search/structure search.
4. Read the per-source coverage and distinguish small-molecule from
   peptide/biologic evidence, and direct binding from functional/interaction
   evidence.
5. Inspect a candidate's structures and assay evidence, and the patent linkage
   status (including a candidate that has none).
6. Generate a scoped, cited summary and check at least one citation against the
   underlying record.
7. Save the selection, sign out, sign in again, reopen the project, and export.
8. Report any defect before the beta is called usable.

Record the outcome in this file, per step, with the build identity from
`/healthz` and the coverage matrix for the run.
