-- B-24: what a source declares for a publication, kept apart from the corpus.
--
-- "Enter a patent, see its compounds" degrades to "enter a patent SPAgo happens to
-- hold" when the family was never imported. ChEMBL indexes compounds by the patent
-- document that reports them, so this is a *source-declared* set reached from a
-- publication number, and it must never read as an occurrence in SPAgo's corpus
-- (AGENTS.md §11): no `compound_mentions` row is written by this path, and the
-- corpus counts are untouched.
--
-- Two tables because they are two facts:
--
--   `patent_source_lookups`    one current row per (publication, source): what was
--                              asked, what the source answered, under which match
--                              rule, with which bounds, when, and whether it worked.
--                              A *failed* lookup is stored as failed, so "we asked and
--                              the source failed" never reads as "not queried"
--                              (needed by the coverage audit, B-26).
--   `patent_source_compounds`  one row per declared record, pointing at the shared
--                              `compounds` identity row. A declaration without a
--                              parseable structure never reaches this table; it is
--                              counted in `rejection_counts` instead.
--
-- Structures are not duplicated here: identity is `compounds.inchikey`, so a molecule
-- declared by a source and seen in a patent is one compound, with one depiction.
--
-- `documents` is what matched the rule exactly; `near_matches` are documents the
-- body search returned that normalize to a *different* publication number (another
-- jurisdiction, a longer body). They are listed with their number and excluded from
-- the rows: a body match may be a sibling publication, and silently including or
-- dropping it would both be wrong (AGENTS.md §10).
--
-- Forward-compatible: new tables, no constraint on existing rows.

CREATE TABLE patent_source_lookups (
    id                     uuid PRIMARY KEY,
    -- Normalized token (country + digits) the lookup is keyed by; `requested_number`
    -- keeps exactly what was asked, so a wrong number stays visible.
    publication_number     text NOT NULL,
    requested_number       text NOT NULL,
    source_name            text NOT NULL,
    source_version         text,
    dataset_version        text NOT NULL,
    -- Versioned rule, so a stored set can be read back years later with the rule
    -- that produced it (`chembl-document-patent-body-v1`).
    match_rule             text NOT NULL,
    status                 text NOT NULL CHECK (status IN ('complete','partial','empty','failed')),
    documents              jsonb NOT NULL DEFAULT '[]'::jsonb,
    near_matches           jsonb NOT NULL DEFAULT '[]'::jsonb,
    warnings               jsonb NOT NULL DEFAULT '[]'::jsonb,
    rejection_counts       jsonb NOT NULL DEFAULT '{}'::jsonb,
    records_seen           integer NOT NULL DEFAULT 0,
    records_excluded       integer NOT NULL DEFAULT 0,
    bounds                 jsonb NOT NULL DEFAULT '{}'::jsonb,
    retrieved_at           timestamptz NOT NULL,
    UNIQUE (publication_number, source_name)
);

CREATE TABLE patent_source_compounds (
    id                     uuid PRIMARY KEY,
    lookup_id              uuid NOT NULL REFERENCES patent_source_lookups(id) ON DELETE CASCADE,
    compound_id            uuid NOT NULL REFERENCES compounds(id) ON DELETE CASCADE,
    -- The source's own record id (ChEMBL `activity_id`), so re-running the lookup
    -- updates the row instead of duplicating the declaration.
    source_record_id       text NOT NULL,
    source_molecule_id     text,
    source_molecule_name   text,
    standard_type          text NOT NULL,
    value                  double precision NOT NULL,
    unit                   text NOT NULL,
    relation               text NOT NULL,
    raw_value              text,
    pchembl_value          double precision,
    potential_duplicate    boolean NOT NULL DEFAULT false,
    validity_comment       text,
    assay_key              text,
    assay_type             text,
    assay_description      text,
    target_key             text,
    target_name            text,
    species                text,
    variant_accession      text,
    variant_mutation       text,
    document_ref           text,
    -- As declared by the source, not resolved by us at read time.
    document_patent_number text,
    document_doi           text,
    document_pmid          text,
    source_url             text,
    provenance_state       text NOT NULL CHECK (provenance_state IN (
                               'source_fact','database_curated','machine_extracted',
                               'llm_inferred','user_curated')),
    dataset_version        text NOT NULL,
    retrieved_at           timestamptz NOT NULL,
    UNIQUE (lookup_id, source_record_id)
);

CREATE INDEX idx_patent_source_compounds_lookup
    ON patent_source_compounds(lookup_id);
CREATE INDEX idx_patent_source_compounds_compound
    ON patent_source_compounds(compound_id);

COMMENT ON TABLE patent_source_lookups IS
    'One current source lookup per (publication number, source): the compounds a '
    'source declares for a publication, the match rule and bounds that produced the '
    'set, and whether the lookup succeeded. Not a corpus occurrence (AGENTS.md §11).';
COMMENT ON COLUMN patent_source_lookups.match_rule IS
    'Versioned match rule. chembl-document-patent-body-v1: the source document''s '
    'patent_id normalizes to the same country+digits token as the requested number; '
    'kind code and separators are ignored.';
COMMENT ON COLUMN patent_source_lookups.near_matches IS
    'Documents the body search returned whose patent_id normalizes to a different '
    'publication number (sibling publication or another jurisdiction). Listed, '
    'counted, and never merged into the declared set.';
COMMENT ON COLUMN patent_source_lookups.status IS
    'complete | partial (a bound stopped the retrieval) | empty (the source knows no '
    'document for this number) | failed (the source could not answer). A failed '
    'lookup is stored so it never reads as "not queried".';
COMMENT ON TABLE patent_source_compounds IS
    'One row per record the source declared for the publication. Structures are the '
    'shared `compounds` identity rows; this table writes no compound_mentions row, so '
    'a declared compound never becomes a corpus occurrence.';
COMMENT ON COLUMN patent_source_compounds.potential_duplicate IS
    'As declared by the source (ChEMBL standard_flag/potential_duplicate), not our '
    'cross-source duplicate detection.';
