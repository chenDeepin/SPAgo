-- B-04 2026-09-16: a corpus refresh retracts measurements its release no longer
-- contains, the same never-delete semantics the mention/evidence retraction
-- (migration 0015) already follows for the patent side.
--
-- `measurements` has carried `retracted_at` / `retracted_reason` since 0015 (the
-- hand-added withdraw path writes them). `retracted_by_dataset_version` is the
-- corpus-side counterpart of the column `compound_mentions` and `evidence_records`
-- already have: *which release* dropped the row, so the absence is attributable to
-- a version rather than to an anonymous update.
--
-- Note for later migrations (carried from 0015): `current_measurements` and
-- `investigation_measurements` expose `m.*`, so they are recreated here; a new
-- column on `measurements` does not appear through a stale view.
-- tests/test_investigation_scope.py fails while a view is stale, on purpose.

ALTER TABLE measurements
    ADD COLUMN IF NOT EXISTS retracted_by_dataset_version text;

CREATE OR REPLACE VIEW current_measurements AS
SELECT * FROM measurements WHERE retracted_at IS NULL;

CREATE OR REPLACE VIEW investigation_measurements AS
SELECT DISTINCT tc.target_id AS investigation_target_id,
       m.*
FROM target_candidates tc
JOIN measurements m ON m.compound_id = tc.compound_id
JOIN assays a ON a.id = m.assay_id
LEFT JOIN target_relations r ON r.related_target_id = a.target_id
WHERE tc.retracted_at IS NULL
  AND m.retracted_at IS NULL
  AND (a.target_id = tc.target_id OR r.target_id = tc.target_id);

COMMENT ON COLUMN measurements.retracted_by_dataset_version IS
    'The dataset version whose refresh no longer contains this measurement (B-04).';
