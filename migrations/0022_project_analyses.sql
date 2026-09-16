-- B-29 2026-09-16: a stored analysis as a project artifact.
--
-- A project could hold compounds and families, not the analysis that explains
-- why they were picked; a scientist assembling a report copied summary text by
-- hand and lost its scope/version header on the way. This table lets a project
-- reference a stored analysis (B-10's `ai_analyses`) the same way items
-- reference families and compounds: by id, with the identity snapshot kept at
-- attach time.
--
-- The snapshot columns exist for the same reason `project_items` keeps
-- `family_key`/`inchikey` snapshots (migration 0008's contract): if the
-- referenced analysis row is ever removed, the project item stays readable and
-- is marked missing instead of silently disappearing. `ai_analyses` has no
-- delete path today; this is the future-proofing that path will meet.

CREATE TABLE IF NOT EXISTS project_analyses (
    id uuid PRIMARY KEY,
    project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    analysis_id uuid NOT NULL,
    owner_id uuid,
    scope text NOT NULL,
    scope_label text NOT NULL,
    provider text,
    model text,
    prompt_version text,
    dataset_version text,
    analysis_created_at timestamptz,
    added_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (project_id, analysis_id)
);

CREATE INDEX IF NOT EXISTS idx_project_analyses_project
    ON project_analyses(project_id);

COMMENT ON TABLE project_analyses IS
    'Stored analyses a project references (B-29): id plus the identity snapshot '
    'kept at attach time, so a vanished analysis leaves a readable, marked item.';
