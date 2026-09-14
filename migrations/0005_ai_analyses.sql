-- M5: persisted AI analyses with citations. Every analysis names its provider
-- and provenance state: offline extractive summaries are machine_extracted;
-- anything from an actual LLM provider must be llm_inferred.

CREATE TABLE ai_analyses (
    id              uuid PRIMARY KEY,
    family_id       uuid NOT NULL REFERENCES patent_families(id) ON DELETE CASCADE,
    provider        text NOT NULL,
    analysis_kind   text NOT NULL,
    text            text NOT NULL,
    citations       jsonb NOT NULL DEFAULT '[]'::jsonb,
    provenance_state text NOT NULL CHECK (provenance_state IN (
                        'source_fact', 'database_curated', 'machine_extracted',
                        'llm_inferred', 'user_curated')),
    dataset_version text NOT NULL,
    created_at      timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX idx_ai_analyses_family ON ai_analyses(family_id);
