# B-25 — Literature supplement bundle import (agent-produced rows)

> Archived 2026-09-17 — round closed. Delivered record and open remainder: [backlog register](../plans/backlog.md) §1–§2.

**Round:** 2026-09-16 (after B-03) · **Class NEXT · P1** · **Owner:** coordinating agent
**Backlog entry:** `docs/plans/backlog.md` §2 B-25 (promoted to P1 when the B-03 round
emptied the P1 group; §4 there argues the promotion)
**Reference read (not copied):** `/media/chen/Machine_Disk/Datasets/BindingDB_IO/` —
`bindingdb_io/web_supplement.py` (`load_web_supplement_file`, `load_supplement_bundle`,
`normalize_web_records`), `examples/web_supplement.example.json`, and the CLI gate flags
(`--web-only-if-empty`, `--web-if-no-active`) read from `cli/extract_target.py` in the
2026-09-16 review. Source, license and destination are recorded in §7.
**Vision served:** `PROMPT.md` §2.1/§2.3 (evidence-linked chemistry, structure-native
retrieval) and `AGENTS.md` §10/§12. What a user can do afterwards that they cannot do
now: **bring a set of literature rows in as one reviewed artifact and confirm them**,
instead of posting them one at a time and having them enter the investigation before
anyone has checked them.

---

## 1. The problem, exactly

`POST /targets/{id}/supplements` accepts a bounded list (≤ 200 rows) and already answers
per row, so the *storage* contract for a set exists. Three things are missing, and each
one was named in the backlog item:

