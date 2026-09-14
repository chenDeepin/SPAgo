-- M3: bioactivity (targets, assays, measurements) and Murcko scaffolds.
-- Activity values are only shown when backed by these typed, provenance-carrying
-- records; no activity conclusions are derived without them.

CREATE TABLE targets (
    id              uuid PRIMARY KEY,
    target_key      text NOT NULL UNIQUE,
    name            text,
    organism        text,
    source_name     text NOT NULL,
    dataset_version text NOT NULL,
    retrieved_at    timestamptz NOT NULL,
    created_at      timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE assays (
    id              uuid PRIMARY KEY,
    assay_key       text NOT NULL UNIQUE,
    target_id       uuid NOT NULL REFERENCES targets(id) ON DELETE CASCADE,
    assay_type      text,
    description     text,
    source_name     text NOT NULL,
    dataset_version text NOT NULL,
    retrieved_at    timestamptz NOT NULL,
    created_at      timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE measurements (
    id                uuid PRIMARY KEY,
    compound_id       uuid NOT NULL REFERENCES compounds(id) ON DELETE CASCADE,
    assay_id          uuid NOT NULL REFERENCES assays(id) ON DELETE CASCADE,
    standard_type     text NOT NULL,
    value             double precision NOT NULL,
    unit              text NOT NULL,
    relation          text NOT NULL DEFAULT '=',
    source_record_id  text,
    source_name       text NOT NULL,
    extraction_method text NOT NULL,
    provenance_state  text NOT NULL CHECK (provenance_state IN (
                          'source_fact', 'database_curated', 'machine_extracted',
                          'llm_inferred', 'user_curated')),
    confidence        double precision,
    dataset_version   text NOT NULL,
    retrieved_at      timestamptz NOT NULL,
    created_at        timestamptz NOT NULL DEFAULT now(),
    UNIQUE (compound_id, assay_id, standard_type, source_record_id)
);

CREATE INDEX idx_measurements_compound ON measurements(compound_id);
CREATE INDEX idx_measurements_assay ON measurements(assay_id);

-- Murcko scaffold (canonical SMILES), computed at seed time by RDKit.
ALTER TABLE compounds ADD COLUMN IF NOT EXISTS scaffold text;
CREATE INDEX idx_compounds_scaffold ON compounds(scaffold);
