-- ONLINE-00: target-led open-database investigation.
--
-- Adds (1) resolved biological scope for targets, (2) assay context and a
-- conservative evidence class per measurement, (3) deterministic modality for
-- compounds, (4) an explicit candidate record so a compound with assay
-- evidence but no patent mapping stays usable and savable, and (5) a per-source
-- retrieval record that distinguishes empty from failed from not-queried.
--
-- Forward-compatible: every new column is nullable or defaulted, so existing
-- family/project reads keep working after the upgrade (ONLINE-00 C).

-- --- targets: resolved biological scope ------------------------------------------
ALTER TABLE targets ADD COLUMN IF NOT EXISTS uniprot_accession text;
ALTER TABLE targets ADD COLUMN IF NOT EXISTS gene_symbol text;
ALTER TABLE targets ADD COLUMN IF NOT EXISTS taxon_id integer;
ALTER TABLE targets ADD COLUMN IF NOT EXISTS target_type text;
ALTER TABLE targets ADD COLUMN IF NOT EXISTS scope_kind text;
ALTER TABLE targets ADD COLUMN IF NOT EXISTS aliases jsonb;
ALTER TABLE targets ADD COLUMN IF NOT EXISTS components jsonb;
ALTER TABLE targets ADD COLUMN IF NOT EXISTS resolution jsonb;

CREATE INDEX IF NOT EXISTS idx_targets_uniprot ON targets(uniprot_accession);
CREATE INDEX IF NOT EXISTS idx_targets_gene ON targets(gene_symbol);

