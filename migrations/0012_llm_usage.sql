-- ONLINE-04: hosted model-usage accounting and quotas.
--
-- A reservation is written before a paid request and settled with the real
-- usage afterwards. An interrupted request keeps its reservation, which is the
-- conservative direction for a budget: an unacknowledged request may still have
-- been billed by the provider.
--
-- No raw provider payload is stored: only identifiers, scope, outcome and token
-- counts (AGENTS.md §12: operational logs stay separate from scientific
-- evidence and never contain unrestricted provider payloads).

CREATE TABLE llm_usage (
    id                uuid PRIMARY KEY,
    owner_id          uuid REFERENCES users(id) ON DELETE CASCADE,
    provider          text NOT NULL,
    model             text,
    scope             text NOT NULL,
    input_hash        text,
    reserved_tokens   integer NOT NULL DEFAULT 0,
    prompt_tokens     integer,
    completion_tokens integer,
    total_tokens      integer,
    outcome           text NOT NULL CHECK (outcome IN (
                          'reserved','succeeded','failed','auth_failed','rate_limited',
                          'timeout','invalid_output','cache_hit')),
    error             text,
    created_at        timestamptz NOT NULL DEFAULT now(),
    settled_at        timestamptz
);

CREATE INDEX idx_llm_usage_owner_created ON llm_usage (owner_id, created_at);
CREATE INDEX idx_llm_usage_created ON llm_usage (created_at);

COMMENT ON TABLE llm_usage IS
    'Per-request model usage accounting. reserved_tokens is written before the call and '
    'kept when a call does not settle, so an interrupted request cannot silently free budget.';