1. **No artifact shape.** The path is a JSON body at a URL, not a file a producer can
   hand over. The workflow that actually produces these rows — an agent or a colleague
   reads papers and writes down what they found — has no documented, self-describing
   container: nothing says who produced the rows, what was searched, or when, which is
   exactly the note `AGENTS.md` §12 requires ("a row without its note is refused rather
   than given a generated one").
2. **No review step.** Every row posted today is stored `user_curated` on arrival, which
   is correct for a person typing one row and **wrong for a set a model proposed**.
   `AGENTS.md` §12: "Rows an agent proposed and a human has not reviewed are not
   `user_curated` and are never merged into source facts; the human confirmation is a
   separate, recorded action." Today an agent bundle can only be imported by asserting
   it was the user's own work.
3. **No trigger.** The moment the supplement is actually needed is the moment the
   reference verdict fails — and the UI does not say so there. A person has to remember
   that the control exists (`ReferenceStrip`'s "Add a row by hand" is a quiet button next
   to the policy footnote).

## 2. What is deliberately *not* changed

- **The row contract.** `SupplementRow` stays as it is (`extra="forbid"`, mandatory
  `note`, a value must state its endpoint and unit) and the same service validates bundle
  rows. A bundle is a container for rows, not a second way to store them.
- **Storage and identity.** Rows go to the same `measurements` / `target_supplement_
  remarks` / `target_candidates` shapes, keyed by the same content hash, through the same
  RDKit normalization and compound identity. A re-import updates instead of duplicating.
- **The withdrawal contract (ONLINE-08).** A confirmed or unreviewed row is taken back
  the same way, with a mandatory reason, never deleted.
- **The one-row dialog.** It keeps working exactly as it does; the bundle is a second
  mode of the same dialog, not a new button (§18).
- **No auto-prefixed notes and no defaulted fields.** The reference implementation fills
  in `"WebSearch supplement; not found in BindingDB."` when a note is missing and defaults
  the organism. SPAgo refuses the row instead — a generated note asserts a provenance
  check nobody made (§10). Recorded as a deliberate difference in §7.
- **No LLM in the import path.** The bundle is data; nothing here decides a target
  assignment, a structure or a class by language. Classes are computed on read by
  `chemistry/activities.py` from the stored numbers, exactly as before.

## 3. Design

### 3a. The bundle artifact (`supplement-bundle-v1`)

A JSON file. A bare list is *not* accepted: the envelope is what carries the provenance
the rule requires, and refusing a list is how a producer learns the shape.

```json
{
  "bundle_version": 1,
  "produced_by": "claude-sonnet + web search, session 2026-09-16",
  "produced_by_kind": "agent",            // human | agent | external
  "searched": "TSLP small-molecule inhibitors in PubMed and Google Patents; queries: ...",
  "generated_at": "2026-09-16T09:00:00Z", // free text, as stated by the producer
  "records": [
    {
      "name": "compound 7",
      "smiles": "CC(=O)Nc1ccc(O)cc1",
      "activity_type": "IC50", "value": 12, "unit": "nM", "relation": "<",
      "doi": "10.1000/example", "pmid": "12345678", "patent_number": "WO 2019/047734",
      "reference": "https://example.org/paper#table2",
      "note": "Table 2, human TSLP, FP assay. Read 2026-09-16."
    }
  ]
}
```

- `produced_by`, `produced_by_kind` and `searched` are **required**; `extra="forbid"` on
  the envelope, so a stray key is refused by name instead of silently ignored.
- `reference` (alias `url`) is appended to the stored note as ` Ref: <value>` — the
  re-find note §12 asks for — and is **never invented**: absent means nothing is added.
- A small, fixed alias table maps the keys the reference example uses, deterministically:
  `ic50_nm`/`ki_nm`/`kd_nm`/`ec50_nm` → `activity_type` + `unit: nM` + `value`;
  `inchikey` → an identity check (refused when it disagrees with the computed one, see
  below); `target` is **refused** (`extra`), because the endpoint already names the
  target and a row that names a different one must not be imported into this one by
  accident. The alias table is a schema adapter, not keyword guessing (§12).
- `records` is bounded by `MAX_SUPPLEMENT_ROWS` (200), refused when exceeded — the
  existing contract, unchanged.
- An optional `uniprot` (or `target_uniprot`) field: when present and it does not match
  the endpoint target's accession, the **whole bundle is refused** with both named. This
  is the guard against handing an agent's file to the wrong investigation; it is an
  identity check, not a resolution.

### 3b. Two provenance states, one confirmation

| `produced_by_kind` | stored `provenance_state` | in the investigation? |
| --- | --- | --- |
| `human` | `user_curated` | yes, immediately (identical to the one-row path) |
| `agent` | `llm_inferred` | **no** — stored, readable, counted separately |
| `external` | `machine_extracted` | **no** — as above |

"Not in the investigation" is a single, honest mechanism rather than a new filter:
`target_candidates` rows are **not created** for unreviewed rows, and migration 0015
already defines investigation scope through that table
(`investigation_measurements` joins `target_candidates`). So an unreviewed row cannot
move the verdict, the candidate table, a selection, an export or a summary — not because
four code paths were patched, but because it has not joined the investigation yet. The
compound row itself is created (normalized identity is shared, as with any import); only
membership is withheld.

**Confirmation** is a separate endpoint and a recorded action:
`POST /targets/{id}/supplement-imports/{import_id}/confirm` sets the rows that import
created to `user_curated` and inserts their `target_candidates` rows, recording who and
when. Idempotent: confirming twice answers "already confirmed at …" instead of writing a
second record. Rows the reviewer does not want are taken back individually with the
existing withdrawal control (reason required, never deleted).

**Provenance never downgrades.** A byte-identical row that a human already asserted stays
`user_curated` even if an agent bundle re-posts it — an import must not be able to turn a
person's statement into a model's. A human re-post *does* upgrade an agent's row (that is
the person asserting it). Between two non-human states the newest producer's state
applies. Enforced in SQL on the upsert, not in the caller.

### 3c. The import report (stored with the run)

New table `supplement_imports` (migration 0018): one row per import —

`id`, `target_id`, `bundle_hash` (sha256 of the canonical records), `bundle_version`,
`produced_by`, `produced_by_kind`, `searched`, `generated_at`, `received`, `measurements`,
`remarks`, `rejected`, `compounds_created`, `compounds_reused`, `updated_rows`,
`record_ids` (jsonb), `outcomes` (jsonb, the per-row answers), `provenance_state`,
`submitted_by`, `created_at`, `confirmed_at`, `confirmed_by`.

`outcomes` is stored because a **refused** row is stored nowhere else, and "what did the
import refuse, and why" is part of the run. `record_ids` is what makes confirmation and
read-back exact without a new column on `measurements`.

### 3d. Serving and the surface

- `POST /targets/{id}/supplements/bundle` — body is the bundle verbatim (so a file can be
  POSTed as-is); response is the report plus the per-row outcomes (the existing
  `SupplementImportResponse` shape, reused).
- `GET /targets/{id}/supplement-imports` — the stored reports, newest first, each with
  its outcomes and the **current stored state** of its rows (kind, compound id, InChIKey,
  value, unit, relation, class under the policy, provenance, retracted) so the dialog can
  render what is waiting without inventing a second read path.
