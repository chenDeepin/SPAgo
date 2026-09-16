# B-30 — A source refresh retracts what its release no longer contains

> Archived 2026-09-17 — round closed. Delivered record and open remainder: [backlog register](../plans/backlog.md) §1–§2.

Date: 2026-09-16 · Register: `docs/plans/backlog.md` B-30 · Class CORE · P1.

## Vision alignment

`PROMPT.md` §2.1 and AGENTS.md §10's refresh-retraction rule: a reader looking
at a candidate list must be able to tell a row the source still reports from
one it dropped. Before this round, rows a source stopped returning stayed
current forever, dated to when they were retrieved — the investigation could
claim more current knowledge than its sources still hold. After it, a complete
refresh states its absences as retractions (never deletions) scoped so tightly
that one access path can never silence another.

## The absence rule (the scope decision the item demanded)

An ask establishes absence only when it **answered the whole question**:
`complete`, or `empty` (the source responded with nothing — a positive
statement about the release for this query). A `failed` or bound-limited
`partial` ask retracts nothing, or an outage becomes a deletion.

The scope of what one complete ask may retract: **the same target, the same
source, and the same access path**. This needed a schema decision: the
retrieval row is shared per (target, source) and its `source_version` is
*overwritten* by whichever path asked last (B-23 made that overwrite correct),
so a candidate row's retrieval link cannot say which path wrote it. Migration
**0021** gives `target_candidates` its own `source_version` (written by the run
that stored the row; backfilled from the retrieval link where one exists).
Rows with no recorded access path — 155 in the operator's stack after the
backfill — are **never retracted**: an unknown origin must not become an
inferred absence.

Mechanics: rows the new run re-delivered are exempt by timestamp (their
`retrieved_at` moves inside the run's transaction); everything older of the
same path is retracted with `retracted_reason` naming the withdrawing
retrieval, its access path and dataset version; re-delivery on a later run
clears the retraction (the 0015 upsert already did). The candidate read path,
the verdict, exports and the investigation view all follow automatically
because they read `retracted_at IS NULL` — retracting a compound's last live
candidate takes its measurements out of the investigation while the shared
measurement rows stay for other scopes.

## Delivered

- Migration `0021_candidate_access_path.sql` (column + backfill + comment).
- `TargetDiscoveryService._retract_dropped_candidates` (discovery.py), run
  inside the write transaction after candidate persistence; per-source counts
  surfaced as `retracted_candidates` on the retrieval response (run responses
  only; a stored-state read says nothing about any run).
- `_persist_candidates` writes the row's access path; the retraction exemption
  is timestamp-based, not id-based, because the retrieval row id is reused
  across runs of the same (target, source).
- The UI run notes state a retraction when one happened ("retracted, not
  deleted — a later retrieval that returns them restores them").
- Runbook §2.7 rewritten: what a retry establishes and what it does not, with
  the B-30 rule stated where the old text said "not implemented".

## Verification

- `tests/test_b30_refresh_retraction.py` — 9 cases: dropped records retracted
  with reason (never deleted), re-delivery clears retraction, the candidates
  read equals exactly the live rows, a failed ask retracts nothing, an `empty`
  answer retracts the whole path, another access path's rows survive a
  complete re-ask (snapshot row during a REST re-ask), legacy rows without an
  access path are never retracted, another target's rows are untouched, and
  the investigation view shrinks with no orphaned measurement while the shared
  `measurements` rows remain.
- Regression: the discovery/refresh cluster (`b06`, `b23`, `online00_api`,
  `online00_discovery`, `b04`, `b30`, `b32`) → **136 passed**.
- The rebuilt stack (`a1ea1ba-dirty`) applied migration 0021 to the operator's
  database — backfill verified in situ (2,696 chembl-web-services, 961
  bindingdb-rest, 155 NULL), `/healthz` ok, the B-17 smoke passes, and the
  stored IL6 investigation still reads 157 candidates.

## Not verified

The UI retraction note was not browser-reproduced this round: showing it needs
a live source that actually drops records between two real asks, which no
local stub serves and the operator's rate limits are not spent on. The note's
backend condition (`retracted_candidates > 0`) and its rendering path are the
same code the API tests exercise. Document-level absence (a corpus package
omitting an entire document) remains out of scope, as B-04 stated.