-- --- resolution runs: what the resolver considered and chose ----------------------
CREATE TABLE target_resolutions (
    id                  uuid PRIMARY KEY,
    query               text NOT NULL,
    species             text NOT NULL,
    status              text NOT NULL CHECK (status IN ('resolved','ambiguous','not_found','failed')),
    chosen_target_id    uuid REFERENCES targets(id) ON DELETE SET NULL,
    chosen_identifier   text,
    candidates          jsonb NOT NULL DEFAULT '[]'::jsonb,
    excluded            jsonb NOT NULL DEFAULT '[]'::jsonb,
    source_name         text NOT NULL,
    source_version      text,
    notes               jsonb NOT NULL DEFAULT '[]'::jsonb,
    retrieved_at        timestamptz NOT NULL,
    created_at          timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX idx_target_resolutions_query ON target_resolutions(query);

-- --- measurements: assay context + evidence class --------------------------------
ALTER TABLE measurements ADD COLUMN IF NOT EXISTS evidence_class text;
ALTER TABLE measurements ADD COLUMN IF NOT EXISTS raw_value text;
ALTER TABLE measurements ADD COLUMN IF NOT EXISTS assay_description text;
ALTER TABLE measurements ADD COLUMN IF NOT EXISTS assay_format text;
ALTER TABLE measurements ADD COLUMN IF NOT EXISTS species text;
ALTER TABLE measurements ADD COLUMN IF NOT EXISTS construct text;
ALTER TABLE measurements ADD COLUMN IF NOT EXISTS variant_accession text;
ALTER TABLE measurements ADD COLUMN IF NOT EXISTS variant_mutation text;
ALTER TABLE measurements ADD COLUMN IF NOT EXISTS pchembl_value double precision;
ALTER TABLE measurements ADD COLUMN IF NOT EXISTS potential_duplicate boolean NOT NULL DEFAULT false;
ALTER TABLE measurements ADD COLUMN IF NOT EXISTS validity_comment text;
ALTER TABLE measurements ADD COLUMN IF NOT EXISTS document_ref text;
ALTER TABLE measurements ADD COLUMN IF NOT EXISTS source_url text;
ALTER TABLE measurements ADD COLUMN IF NOT EXISTS source_molecule_id text;
ALTER TABLE measurements ADD COLUMN IF NOT EXISTS modality_declared text;

CREATE INDEX IF NOT EXISTS idx_measurements_evidence_class ON measurements(evidence_class);

-- --- compounds: deterministic modality -------------------------------------------
ALTER TABLE compounds ADD COLUMN IF NOT EXISTS modality text;
ALTER TABLE compounds ADD COLUMN IF NOT EXISTS modality_rule text;
ALTER TABLE compounds ADD COLUMN IF NOT EXISTS modality_source text;

CREATE INDEX IF NOT EXISTS idx_compounds_modality ON compounds(modality);

-- Existing rows predate the classifier; label them so a NULL is never read as
-- "small molecule by default" (AGENTS.md §10: no silent provenance upgrade).
UPDATE compounds SET modality = 'unclassified', modality_rule = 'pre_classifier'
WHERE modality IS NULL;

-- --- candidate records: compounds proposed for a target by one source -------------
-- Deliberately separate from compound_mentions: a candidate is not a patent
-- occurrence, and its presence is not proof that the compound inhibits the
-- target or is claimed.
CREATE TABLE target_candidates (
    id                 uuid PRIMARY KEY,
    target_id          uuid NOT NULL REFERENCES targets(id) ON DELETE CASCADE,
    compound_id        uuid NOT NULL REFERENCES compounds(id) ON DELETE CASCADE,
    source_name        text NOT NULL,
    source_record_id   text NOT NULL,
    source_molecule_id text,
    evidence_class     text,
    modality           text,
    retrieval_id       uuid,
    dataset_version    text NOT NULL,
    retrieved_at       timestamptz NOT NULL,
    created_at         timestamptz NOT NULL DEFAULT now(),
    UNIQUE (target_id, source_name, source_record_id)
);

CREATE INDEX idx_target_candidates_target ON target_candidates(target_id);
CREATE INDEX idx_target_candidates_compound ON target_candidates(compound_id);

-- --- retrieval runs: the coverage matrix's evidence ------------------------------
CREATE TABLE source_retrievals (
    id                uuid PRIMARY KEY,
    target_id         uuid REFERENCES targets(id) ON DELETE CASCADE,
    source_name       text NOT NULL,
    query             jsonb NOT NULL DEFAULT '{}'::jsonb,
    status            text NOT NULL CHECK (status IN
                          ('complete','partial','empty','failed','not_queried')),
    dataset_version   text,
    source_version    text,
    pages_fetched     integer NOT NULL DEFAULT 0,
    records_seen      integer NOT NULL DEFAULT 0,
    records_kept      integer NOT NULL DEFAULT 0,
    records_excluded  integer NOT NULL DEFAULT 0,
    rejection_counts  jsonb NOT NULL DEFAULT '{}'::jsonb,
    latency_ms        integer,
    warnings          jsonb NOT NULL DEFAULT '[]'::jsonb,
    checksum          text,
    retrieved_at      timestamptz NOT NULL,
    created_at        timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX idx_source_retrievals_target ON source_retrievals(target_id);
CREATE INDEX idx_source_retrievals_source ON source_retrievals(source_name);

ALTER TABLE target_candidates
    ADD CONSTRAINT target_candidates_retrieval_fkey
    FOREIGN KEY (retrieval_id) REFERENCES source_retrievals(id) ON DELETE SET NULL;

-- --- project items: allow non-patent candidates to be saved ----------------------
-- A candidate with assay evidence but no patent mapping must remain savable
-- (ONLINE-00 acceptance); family_id becomes optional and the owning target is
-- recorded instead.
ALTER TABLE project_items ALTER COLUMN family_id DROP NOT NULL;
ALTER TABLE project_items ADD COLUMN IF NOT EXISTS target_id uuid;
ALTER TABLE project_items ADD COLUMN IF NOT EXISTS candidate_id uuid;
-- Snapshot of the biological scope at save time, so a reopen can label the item
-- even if the target row is later replaced by a source refresh.
ALTER TABLE project_items ADD COLUMN IF NOT EXISTS target_key text;
ALTER TABLE project_items ADD COLUMN IF NOT EXISTS target_name text;
ALTER TABLE project_items ADD COLUMN IF NOT EXISTS evidence_class text;

CREATE UNIQUE INDEX IF NOT EXISTS uq_project_candidate_save
    ON project_items(project_id, target_id, compound_id)
    WHERE family_id IS NULL AND compound_id IS NOT NULL;
