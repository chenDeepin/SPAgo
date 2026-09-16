-- B-25: a remark can be a proposal, not only a person's own statement.
--
-- Migration 0014 created `target_supplement_remarks` for rows a person typed, and the
-- constraint said so: `provenance_state IN ('user_curated')`. B-25 imports sets of rows
-- whose producer is an agent or a script, and those rows must be storable while being
-- visibly *not* the user's own (`measurements.provenance_state`, migration 0004, already
-- allows the full set of states: `source_fact`, `database_curated`, `machine_extracted`,
-- `llm_inferred`, `user_curated`).
--
-- So the constraint is widened to the same vocabulary, never dropped: a value outside
-- the states SPAgo defines stays impossible. Existing rows are untouched, and a
-- downgrade of a stored `user_curated` row is refused in the service
-- (`supplements.import_supplements`), not by this constraint — the *column* must be
-- able to hold a proposal, while the *transition* rule is what protects a person's row.
--
-- Forward-compatible: constraint widening only; no data change, no column change.

ALTER TABLE target_supplement_remarks
    DROP CONSTRAINT IF EXISTS target_supplement_remarks_provenance_state_check;

ALTER TABLE target_supplement_remarks
    ADD CONSTRAINT target_supplement_remarks_provenance_state_check
    CHECK (provenance_state IN ('source_fact', 'database_curated', 'machine_extracted',
                                'llm_inferred', 'user_curated'));

COMMENT ON COLUMN target_supplement_remarks.provenance_state IS
    'user_curated for a row a person asserted (ONLINE-07, a bundle a human produced, or '
    'an import a person confirmed); machine_extracted / llm_inferred for a stored row an '
    'agent or script proposed. A proposal is readable, counted separately (unreviewed), '
    'and outside the investigation until it is confirmed (B-25).';
