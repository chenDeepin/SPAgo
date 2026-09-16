# B-01 — Corpus scale-up workflow (delivered 2026-09-16)

Backlog item: `docs/plans/backlog.md` B-01 (top P1 after the hosted-acceptance
rehearsal). Vision check before starting, and again before closing: this serves
`PROMPT.md` §1 (`patents → families → structures → …` over *real* sources) and §2
("search" must mean a corpus the deployment actually holds). What a user can do
afterwards that they could not do before: load a list of patents in one bounded run,
and see — in the product, not in a database console — exactly which dataset versions
and how many families/documents/compounds a search can reach.

## 1. What was built

| Piece | Where | Why this shape |
| --- | --- | --- |
| Batch loop (list in → chunked extract → import → resumable state) | `scripts/corpus_batch.py` | Operator-side, on the host that has the credentials and the disk. No new service or queue (§6, §22): the work is bounded, resumable, and already has durable per-import state in `import_jobs`. |
| "What is loaded" surface, HTTP | `GET /api/v1/corpus` (`api/routes.py`, `services/core.py::corpus_summary`) | One read-only, exact answer: counts per dataset version, read from the corpus tables on the request. |
| Same numbers, terminal | `python -m spago_core.corpus_status` (`--json`, `--patents FILE`) | The operator's post-import check and the pre-conclusion check, without a browser. `--patents` exits non-zero and lists every number that is not loaded. |
| Same surface, UI | `CorpusDialog.tsx`, opened from the top-bar dataset badge | The badge already told the user *which* source is loaded; it now opens the full inventory. No new permanent panel (§17): a dialog behind the control that already existed (§18). |
| Publication-list reader | `services/core.py::read_publication_list` | One reader for the CLI and the batch script: one-per-line or CSV/TSV with `--column`; a multi-column file without a column is refused rather than guessed. |

## 2. Verification (commands and observed results)

Backend, unit + API + CLI:

```
cd services/core && .venv/bin/python -m pytest tests/test_corpus_surface.py
# → 13 passed
```

`tests/test_corpus_surface.py` asserts the surface against the tables read
independently: per-kind counts equal the grouped table counts for every
`dataset_version`, totals equal the sum of rows, the demo fixture names itself, a
failed import is reported with its error text, an interrupted import is named in the
notes, a version with no `dataset_info` row is still listed and labelled, and a
target-investigation version keeps its `source_name` from the bioactivity rows.

CLI, against the real local database (not a fixture):

```
DATABASE_URL=… .venv/bin/python -m spago_core.corpus_status
demo-fixture-v1          surechembl_simplified_fixture      1     3      10      12      12       6      1
external:open-databases  —                                  0     0    2774       0       0       0      0  (not a registered package)
bindingdb:2026-09-15     bindingdb                          0     0       0       0       0     961      0  (not a registered package)
chembl:2026-09-15        chembl                             0     0       0       0       0    2696      0  (not a registered package)
user-supplement:v1       user_supplement                    0     0       0       0       0       1      0  (not a registered package)
TOTAL                                                       1     3    2784      12      12    3664      1
```

Coverage check, both directions (the exit code is the deliverable):

```
… --patents /tmp/ok.txt    # DEMO-PATENT-A, DEMO-PATENT-B → exit 0, "2/2 publication(s) in the corpus"
… --patents /tmp/gap.txt   # DEMO-PATENT-A, US-9999999-ZZ → exit 1, "1/2 …", "NOT in the corpus (1): US-9999999-ZZ"
```

Batch loop, planning:

```
services/core/.venv/bin/python scripts/corpus_batch.py --patents /tmp/three.txt \
    --release 2026-09-08 --workdir /tmp/batch-dry --per-package 2 --dry-run
3 publication(s) → 2 package(s) of at most 2, workdir /tmp/batch-dry
  chunk 01: DEMO-PATENT-A, DEMO-PATENT-B → /tmp/batch-dry/chunk-01
  chunk 02: DEMO-PATENT-C → /tmp/batch-dry/chunk-02
```

Batch loop, failure path (release directory that does not exist, so the extractor's own
HTTP error is what surfaces):

```
… --release 1990-01-01 --workdir /tmp/batch-fail2 --per-package 3   # → exit 1
0/1 chunk(s) completed
3/3 requested publication(s) are loaded as documents
chunk(s) did not complete — their chemistry is not verified: chunk-01
re-run with --retry-failed; detail is in /tmp/batch-fail2/batch.log
```

That output is the intended distinction: the *documents* for those numbers are in the
corpus (from an earlier import), while the chunk this run was responsible for never
landed. `STATE.json` records `stage: extract`, the captured error, `attempts`, and
`unfinished_chunks`; a re-run skips completed chunks.

Frontend: `npx tsc -p tsconfig.app.json --noEmit` clean; browser walkthrough of the
badge → `Loaded corpus` dialog recorded in §3.

