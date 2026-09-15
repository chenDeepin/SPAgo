# Round plan — backlog round: recorded measurements, cohort coverage, deferred capability (2026-09-16)

> Archived 2026-09-16 (A1–A4, B1, B2 closed with records; §5 is the result set).
> Nothing in it stayed open except operator decisions, which stay with
> `docs/online-capability.md` §6 and `docs/runbook.md` §H9.

Status (at the time of writing): **active**. Owner: coordinating agent. Baseline
commit: `194e953` (defect round).

Inputs: the user's request (deliver the remaining backlog in priority order and pass
acceptance tests), `PROMPT.md` (handoff block, §14 milestone states, §19), the defect
round's §4 backlog, `docs/online-capability.md` §5/§6/§8, and the open items in
`docs/plans/2026-09-15-bindingdb-io-port.md` §6.5 and §7.4.

## 1. What the backlog actually contains

The gate in `docs/online-capability.md` §6 is the only thing standing between this
build and an invited beta, and **ten of its twelve checklist items are operator
decisions** — host, TLS, secret injection, `SPAGO_AUTH_MODE`, seed mode, model
endpoint and budget, cohort list, invited user, independent cross-reading, latency
and cost targets. They cannot be closed by writing code, and pretending otherwise
would be the same mistake the previous rounds recorded.

What *can* be closed here is the engineering half of the same gate plus the
capability items that were deferred with a named blocker:

| # | Item | Obligation it closes | Deliverable |
| --- | --- | --- | --- |
| A1 | Measure the ChEMBL projection saving | bindingdb §6.5: the `only=` narrowing "was not done and no saving is claimed"; AGENTS §20 forbids an unmeasured optimization | live measurement with and without the projection, recorded in `benchmarks/`, plus a request-capturing test that pins the field list |
| A2 | Cohort coverage matrix command | capability §6: "coverage matrix re-recorded for the acceptance targets on the deployed build"; ONLINE-06 next input | `scripts/cohort_coverage.py` — resolve/investigate a target list through the shipped services and emit the matrix (md + json) |
| A3 | Sparse / no-retrieval scope recorded | PROMPT handoff §4: the eval record "explicitly cannot" speak for a sparse target; capability §5: "a thin set is never rendered as a negative result" | recorded eval run against a target with **no** retrievals, and a fix if the summary overstates |
| A4 | Latency and cost budget worksheet | capability §6 last bullet ("defined, then measured") | a worksheet with the measured components and the formula the operator fills in for their host and model |
| B1 | Ketcher editor embedding | M2 deviation (`ketcher-react` 2.28/3.14 crash in the Vite production build), listed NEXT in the milestone table | a bounded attempt at a current version; embed, or record the exact failure and keep the deferral |
| B2 | Chrome MV3 load verification | M4: "Chrome-in-Chrome verification still open" | load the unpacked extension in a real browser and verify detect → handoff, or record it as blocked with the reason |

**Explicitly not in this round** (deferred by rule, not by omission): PDF OCSR
(AGENTS §30 — a coverage gap must be measured first and is not), full Markush search
(§31), and every REJECT-class item in `PROMPT.md` §19. Stating them here is the
point: they are decisions, not a queue.

## 2. Order and why

1. **A1** — cheapest, closes a recorded "not measured" obligation, and the number
   feeds A4.
2. **A3** — the correctness question comes before the reporting work: if an empty
   scope produces a summary that reads like a negative result, that is a defect,
   and A2 would otherwise publish the wrong thing in a matrix.
3. **A2** — the operator's coverage instrument; uses the numbers from A1/A3.
4. **A4** — the budget worksheet, built on A2's and A3's measurements.
5. **B1 / B2** — deferred capability, each time-boxed: a bounded attempt plus an
   honest record beats an open-ended one.

## 3. Acceptance per item

- A1: a recorded byte/latency delta against the live ChEMBL API, and a test that
  fails if the projection is dropped from the request.
- A2: the tool runs against the stored investigations and the deployed build;
  its output is reproducible and labelled with what it is not.
- A3: a recorded run; the empty-scope path either states its own emptiness or is
  fixed to.
- A4: the worksheet reproduces its own numbers from the recorded artifacts.
- B1: `tsc` + `vite build` clean, and the editor either works in the browser or
  the deferral stays with a named error.
- B2: an observed extension load, or a recorded blocker.

## 4. Verification

| Check | Command | Result |
| --- | --- | --- |
| Backend suite (whole tree, live PG + RDKit) | `cd services/core && .venv/bin/python -m pytest -o addopts="" -q` | **517 passed**, 0 failed, 0 skipped, 118 s (the round before this one recorded 503, so the new tests are counted) |
| Frontend typecheck + build | `cd apps/web && npx tsc -b && npm run build` | clean; the same asset hashes as the measured build (`index-DnRNlgaF.js`, `StructureSearchDialog-DPt54ybX.js`) |
| Companion extension | `node apps/chrome-extension/check.js` · `node apps/chrome-extension/verify-in-chrome.js` | all checks passed · real-browser load + detection + handoff + panel render verified |
| Text | `git diff --check` | clean |

Browser: any item that claims a user-visible behaviour is checked in the served
build, with the viewport and build identity recorded. Screenshots are local
(`docs/plans/ui-round-verification/`, gitignored).

## 5. Results

