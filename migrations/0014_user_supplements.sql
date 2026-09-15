-- ONLINE-07: manually added literature rows without a public structure.
--
-- A user may know a potency value from a paper or a patent whose structure is not
-- published (or is a drawn Markush example SPAgo cannot take as a compound). The
-- ported process keeps such a row as a *remark* rather than dropping it, because a
-- thin retrieved set must never be read as a negative result (AGENTS.md §12).
--
-- This cannot live in `compounds`: `canonical_smiles` and `inchikey` are NOT NULL
-- there, and every measurement is compound-scoped, so a structure-less row would
-- either have to invent a structure (forbidden, AGENTS.md §11/§12) or become a
-- compound-shaped row without chemistry. It gets its own table instead, and it is
-- never counted as a measurement.
--
-- Provenance: `user_curated` only. A remark is a statement the user made, with a
-- mandatory note; it is not a source fact and nothing in the pipeline may promote it
-- to one (AGENTS.md §10).
--
-- Forward-compatible: new table, no constraint on existing rows.

CREATE TABLE target_supplement_remarks (
    id                uuid PRIMARY KEY,
    target_id         uuid NOT NULL REFERENCES targets(id) ON DELETE CASCADE,
    -- Content hash of the submitted row (target, name, endpoint, value, unit,
    -- relation, document references), so re-posting the same row updates it
    -- instead of silently duplicating a literature claim (AGENTS.md §22).
    source_record_id  text NOT NULL,
    name              text NOT NULL,
    note              text NOT NULL,
    activity_type     text,
    value             double precision,
    unit              text,
    relation          text,
    doi               text,
    pmid              text,
    patent_number     text,
    source_name       text NOT NULL DEFAULT 'user_supplement',
    provenance_state  text NOT NULL CHECK (provenance_state IN ('user_curated')),
    dataset_version   text NOT NULL,
    created_at        timestamptz NOT NULL DEFAULT now(),
    UNIQUE (target_id, source_record_id)
);

CREATE INDEX idx_supplement_remarks_target ON target_supplement_remarks(target_id);

COMMENT ON TABLE target_supplement_remarks IS
    'Manually added literature/patent rows with a potency but no public structure. '
    'Stored so a thin retrieved set is not read as a negative result; never counted '
    'as a measurement and never exported as a compound.';
COMMENT ON COLUMN target_supplement_remarks.note IS
    'Mandatory user-stated provenance. No default is applied: a generated note would '
    'assert a provenance check the user may not have made.';
COMMENT ON COLUMN target_supplement_remarks.patent_number IS
    'Publication number as entered by the user, normalized to country+digits when it '
    'parses as one. User-declared: not proof of an occurrence in SPAgo''s corpus.';
