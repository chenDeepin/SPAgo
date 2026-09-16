# B-32 (machine half) — Scientific cross-read pack and reproducible coverage cohorts

Date: 2026-09-16 · Register: `docs/plans/backlog.md` B-32 · Class CORE · P1.
Operator-gated remainder (the human cross-read itself) is **not** done here; see the
last section.

## Vision alignment

`PROMPT.md` §2.1 (evidence-linked chemistry: understand exactly what the retrieved
set and its summary support). Before this round, a reader who saw "TSLP qualifies"
could not tell which part came from retrieved sources and which from a hand-added
row, and a reviewer asked to cross-read the cohort had no artifact that stated the
build, schema, accessions, source versions, query bounds, policy and modality scope
it was reading. After this round an operator/reviewer runs one script and receives a
stratified pack that states, per record, where every fact came from — so the
independent cross-read (B-32's gated half, feeding B-31) can actually be performed
and repeated. A machine prepares the pack; the pack says in its own Limits section
that a machine cannot approve its own review.

## What was built

1. **Disclosure defect fixed** — `services/core/spago_core/services/coverage.py`
   module docstring and `_REPORT_NOTES` still said a licensed BindingDB snapshot
   "is not configured in this build", stale since B-23 delivered the snapshot access
   path. Both now state the truth: the snapshot is an operator access path (B-23),
   the coverage report has no per-publication snapshot leg, and a snapshot hit is
   neither a corpus occurrence nor a complete publication scan. No patent-led
   snapshot lookup was added. The B-26 test that pins the note ("snapshot" stated,
   not implied) keeps its intent; only its comment changed.
2. **Source-only verdict scoping** — `reference_verdict` /
   `reference_verdicts` gained `include_supplements: bool = True` (default keeps
   every existing caller unchanged). `include_supplements=False` recomputes the same
   counts over the sources' own rows by excluding `user_supplement` measurements in
   the one `_rows` read; hand-added remark/withdrawn/unreviewed visibility stays
   with the combined verdict, and source-side facts (`records_without_structure`)
   belong to both scopes. This is the "source-only baseline" `docs/online-capability.md`
   §5 said was missing.
3. **Pack generator** — new `scripts/cohort_pack.py` (a separate purpose from
   `scripts/cohort_coverage.py`'s coverage matrix: identity + schema + two scoped
   verdicts + reviewer frame, not a retrieval matrix). For a named cohort (default
   the acceptance targets, IL-6/IL-6R named by accession because their symbol forms
   are ambiguous) it emits a JSON record and a Markdown record carrying: served
   build identity fetched verbatim from `/healthz` with `--expected-build` compare
   (mismatch/unreachable exit 1), schema state (applied `schema_migrations` rows,
   read-only, plus files pending in the generator's checkout), resolved targets,
   per-source retrievals (access path, versions, status, counts, `retrieved_at`),
   the verdict twice (source-only and combined) with denominators and
   no-structure counts, the policy and query bounds in force, per-record
   stratification hooks (evidence class, censor relation, stereo stored as
   SMILES+InChIKey, source-declared patent vs corpus occurrence carried separately,
   supplement flag, per-record class under the pack policy), and the Limits
   section. Nothing is written and no source is called.
4. **Tests** — `services/core/tests/test_b32_cohort_pack.py`: service-level scoping
   (supplement moves combined but not source-only; remarks/withdrawals visible only
   in combined; `records_without_structure` in both; batch scoping) and the script's
   plumbing (build match/mismatch/unknown/unreachable, usage refusals,
   stratification counts, markdown stating both verdicts and the limits).

## Verification (commands and results, from this checkout)

- `cd services/core && .venv/bin/python -m pytest
  tests/test_b26_coverage_audit.py tests/test_online06_reference.py
  tests/test_b32_cohort_pack.py` — **80 passed** (42 B-26 + 25 ONLINE-06 + 13 B-32).
- `rtk proxy bash scripts/run_checks.sh --no-pg` — passed ("selected backend tests
  and frontend build passed; database tests not checked" — the database suite is
  not part of `--no-pg`; the three files above ran against the local test database).
- `rtk git diff --check` — clean.
- Pack against the running local stack (read-only; the stack was serving build
  `d9f441a-dirty`, verified by expectation):

      services/core/.venv/bin/python scripts/cohort_pack.py \
          --expected-build d9f441a-dirty \
          --json-out benchmarks/cohort-pack-2026-09-16.json \
          --md-out   benchmarks/cohort-pack-2026-09-16.md
      # exit 0; stderr per target: "TSLP source-only 0/1 · combined 1/2" …

  `--expected-build 3dfd6fc-dirty` (an older build) exited 1 with
  `MISMATCH: expected build_id=3dfd6fc-dirty, served d9f441a-dirty`; during this
  round the stack was rebuilt by another workstream from `3dfd6fc-dirty` to
  `d9f441a-dirty`, which exercised the mismatch path against the live server.

### What the local pack records (headline, source-only → combined per target)

| Target | Source-only | Combined workspace | What moves |
| --- | --- | --- | --- |
| TSLP | **0/1, does not qualify** (53 actives outside modality scope) | **1/2, qualifies** | one `user_supplement` measurement at 250 nM — the historical "1/2 vs 0/1" confusion is now machine-visible as a supplement, not a conflict |
| CD40LG | 6/10, qualifies | 6/10, qualifies | nothing (no supplements stored) |
| IL6 (P05231) | 135/157, qualifies | 135/157, qualifies | nothing; 277 records carry 9 source-declared patents, 0 corpus occurrences |
| IL6R (P08887) | 0/1, does not qualify (not a potency) | 0/1 | nothing; BindingDB leg stored `failed` |
| EGFR | 1833/2531, qualifies | 1833/2531 | nothing; read not truncated (3,346 rows under the 5,000 cap) |

Raw record: `benchmarks/cohort-pack-2026-09-16.json` (2.6 MB — the full
per-record frame is the reviewer's sampling frame; it is capped per target by the
verdict read cap), human record: `benchmarks/cohort-pack-2026-09-16.md`.

## Not verified / not done (operator-gated)

- **The independent human cross-read is not performed or recorded.** Checking
  sampled structure/stereo, assay/units/target assignment, occurrence and
  summary-claim support against original sources is B-32's gated half; the pack
  prepares it and states in its own Limits that a machine cannot approve its own
  review. No §6 checklist box in `docs/online-capability.md` was touched.
- No private data was imported and no new scientific fixture beyond the synthetic
  test rows was added; no claim of scientific accuracy is made or implied by the
  pack, and the local numbers describe this stored workspace only.
- No patent-led BindingDB snapshot lookup was added (correcting the B-26 note is a
  disclosure fix, not a new access path).
- `docs/online-capability.md` §5 still says "neither is a substitute for a
  source-only baseline (B-32)"; now that the baseline exists in the pack, updating
  that sentence and the §6 pointer is a coordinator/documentation follow-up, not
  claimed done here.
- Hosted-shape verification of the pack (a run recorded against a deployed build)
  belongs to B-31's gate; this run was the local stack.
