-- B-25: the run that brought a set of literature rows in, and what happened to it.
--
-- The one-row supplement path (ONLINE-07) stores a person's own statement. A *set*
-- of rows produced by an agent is a different fact: the rows are proposals until a
-- human has read them, and the import that carried them is an event with its own
-- provenance — who produced it, what was searched, what it refused (AGENTS.md §12).
--
-- `supplement_imports` stores exactly that event, one row per import:
--
--   * the envelope's provenance (`produced_by`, `produced_by_kind`, `searched`,
--     `generated_at`) travels with the run, so a stored row can be traced back to
--     the artifact that proposed it;
--   * `bundle_hash` is the canonical hash of the records, so a re-import is
--     recognisable as the same artifact;
--   * `provenance_state` is what the rows were stored with (`user_curated` for a
--     human's own bundle, `llm_inferred` / `machine_extracted` for an unreviewed
--     one). Unreviewed rows are stored but create **no** `target_candidates` row:
--     migration 0015 defines investigation scope through that table, so a proposal
--     cannot move a verdict, a selection, an export or a summary until a person
--     confirms it — one mechanism, not four filters.
--   * `outcomes` keeps the per-row answers, because a *refused* row is stored
--     nowhere else and "what did the import refuse, and why" is part of the run;
--   * `record_ids` is what confirmation and read-back work from, so no column is
--     added to `measurements` (a large, hot table) for a supplement-only concern.
--
-- Confirmation is recorded here (`confirmed_at`, `confirmed_by`), never in a row the
-- reviewer cannot see later. Nothing is deleted: a withdrawn row keeps its note and
-- its import.
--
-- Forward-compatible: new table, no changes to existing rows or constraints.

CREATE TABLE supplement_imports (
    id                     uuid PRIMARY KEY,
    target_id              uuid NOT NULL REFERENCES targets(id) ON DELETE CASCADE,
    -- sha256 over the canonicalized records: the same bundle imported twice is
    -- recognisable, which is what makes a duplicate report possible at all.
    bundle_hash            text NOT NULL,
    bundle_version         integer NOT NULL DEFAULT 1,
    produced_by            text NOT NULL,
    produced_by_kind       text NOT NULL CHECK (produced_by_kind IN ('human','agent','external')),
    searched               text NOT NULL,
    generated_at           text,
    received               integer NOT NULL DEFAULT 0,
    measurements           integer NOT NULL DEFAULT 0,
    remarks                integer NOT NULL DEFAULT 0,
    rejected               integer NOT NULL DEFAULT 0,
    compounds_created      integer NOT NULL DEFAULT 0,
    compounds_reused       integer NOT NULL DEFAULT 0,
    updated_rows           integer NOT NULL DEFAULT 0,
    -- The row ids this import created or updated, as content-hash record ids.
    record_ids             jsonb NOT NULL DEFAULT '[]'::jsonb,
    -- Per-row answers, including the refused rows that are stored nowhere else.
    outcomes              jsonb NOT NULL DEFAULT '[]'::jsonb,
    -- What the rows were stored as. `user_curated` means the bundle declared a human
    -- producer; anything else is a proposal awaiting review.
    provenance_state       text NOT NULL,
    submitted_by           text,
    created_at             timestamptz NOT NULL DEFAULT now(),
    confirmed_at           timestamptz,
    confirmed_by           text
);

CREATE INDEX idx_supplement_imports_target ON supplement_imports(target_id, created_at DESC);