- `POST /targets/{id}/supplement-imports/{import_id}/confirm` — as above.
- Verdict (`ReferenceVerdictResponse`): `unreviewed_supplements` (live rows of either
  kind whose provenance is not `user_curated`), and `supplement_remarks` now counts
  confirmed remarks only. Both are counts next to the existing ones; nothing is dropped
  silently (§11).
- `ReferenceStrip`: when the verdict fails the gate (`compounds_active === 0`) the strip
  states it in its own vocabulary and offers the one control (the same dialog, opened in
  bundle mode): *"No in-scope compound is at or below 10 µM — the sources' set does not
  reach the gate. Literature rows for this target can be added by hand; a set a model
  produced is stored for your review and does not join the investigation until you
  confirm it."* When `unreviewed_supplements > 0`, the strip says N rows await review and
  opens the dialog on that list. No wording that reads an empty set as a negative result
  (§11, and the existing footnote stays).
- `SupplementDialog`: a mode switch — **One row** (unchanged) / **Bundle** (paste JSON or
  choose a `.json` file, read client-side; the client *previews* what it can parse and
  refuses locally for envelope problems, but the server decides per row and its answers
  are what is displayed). After an import the dialog shows the report, and for an
  unreviewed one the **Confirm** control with the row count it is about to assert.

## 4. Verification

- Unit: envelope validation (missing `produced_by`/`searched`/`produced_by_kind`, unknown
  envelope key, >200 records, non-list records, a `target` key refused by name); alias
  mapping (`ic50_nm`, `reference` appended, `inchikey` disagreement refused); a row with
  no note refused per row while the rest of the bundle still imports; `uniprot` mismatch
  refuses the whole bundle.
- PG: an `agent` bundle stores `llm_inferred` measurements/remarks, creates **no**
  `target_candidates` row, and does not move the verdict's `compounds` /
  `compounds_active`; the verdict reports `unreviewed_supplements`; confirmation flips the
  rows to `user_curated`, creates the candidates, and moves the verdict; confirming twice
  does not write a second confirmation; a byte-identical human re-post of an agent row
  upgrades it and an agent re-post of a human row does not downgrade it; re-importing the
  same bundle twice duplicates nothing; a refused row is visible in the stored report.
- API: 404 unknown target, 422 malformed bundle (with the reason), the report list, the
  confirm endpoint's idempotence, and `extra="forbid"` on the envelope.
- Browser (local stack, current checkout): open a target whose verdict fails the gate,
  read the trigger line, import an agent bundle from the dialog, see the rows listed as
  awaiting review with their structures and classes, confirm, and watch the verdict's
  counts and the candidate table change; reload and see the report and the confirmed
  state; a refused row shows its reason.
- Documentation: `docs/online-capability.md` (the bundle path, the two-state rule, the
  trigger), `README.md` (one paragraph), `docs/runbook.md` (a `curl` recipe for an
  operator/agent producing a bundle), `THIRD_PARTY_NOTICES.md` if anything new ships (no
  new dependency is expected).
- Full suite + `npm run build`; `rtk git diff --check`.

## 5. Result

**Delivered 2026-09-16** (local compose stack, current checkout; suite 643 → 677).