## 3. Browser check

Recorded with the local compose stack rebuilt from this checkout
(`docker compose build app && docker compose up -d app`; `spago-app-1`,
`127.0.0.1:8000`, viewport 1440×900). Freshness of the served bundle matters here
because the dialog is new code, so the stack was rebuilt rather than reloaded.

| Step | Observed |
| --- | --- |
| Badge is the control | accessibility tree exposes `button "Demo dataset · demo-fixture-v1"` (previously a non-interactive `div`) |
| Click → loading state | `Reading the corpus tables…` rendered while the query was in flight |
| Loaded state | dialog `innerText` = 5 version rows; `demo-fixture-v1 · surechembl_simplified_fixture · synthetic`, `1 families · 3 documents · 10 compounds · 12 mentions · 12 evidence · 6 measurements · 1 record with ingestion issues`, `Retrieved 9/16/2026, 2:01:02 PM · release 2026-09-14`; the four per-row versions labelled `· not an imported package`; `Total 1 families · 3 documents · 2,784 compounds · 12 mentions · 12 evidence · 3,664 measurements`; `Imports: 0 completed`; the unregistered-version note |
| Numbers agree with the API and the CLI | the dialog text above is byte-for-byte the same set of numbers as `curl /api/v1/corpus` and `python -m spago_core.corpus_status` on the same database |
| Escape closes, focus returns | after Escape: `dialog: false`, `document.activeElement.className === "dataset-badge"` |

Not exercised, and therefore not claimed: the **empty** state (`sources.length === 0`)
is unreachable on this deployment because the corpus is non-empty, and the **error**
state was not induced. Both are code paths only.

Latency of the same endpoint, measured on this database (2,784 compounds, 3,664
measurements, 5 versions), three runs: 5.8 ms / 6.1 ms / 6.5 ms, 1,907 bytes.

## 4. Defect found and fixed during this round (test-quality, not product)

`tests/test_real_source_import.py::TestImportCommand::test_failed_import_records_the_error`
asserted on `failed[-1]` of `SELECT … FROM import_jobs WHERE status='failed'` — an
**unordered** query. It passed only while the heap order happened to end with that
row; this module's `import_jobs` inserts/deletes reorder it, and the full suite then
failed with `checksum mismatch` as the last row. Nothing in the product reads that
table without `ORDER BY` (checked `import_package.list_jobs` and `corpus_summary`),
so the fix is in the assertion: any failed row carrying the refusal, and no failed row
without a reason. Verified in both orders
(`pytest tests/test_corpus_surface.py tests/test_real_source_import.py` → 43 passed,
twice) and then by the full suite: **531 passed** (previously 530 passed + 1 failed).

## 5. Deliberate scope decisions (and what would change them)
- **Counts on read, not counters.** `corpus_summary` runs one grouped scan per corpus
  table per request. Measured on this database: 5.8 / 6.1 / 6.5 ms, 1,907 bytes, and
  the dialog is opened on demand. A corpus where this stops being true (measured, not
  projected) is the trigger for maintained counters — recorded here so the decision is
  re-visitable rather than remembered (AGENTS.md §20).
- **No queue, no worker.** `corpus_batch.py` is sequential on purpose: SureChEMBL
  extraction is bandwidth-bound and the release index is the shared bottleneck, so
  parallelism buys little and costs a job system (§6). B-04 (refresh completeness,
  interrupted-import resume) stays open as the next scale-up item.
- **The batch script does not create packages for publications the release lacks.**
  The extractor already fails with the numbers it could not find; the batch loop
  propagates that as a failed chunk with the missing numbers in `STATE.json['missing']`
  rather than inventing a placeholder family.

## 6. Files changed

- `scripts/corpus_batch.py` (new)
- `services/core/spago_core/corpus_status.py` (new)
- `services/core/spago_core/services/core.py` (`corpus_summary`, `publications_in_corpus`, `read_publication_list`)
- `services/core/spago_core/services/__init__.py` (export)
- `services/core/spago_core/api/routes.py` (`GET /api/v1/corpus`)
- `services/core/tests/test_corpus_surface.py` (new, 13 tests)
- `apps/web/src/components/CorpusDialog.tsx` (new), `TopBar.tsx`, `App.tsx`, `api/client.ts`, `api/types.ts`, `styles.css`
- `docs/plans/backlog.md`, `docs/runbook.md`, `README.md`

## 7. Left open

- The empty-corpus and error states of the dialog are exercised by code path only
  (§3) — reachable on a deployment with no import, not on this one.
- The batch loop's happy path against the live release was not re-run here: the
  extraction itself was verified during the hosted-acceptance rehearsal and by
  `scripts/extract_surechembl.py`'s own import tests; what this round added is the loop
  around it, and its failure and planning paths are the ones recorded above.
