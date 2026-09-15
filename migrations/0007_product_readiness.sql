-- PROD-01 + PROD-03 (product readiness): import job records with durable
-- state, and project-item snapshots with the server-derived version list.

CREATE TABLE import_jobs (
    id              uuid PRIMARY KEY,
    source_name     text NOT NULL,
    dataset_version text NOT NULL,
    synthetic       boolean NOT NULL DEFAULT false,
    status          text NOT NULL CHECK (status IN ('queued','running','completed','failed')),
    files           jsonb NOT NULL DEFAULT '{}'::jsonb,
    summary         jsonb,
    error           text,
    created_at      timestamptz NOT NULL DEFAULT now(),
    started_at      timestamptz,
    finished_at     timestamptz
);

-- Saved items keep what was actually saved: identity snapshot at save time
-- and the full list of dataset versions covered by the save (the legacy
-- dataset_version column stays as the single-or-'mixed' label).
ALTER TABLE project_items
    ADD COLUMN IF NOT EXISTS inchikey text,
    ADD COLUMN IF NOT EXISTS canonical_smiles text,
    ADD COLUMN IF NOT EXISTS dataset_versions jsonb;