Each item below is closed by an artifact, not by an assertion. Nothing in this round
touched production code except the two recorded fixes (D9 was already fixed in the
defect round; B1's change subscription was fixed and re-verified here).

### A1 — ChEMBL projection measured (closed)

`benchmarks/online00-chembl-projection-2026-09-16.md` (raw JSON alongside it), produced
by `services/core/benchmarks/chembl_projection.py` against live EBI, two targets
(TSLP single page, EGFR multi-page), interleaved full/projected requests, 2 repeats.

- Transfer: **−41.2 % / −43.0 %** bytes per page, identical record counts.
- Latency: **no improvement**; the projected variant was equal (TSLP, +31 ms) or
  slower (EGFR, +950 ms, consistent across repeats).
- Consequence applied: the "dominant upstream cost" claim in
  `docs/plans/2026-09-15-bindingdb-io-port.md` §6.5 was corrected — the projection
  cuts bandwidth, not wait time; the page count (`max_activities`) is the latency
  lever. The projection is kept and pinned by a request-capturing test.

### A3 — the sparse (no-retrieval) scope (closed, with a fix)

`benchmarks/online01-llm-eval-2026-09-16-sparse.md`, produced by
`scripts/llm_summary_eval.py` against a target with zero retrievals
(`DEMO-TARGET-1`), live provider.

- Before the fix: **0 of 2 answered, 4 refusals** — the model cited
  `reference:<id>` because the shipped prompt instructs it to, and the validator's
  allowed set never contained that ref. The defect was **not** sparse-specific: any
  target summary whose model followed its potency instruction was refused.
- Fix (D9, `spago_core/services/ai.py`): `allowed_refs` now walks the snapshot
  generically; `_build_citations` maps the `reference` node to a clickable citation
  that focuses the verdict strip. UI: `CitationRef` gains the `reference` kind.
- After the fix: **2 of 2 answered, 0 refusals**, 4,347 tokens, median call 3,632 ms,
  and the text states the scope is empty instead of implying a negative result.
  Regression test: `test_the_potency_verdict_ref_is_citable_and_reaches_the_reader`.

### A2 — cohort coverage matrix (closed)

`scripts/cohort_coverage.py` + `benchmarks/cohort-coverage-2026-09-16.md` (raw JSON
alongside). Five acceptance targets, two of them investigated live through the shipped
service layer.

- Three corrections applied to `docs/online-capability.md` §5/§6: CD40LG is **not**
  thin (10 in-scope compounds, 6 at or below 10 µM → qualifies); IL-6R stays thin and
  its BindingDB row is a **source failure**, not an absence of measurements; IL-6 and
  IL-6R need the accession because the gene symbols resolve ambiguously, and the
  acceptance script now says to record which entry was selected.
- The tool reads through the shipped paths (`coverage_matrix`, `reference_verdicts`),
  labels the API version it ran against, and states what it is not.

### A4 — latency and cost worksheet (closed)

`docs/runbook.md` §H9 (renumbered from H10; the "explicit limits" section is now
§H10, and the `§H1–H9` pointers in `PROMPT.md`, `.env.example` and
`docker-compose.yml` were updated with it). It carries the measured components with
their sources, the investigation wall-time formula, the shipped cost formula
(`tokens / 1e6 × price`, `services/core/spago_core/services/usage.py`), and a
fill-in table for the operator's host and provider. The capability gate's last bullet
now points at it. No targets are invented: the operator's numbers are the deliverable.

### B1 — Ketcher editor embedded (closed)

Embedded in the structure-search dialog at 3.18.0 with all three Ketcher packages
pinned. Three packaging failures were found and fixed, each recorded at the code site:
`require("raphael")` in an ESM bundle (`ketcher-require-shim.ts`), a bare `global`
during editor init (`vite.config.ts` `define`), and a `changeEvent` subscription that
3.18 exposes differently from the 2.x API the first draft used — the last one was a
**silent no-op**, so a drawing never reached the SMILES box until it was fixed and
re-verified in the browser.

- `tsc` and `vite build` clean; keyboard-free browser check: editor mounts, drawing
  updates the box, no error banner.
- Cost measured, not estimated: `benchmarks/online08-structure-editor-2026-09-16.md`
  (20.3 MB raw / 4.95 MB gzip on first open; 0.83–0.86 s to a usable editor on
  loopback; the container serves assets uncompressed).
- Documentation updated where it claimed a deferral: `README.md` milestone table,
  `PROMPT.md` §14 M1/M2, `docs/architecture/overview.md` boundaries,
  `docs/online-capability.md` §5, `THIRD_PARTY_NOTICES.md` (Apache-2.0, pinning rule).

### B2 — Chrome MV3 load verified (closed)

`apps/chrome-extension/verify-in-chrome.js` — a real browser check, no stubs: the
unpacked extension is loaded, a page under the content-script match pattern is opened
(a local HTTPS server mapped onto `patents.google.com`, so no third-party site is
contacted), and the assertions are read back from the extension's own state:

```
service worker: chrome-extension://mgpkfnecgdkfblinblhicoignbnannme/background.js
storage.session.spagoPublicationNumber=US10102057B2
page: https://patents.google.com/patent/US10102057B2/en
side panel: "Detected: US10102057B2"
companion browser check: load, service worker, detection, handoff and panel render verified.
```

Two environment facts were found on the way and are recorded in the script and docs:
branded **Google Chrome 142 refuses `--load-extension`** ("not allowed in Google
Chrome"), so the check targets an unbranded Chromium / Chrome for Testing build
(the Playwright cache is searched automatically, `CHROME=` overrides); and the
service-worker target can appear before the content script has run, so the check polls
the stored value rather than the storage API. **Not covered:** the toolbar click,
`openPanelOnActionClick` and the side-panel *surface* — they need a headed browser and
a user gesture, and no claim is made about them.

### Round verification

Numbers are in §4: **517 passed** on the backend, `tsc` + `vite build` clean with the
measured asset hashes reproduced, extension checks passing, `git diff --check` clean.
Browser: B1 was checked in the served app and B2 in an unbranded Chrome for Testing,
each with its build identity recorded in the item's record; screenshots stay local
(gitignored, `docs/plans/ui-round-verification/`).
