-- M1: save-to-project. A project item stores either a whole-family save
-- (compound_id NULL) or a selected-compound save. Idempotent by unique indexes.

CREATE TABLE project_items (
    id              uuid PRIMARY KEY,
    project_id      uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    family_id       uuid NOT NULL REFERENCES patent_families(id) ON DELETE CASCADE,
    compound_id     uuid REFERENCES compounds(id) ON DELETE CASCADE,
    dataset_version text NOT NULL,
    added_at        timestamptz NOT NULL DEFAULT now(),
    created_at      timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX idx_project_items_project ON project_items(project_id);

CREATE UNIQUE INDEX uq_project_family_save
    ON project_items(project_id, family_id) WHERE compound_id IS NULL;
CREATE UNIQUE INDEX uq_project_compound_save
    ON project_items(project_id, family_id, compound_id) WHERE compound_id IS NOT NULL;
