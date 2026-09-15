-- ONLINE-01: summaries with an explicit scope (document / family / target).
--
-- A document summary belongs to one document; a target-investigation summary
-- belongs to no patent family at all. Storing them all as "family summaries"
-- would be a factual mislabel, so the owning scope becomes explicit and
-- family_id stops being mandatory.

ALTER TABLE ai_analyses ADD COLUMN IF NOT EXISTS document_id uuid;
ALTER TABLE ai_analyses ADD COLUMN IF NOT EXISTS target_id uuid;

-- Existing rows predate scoped summaries and really are family summaries, so
-- the stored analysis_kind already describes them truthfully. Only the
-- constraint changes.
ALTER TABLE ai_analyses ALTER COLUMN family_id DROP NOT NULL;

CREATE INDEX IF NOT EXISTS idx_ai_analyses_document ON ai_analyses(document_id);
CREATE INDEX IF NOT EXISTS idx_ai_analyses_target ON ai_analyses(target_id);
CREATE INDEX IF NOT EXISTS idx_ai_analyses_kind ON ai_analyses(analysis_kind);

-- Duplicate/conflict-bearing columns for the scoped path.
ALTER TABLE ai_analyses ADD COLUMN IF NOT EXISTS scope_kind text;
UPDATE ai_analyses SET scope_kind = 'family' WHERE scope_kind IS NULL;
ALTER TABLE ai_analyses ALTER COLUMN scope_kind SET DEFAULT 'family';

COMMENT ON COLUMN ai_analyses.scope_kind IS
    'family | document | target — the scope the summary was generated for. '
    'Never relabel an analysis with a wider scope than the facts it was given.';
