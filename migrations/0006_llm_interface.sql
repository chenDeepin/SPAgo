-- LLM interface (2026-09-14 plan): content-key caching and input provenance
-- for ai_analyses. All columns nullable: pre-LLM rows stay readable, and rows
-- without input_hash never count as cache hits for the new protocol.

ALTER TABLE ai_analyses ADD COLUMN IF NOT EXISTS model text;
ALTER TABLE ai_analyses ADD COLUMN IF NOT EXISTS input_hash text;
ALTER TABLE ai_analyses ADD COLUMN IF NOT EXISTS prompt_version text;
ALTER TABLE ai_analyses ADD COLUMN IF NOT EXISTS input_snapshot jsonb;
ALTER TABLE ai_analyses ADD COLUMN IF NOT EXISTS usage jsonb;

CREATE UNIQUE INDEX IF NOT EXISTS uq_ai_analyses_input_hash
    ON ai_analyses(input_hash) WHERE input_hash IS NOT NULL;
