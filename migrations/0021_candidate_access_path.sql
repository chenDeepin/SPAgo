-- B-30 2026-09-16: the access path a candidate row arrived through.
--
-- `source_retrievals` holds one row per (target, source) and its
-- `source_version` is *overwritten* by whichever access path asked last (B-23
-- made that overwrite correct: a snapshot run after a REST call must not leave
-- the row reading `bindingdb-rest`). The consequence is that a candidate row's
-- `retrieval_id` cannot tell which path wrote it — and B-30's retraction rule
-- is scoped by exactly that: a complete refresh through one access path
-- retracts only the rows that same path delivered and no longer returns. A
-- REST re-ask must not retract snapshot rows, and a snapshot pass must not
-- retract REST rows, even though both are `source_name = 'bindingdb'`.
--
-- The column is the row's own statement of its origin, written by the run that
-- stored it. The backfill assigns each existing row the source_version of its
-- retrieval row — the best available identity for rows written before this
-- migration; rows with no retrieval link stay NULL and are never retracted by
-- the refresh rule (an unknown origin must not become an inferred absence).
--
-- No view exposes `target_candidates` via SELECT *, so none needs recreating
-- (the rule from migration 0015/0020, checked again here).

ALTER TABLE target_candidates
    ADD COLUMN IF NOT EXISTS source_version text;

UPDATE target_candidates tc
SET source_version = r.source_version
FROM source_retrievals r
WHERE r.id = tc.retrieval_id
  AND tc.source_version IS NULL
  AND r.source_version IS NOT NULL;

COMMENT ON COLUMN target_candidates.source_version IS
    'The access path (retrieval source_version, e.g. bindingdb-rest vs '
    'bindingdb-snapshot-tsv) that wrote this row. NULL means the origin is '
    'not recorded; such rows are never retracted by a refresh (B-30).';