- **Schema.** `migrations/0018_supplement_imports.sql` (the run: envelope, counts,
  `record_ids`, `outcomes`, `provenance_state`, `confirmed_at/by`) and
  `migrations/0019_remark_proposal_states.sql` (widens `target_supplement_remarks`'
  single-value provenance constraint to the five states SPAgo defines — a constraint
  widening, no data change, so a remark can hold a *proposal* while the transition rule
  that protects a person's row stays in the service).
- **Domain.** `SupplementBundle` (envelope, `extra="forbid"`, version check,
  `MAX_SUPPLEMENT_ROWS`), `SupplementImportReport` (the stored run + `stored` row state),
  `SupplementBundleImport`, `SupplementConfirmation`, `SuppliedRowState`,
  `ReferenceVerdict.unreviewed_supplements`.
- **Service.** `map_bundle_record` (alias table, `reference`→note, contradiction
  refusals), `supplement_bundle_hash`, `_bundle_matches_target`, `import_supplement_bundle`,
  `list_supplement_imports`, `confirm_supplement_import`, `count_unreviewed_supplements`,
  provenance-preserving upserts in `_store_remark` / the measurement insert, and the
  one-transition confirm (provenance + `target_candidates` in one act).
- **API.** `POST /targets/{id}/supplements/bundle`,
  `GET /targets/{id}/supplement-imports`,
  `POST /targets/{id}/supplement-imports/{import_id}/confirm`;
  `unreviewed_supplements` on the verdict.
- **UI.** `SupplementDialog` gained the mode switch (one row / a set of rows) and the
  bundle pane (paste or load a `.json`, client-side envelope preview, the report with
  refused rows and their reasons, the row list with live/withdrawn state, confirm and
  take-back controls); `ReferenceStrip` states the failed gate in its own vocabulary and
  offers the review control when proposals exist; the verdict counts an
  `unreviewed_supplements` chip.
- **Tests.** `services/core/tests/test_b25_supplement_bundle.py` — 34 cases over
  mapping, envelope, the three producer kinds, confirmation (idempotence, withdrawn
  rows, cross-target refusal), provenance never downgrading, the report (refusals,
  repeat, current row state, re-posted rows counted as updates) and the HTTP contract
  (import → read back → confirm; the candidate list, the verdict and the export).
  Suite 643 → 677, all green; `npm run build` and `tsc --noEmit` clean.

**Browser check (local stack, current checkout, `?q=CDK4&t=…`, viewport 1280×800):**
imported an agent bundle (3 records: one measurement with a structure, one
structure-less remark, one self-contradicting record), read the report — the refusal
names the row and the rule, the two stored rows show their class and note — confirmed it
("I have read these rows"), and verified the transition end to end:
`qualifies false` / 0 compounds / 2 unreviewed → `qualifies true` / 1 compound at
≤ 10 µM / 1 remark / 0 unreviewed, with the candidate appearing in the table. Then
withdrew the confirmed row (reason recorded, row readable, verdict back to "no reference
set", candidate gone), re-imported the same file (recognised, `repeat_of` set, both rows
counted as updates, the withdrawn row re-posted as live) and read the history back. The
fresh report is no longer rendered twice (it was, before the fix below).

**Three defects the check found, all fixed in this round:**
1. the import that had just arrived was rendered both as the fresh report and again in
   the history list (one import, two confirm controls);
2. `updated_rows` was 0 for a re-posted **remark** — only the measurement path counted
   an existing row, so a run that updated a stored remark reported it as new;
3. `repeated_of` survived only in the POST response: it was passed in at insert time and
   not derived on read, so "the same file was imported before" disappeared on reload.
   Now derived from the runs themselves (earlier run, same hash, same target).

## 6. Open questions settled while implementing

- **Is an unreviewed row "not in the investigation" or "in it, flagged"?** Not in it:
  no `target_candidates` row, so migration 0015's scope definition does the filtering
  once instead of four read paths filtering. Confirmation is the only insert.
- **Where does a re-posted row's provenance land?** The strongest state it ever had:
  a person's row is never downgraded by a later agent import, and a person's re-post
  does upgrade a proposal.
- **What happens to a proposal whose row the reviewer takes back before confirming?**
  Confirmation admits live rows only; the withdrawn row stays withdrawn and readable.
  Confirming twice answers "already confirmed" instead of writing a second record.
- **Is a bundle for the wrong target caught?** Only if the file states `uniprot`; then
  the whole bundle is refused with both proteins named. Without the field, the rows are
  about whatever the producer wrote — the envelope is the only place that claim can
  live, and the dialog says so.
- **Does the one-row path change?** Only in the ways the bundle needed: the same
  service, the same row contract, the same withdrawal semantics; a one-row POST is
  still `user_curated` on arrival.
- **A refused row: dropped or stored?** Stored in the run's `outcomes` with its
  reasons — "what did this file propose that SPAgo would not store" is part of the
  record, and a rejected row is not a lost row.

## 7. Reference, license and what was not taken

`/media/chen/Machine_Disk/Datasets/BindingDB_IO/` is the author's own project (same
author as SPAgo), read read-only on 2026-09-16. What travels across is the *shape* of the
idea and two field names: the envelope concept ("a bundle names the run that produced it")
and `reference` as the URL field. No code was copied: the loader, the alias table, the
validation and the storage path are written against SPAgo's own contracts
(`SupplementRow`, `persist_compounds`, the content-hash row id), and the differences are
deliberate and listed in §2 — no auto-prefixed notes, no defaulted organism, no
`Target Name` per row, no file-keyed multi-target grouping (SPAgo's endpoint is already
per target, and a group keyed by an output filename has no meaning here). The reference
project is not a dependency: nothing in SPAgo imports it, no notice entry is added, and
this section is the recorded attribution required by `AGENTS.md` §0/§34.
