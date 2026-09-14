-- SPAgo M0 initial schema.
-- Applied by the versioned migration runner; never edit applied migrations.

CREATE TABLE patent_families (
    id              uuid PRIMARY KEY,
    family_key      text NOT NULL UNIQUE,
    title           text,
    source_name     text NOT NULL,
    dataset_version text NOT NULL,
    retrieved_at    timestamptz NOT NULL,
    created_at      timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE patent_documents (
    id                 uuid PRIMARY KEY,
    family_id          uuid NOT NULL REFERENCES patent_families(id) ON DELETE CASCADE,
    publication_number text NOT NULL UNIQUE,
    title              text,
    abstract           text,
    assignee           text,
    publication_date   date,
    jurisdiction       text,
    doc_type           text,
    source_name        text NOT NULL,
    dataset_version    text NOT NULL,
    retrieved_at       timestamptz NOT NULL,
    created_at         timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX idx_patent_documents_family ON patent_documents(family_id);

CREATE TABLE compounds (
    id                  uuid PRIMARY KEY,
    canonical_smiles    text NOT NULL,
    inchikey            text NOT NULL UNIQUE,
    inchi               text,
    molecular_formula   text,
    molecular_weight    double precision,
    hbd                 integer,
    hba                 integer,
    tpsa                double precision,
    logp                double precision,
    has_stereo          boolean NOT NULL DEFAULT false,
    is_multi_component  boolean NOT NULL DEFAULT false,
    normalization_notes text,
    dataset_version     text NOT NULL,
    created_at          timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX idx_compounds_smiles ON compounds(canonical_smiles);

CREATE TABLE compound_mentions (
    id           uuid PRIMARY KEY,
    compound_id  uuid NOT NULL REFERENCES compounds(id) ON DELETE CASCADE,
    document_id  uuid NOT NULL REFERENCES patent_documents(id) ON DELETE CASCADE,
    patent_label text,
    source_record_id text,
    source_name  text NOT NULL,
    dataset_version text NOT NULL,
    retrieved_at timestamptz NOT NULL,
    created_at   timestamptz NOT NULL DEFAULT now(),
    UNIQUE (compound_id, document_id, patent_label)
);

CREATE INDEX idx_compound_mentions_document ON compound_mentions(document_id);
CREATE INDEX idx_compound_mentions_compound ON compound_mentions(compound_id);

CREATE TABLE evidence_records (
    id                  uuid PRIMARY KEY,
    compound_id         uuid REFERENCES compounds(id) ON DELETE CASCADE,
    compound_mention_id uuid REFERENCES compound_mentions(id) ON DELETE CASCADE,
    document_id         uuid REFERENCES patent_documents(id) ON DELETE CASCADE,
    source_type         text NOT NULL,
    section             text,
    page                integer,
    table_ref           text,
    figure_ref          text,
    paragraph           text,
    compound_local_id   text,
    raw_excerpt         text,
    source_url          text,
    extraction_method   text NOT NULL,
    provenance_state    text NOT NULL CHECK (provenance_state IN (
                            'source_fact', 'database_curated', 'machine_extracted',
                            'llm_inferred', 'user_curated')),
    confidence          double precision,
    dataset_version     text NOT NULL,
    retrieved_at        timestamptz NOT NULL,
    created_at          timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX idx_evidence_compound ON evidence_records(compound_id);
CREATE INDEX idx_evidence_document ON evidence_records(document_id);
CREATE INDEX idx_evidence_mention ON evidence_records(compound_mention_id);

CREATE TABLE dataset_info (
    id              uuid PRIMARY KEY,
    source_name     text NOT NULL,
    dataset_version text NOT NULL,
    synthetic       boolean NOT NULL DEFAULT false,
    release_label   text,
    files           jsonb,
    notes           text,
    retrieved_at    timestamptz NOT NULL,
    created_at      timestamptz NOT NULL DEFAULT now(),
    UNIQUE (source_name, dataset_version)
);

-- Forward-compatibility for M1 save-to-project; no save UI exists at M0.
CREATE TABLE projects (
    id          uuid PRIMARY KEY,
    name        text NOT NULL UNIQUE,
    description text,
    created_at  timestamptz NOT NULL DEFAULT now(),
    updated_at  timestamptz NOT NULL DEFAULT now()
);

-- Recorded validation problems from ingestion (e.g. malformed SMILES).
-- Never silently dropped: AGENTS.md §34.
CREATE TABLE ingestion_issues (
    id              uuid PRIMARY KEY,
    dataset_version text NOT NULL,
    source_record_id text,
    document_id     text,
    patent_label    text,
    raw_smiles      text,
    issue           text NOT NULL,
    created_at      timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX idx_ingestion_issues_dataset ON ingestion_issues(dataset_version);
