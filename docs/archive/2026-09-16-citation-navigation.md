# B-37 — Summary citation → exact supporting record

> Archived 2026-09-17 — round closed. Delivered record and open remainder: [backlog register](../plans/backlog.md) §1–§2.

Date: 2026-09-16 · Register: `docs/plans/backlog.md` B-37 · Class CORE · P1.

## Vision alignment

`PROMPT.md` §2.1: a user must move from a scientific statement to its original
evidence with one action. Before this round a citation click switched a tab at
best; a cited measurement belonging to another compound went nowhere, and the
analyses archive rendered citations as plain text. After it, every
record-bearing citation resolves to the exact object it names — including
unselected and not-yet-loaded compounds — and a stale or missing record says so
instead of showing silence.

## Delivered

**Typed citation contract (server)** — `services/ai.py`: `measurement`
citations carry `compound_id` (all three scopes' snapshot queries now select
it), `evidence` citations carry `compound_id` when their mention is current
(explicit `null` when it is not — never another compound's id), and the family
citation carries `family_id`. The stored-analysis detail already returned full
citation dicts; the frontend type was widened to match.

**Navigation (frontend)** —
- `AiPanel` passes the whole typed `CitationRef`, not just the ref string.
- `TargetEvidencePanel`: `candidate`/`measurement` citations route to the app,
  which selects the cited compound (the D2 pin keeps a filtered-out compound
  visible) and reopens the panel; the cited measurement row is highlighted and
  scrolled to; a focus id absent from today's rows renders an explicit
  "not in today's stored rows … the data has changed since" note.
- `EvidencePanel` (family/document): citations naming another compound or a
  document route to the app; a cited evidence record that belongs to the open
  compound is shown, highlighted and its occurrence selected; same-compound
  measurement citations expand the activity section in place; missing cited
  records get the explicit note.
- `AnalysesDialog` (B-10 archive): citations in a stored analysis are buttons.
  Target scopes reopen directly by URL state (`t` + `c` + focus); family and
  document scopes reopen through the stored scope query with the cited
  compound selected. When the scope itself is gone (`scope_id` null) the
  citations stay readable text beside the existing "scope is gone" note.
- `App.tsx` owns one `citationFocus` state — set by navigation, cleared when
  the inspector closes — so an older focus can never label a newer selection.

## Verification

- `services/core/tests/test_b37_citation_records.py` (5 cases): measurement
  citations carry a resolvable compound id (checked against the `compounds`
  table), the family citation carries its id, evidence snapshot entries state
  their compound or an explicit null, and a stored target investigation's
  citations keep their compound ids end-to-end through `summarize_target`.
- Regression: `test_m5_ai.py test_online01_scoped_summaries.py
  test_analysis_history.py test_b37_citation_records.py` → 59 passed.
  Frontend typecheck + build green.
- Browser (Playwright, rebuilt stack `12be253-dirty`, viewport 1600×1000,
  stored data only, offline summaries — no provider calls):
  1. **Target panel**: clicked a measurement citation of an unselected IL6
     candidate — the URL switched to `c=<cited compound>`, the panel reopened
     on it and the cited measurement row was highlighted in place.
  2. **Stored analysis**: a citation in an archived target analysis closed the
     dialog and opened `?q=IL6&c=<cited compound>&t=<target id>` — the exact
     record, without a model call.
  3. **Family panel**: a DEMO family measurement citation restored the
     evidence tab and expanded the activity section for the cited compound.

## Deliberate limits

The family view's activity section is aggregated per assay and its endpoint
does not carry measurement ids, so a same-compound family measurement citation
expands the section rather than highlighting one row — record-level highlight
exists where the data supports it (target panel, evidence records). `source:`
and `reference:` citations keep their existing chip/strip focus behaviour.
Forbidden/out-of-scope records surface as the missing-record note rather than
an auth-specific error, because the local stack runs with auth disabled;
owner-scoped reads are the API's contract and were not re-verified in the
browser this round.
