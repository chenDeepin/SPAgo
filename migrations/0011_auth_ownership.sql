-- ONLINE-03: users, invitations, sessions and per-owner data (ADR-0002).
--
-- Ownership is recorded next to the data it protects. `owner_id IS NULL` means
-- "unassigned legacy data" and is deliberately unreachable from a hosted
-- session: legacy rows are attached to a user only by an explicit operator
-- command, never by whoever signs in first.

CREATE TABLE users (
    id            uuid PRIMARY KEY,
    email         text NOT NULL,
    display_name  text,
    is_admin      boolean NOT NULL DEFAULT false,
    created_at    timestamptz NOT NULL DEFAULT now(),
    disabled_at   timestamptz
);

-- Email uniqueness is case-insensitive: an invitation for Ada@Example.org and
-- ada@example.org must not create two accounts.
CREATE UNIQUE INDEX uq_users_email_lower ON users (lower(email));

CREATE TABLE invitations (
    id            uuid PRIMARY KEY,
    email         text NOT NULL,
    -- Only the hash is stored: the token itself exists once, in the invitation
    -- link handed to the invitee, and is never recoverable from the database.
    token_hash    text NOT NULL UNIQUE,
    created_by    uuid REFERENCES users(id) ON DELETE SET NULL,
    created_at    timestamptz NOT NULL DEFAULT now(),
    expires_at    timestamptz NOT NULL,
    accepted_at   timestamptz,
    accepted_by   uuid REFERENCES users(id) ON DELETE SET NULL,
    revoked_at    timestamptz,
    note          text
);

CREATE INDEX idx_invitations_email ON invitations (lower(email));

CREATE TABLE sessions (
    id            uuid PRIMARY KEY,
    user_id       uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    token_hash    text NOT NULL UNIQUE,
    created_at    timestamptz NOT NULL DEFAULT now(),
    expires_at    timestamptz NOT NULL,
    last_seen_at  timestamptz NOT NULL DEFAULT now(),
    revoked_at    timestamptz,
    user_agent    text
);

CREATE INDEX idx_sessions_user ON sessions (user_id);

-- --- ownership ------------------------------------------------------------------

ALTER TABLE projects ADD COLUMN IF NOT EXISTS owner_id uuid REFERENCES users(id) ON DELETE CASCADE;

-- Per-owner names (ADR-0002): the global unique constraint becomes per-owner,
-- keeping a single global uniqueness rule for unassigned legacy rows so an
-- operator notices a real duplicate before it is migrated.
ALTER TABLE projects DROP CONSTRAINT IF EXISTS projects_name_key;
CREATE UNIQUE INDEX uq_projects_owner_name ON projects (owner_id, name) WHERE owner_id IS NOT NULL;
CREATE UNIQUE INDEX uq_projects_legacy_name ON projects (name) WHERE owner_id IS NULL;

ALTER TABLE ai_analyses ADD COLUMN IF NOT EXISTS owner_id uuid REFERENCES users(id) ON DELETE CASCADE;

-- Analyses are private workspace content (ADR-0002): a cached analysis of
-- private inputs must never be served to another owner, so the content key
-- includes the owner. Existing rows had no owner and stay unassigned.
DROP INDEX IF EXISTS uq_ai_analyses_input_hash;
CREATE UNIQUE INDEX uq_ai_analyses_owner_input_hash
    ON ai_analyses (owner_id, input_hash) WHERE input_hash IS NOT NULL;
CREATE UNIQUE INDEX uq_ai_analyses_legacy_input_hash
    ON ai_analyses (input_hash) WHERE input_hash IS NOT NULL AND owner_id IS NULL;

COMMENT ON COLUMN projects.owner_id IS
    'Hosted owner. NULL = unassigned legacy data, unreachable from a hosted session.';
COMMENT ON COLUMN ai_analyses.owner_id IS
    'Hosted owner of the analysis and of the inputs it was generated from.';
