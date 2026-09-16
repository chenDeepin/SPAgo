# ADR 0002 — Invitation-only sessions and per-owner data on the existing stack

- Status: accepted for the hosted beta (ONLINE-03)
- Date: 2026-09-15
- Supersedes: none
- Related: `docs/archive/2026-09-15-online-llm.md` §2 (ONLINE-03), AGENTS.md §6, §7, §23, §35

## Problem

SPAgo was built as a local, single-user application: every project, analysis and
export in PostgreSQL belongs to nobody, and any client that can reach the API can
read and write all of it. Hosting it for invited scientists (ONLINE-03) requires
that a user can only reach their own workspace, that unauthenticated and revoked
access fails closed, and that no user can spend the operator's model budget or
select an arbitrary model endpoint.

Two facts constrain the solution:

1. **The local product must keep working.** `docker compose up` with no accounts
   is a supported, documented path (PROMPT.md §15, AGENTS.md §24). A hosted auth
   layer must not make the local workflow require credentials.
2. **No new infrastructure.** AGENTS.md §6 forbids introducing a service (Redis,
   Kafka, a separate auth microservice) without a written decision and measured
   evidence. The stack is React + FastAPI + PostgreSQL + RDKit.

## Decision

Implement ownership with the stack that already exists, and keep the session
mechanism replaceable.

1. **Ownership lives in PostgreSQL, next to the data.**
   - `users`, `invitations` and `sessions` are ordinary tables; a session is a
     row, not a token the application cannot revoke.
   - `projects.owner_id`, `project_items` (through their project) and
     `ai_analyses.owner_id` record the owner. `owner_id IS NULL` means
     "unassigned legacy data" and is **inaccessible** to hosted users. Legacy
     projects are attached to a user only by an explicit operator command
     (`python -m spago_core.admin assign-project`), never by whoever signs in
     first.
   - Project name uniqueness becomes per-owner (`(owner_id, name)`), because two
     scientists may reasonably both have a project called "TSLP screen".

2. **Access is enforced in the service layer, not only at the edge.** Every
   owner-scoped read or write takes the authenticated user as an argument.
   Hiding a button is not access control (AGENTS.md §18, plan ONLINE-03), so the
   tests call the API directly with guessed identifiers.

3. **Sessions are server-side rows with an opaque random token in an HttpOnly
   cookie.** SameSite=Lax; `Secure` whenever the deployment serves HTTPS
   (`SPAGO_COOKIE_SECURE`). State-changing requests additionally require a
   double-submit CSRF header, so a cross-site form post cannot mutate data even
   if the cookie is sent.

4. **Two modes, one code path.** `SPAGO_AUTH_MODE`:
   - `disabled` (default, local): a single implicit local user; behaviour is
     unchanged from the local product.
   - `required` (hosted): every request to a workspace endpoint must carry a
     valid, unexpired, unrevoked session; anonymous access fails closed (401).
   The mode is explicit configuration, not a heuristic: silently degrading
   hosted mode to open access would be the worst possible failure.

5. **Invitation-only.** There is no signup and no password. An operator creates
   an invitation (`python -m spago_core.admin invite <email>`); the invitee
   redeems the token once, which creates the user and a session. Invitations can
   be revoked before use and sessions after use.

6. **The model endpoint is operator-controlled by construction.** Request bodies
   are `extra="forbid"`, so a client cannot inject an endpoint, model name or
   API key. Plan and summary routes read the endpoint from server configuration
   only.

## Alternatives considered

| Option | Why not (yet) |
| --- | --- |
| OIDC provider (Auth0/Keycloak/Google) | Adds an external dependency, a vendor account, a privacy decision about identities, and a second failure mode for the beta. Revisit when an institution requires SSO. |
| Signed stateless JWTs | Cannot be revoked per session without a denylist — which is the session table, minus the ability to inspect it. |
| HTTP Basic auth on the reverse proxy only | Does not give the application an owner identity, so service-layer authorization remains impossible. |
| Password authentication | Requires reset, hashing policy, breach handling and a mailing path for a beta with a handful of invited scientists; adds risk without adding a capability. |
| A managed auth service | New infrastructure with no measured need at this scale (AGENTS.md §6). |

## Consequences

- **Positive.** Revocation is immediate and auditable; ownership is one join
  away; the local path is untouched; no new service, no new runtime dependency,
  no new license obligation.
- **Cost.** Multi-worker deployments must share the database (they already do)
  and cookie-secure configuration is the operator's responsibility; the runbook
  documents it. Sessions have no refresh protocol — a long session is a long
  session, bounded by `SPAGO_SESSION_TTL_HOURS`.
- **Explicitly out of scope.** Team sharing, public signup, SSO, self-service
  account deletion. Documented as NEXT/LATER in the plan, not half-built here.
- **Migration path.** `sessions` and the auth dependency are the only pieces
  coupled to the mechanism. Replacing them with an OIDC integration changes the
  session-creation step; ownership tables, enforcement points and tests stay as
  they are.

## Verification

`services/core/tests/test_online03_auth.py` covers: anonymous rejection in
`required` mode; disabled mode unchanged; invitation redemption, expiry and
revocation; session expiry and logout; user A and user B each using the same
project name; A unable to list/read/modify/export/reuse analyses for B's ids,
including by guessing UUIDs; legacy (`owner_id IS NULL`) data unreachable from
hosted mode; and a client-supplied provider endpoint being rejected by the
request schema.
