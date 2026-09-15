"""Invitation-only authentication and ownership (ONLINE-03, ADR-0002).

Design commitments this module implements:

- **Sessions are rows.** An opaque random token is stored hashed; revoking,
  expiring or logging out is a database update, and a session can be inspected
  by an operator.
- **Two modes, one code path.** `disabled` (default) keeps the local
  single-user product unchanged; `required` (hosted) fails closed for anonymous
  or revoked callers. The mode is explicit configuration.
- **Invitation-only.** There is no signup and no password: an operator creates an
  invitation, the invitee redeems it once.
- **Ownership is data.** `owner_id IS NULL` means unassigned legacy data and is
  never reachable from a hosted session; assignment is an operator action.

Nothing here is a substitute for the service-layer checks in `projects`,
`ai` and `export`: this module answers "who is calling", those modules enforce
"what may this caller touch".
"""
from __future__ import annotations

import hashlib
import secrets
import uuid
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import text
from sqlalchemy.engine import Engine

SESSION_COOKIE = "spago_session"
CSRF_COOKIE = "spago_csrf"
CSRF_HEADER = "x-spago-csrf"
INVITATION_TTL_HOURS = 72
DEFAULT_SESSION_TTL_HOURS = 12

#: Token entropy. 32 bytes of urandom is well beyond guessing; the hash means a
#: database dump does not yield a usable credential.
TOKEN_BYTES = 32


class AuthError(Exception):
    """Authentication failure. Maps to 401 in the API."""

    status_code = 401

    def __init__(self, message: str) -> None:
        self.detail = message
        super().__init__(message)


class ForbiddenError(AuthError):
    """Authenticated but not permitted (or not permitted to perform this)."""

    status_code = 403


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def new_token() -> str:
    return secrets.token_urlsafe(TOKEN_BYTES)


@dataclass(frozen=True)
class AuthUser:
    id: uuid.UUID
    email: str
    display_name: Optional[str]
    is_admin: bool
    session_id: Optional[uuid.UUID] = None


#: The identity used in `disabled` mode. It is not a user row: local data keeps
#: `owner_id IS NULL` exactly as before this change, so the local product's
#: behaviour and its existing rows are untouched.
LOCAL_USER = AuthUser(
    id=uuid.UUID(int=0),
    email="local@spago.invalid",
    display_name="Local user",
    is_admin=True,
    session_id=None,
)


def is_local(user: AuthUser) -> bool:
    return user.session_id is None and user.id == LOCAL_USER.id


# --- users and invitations ---------------------------------------------------------


def create_user(
    engine: Engine, email: str, display_name: str | None = None, is_admin: bool = False
) -> uuid.UUID:
    user_id = uuid.uuid4()
    with engine.begin() as conn:
        existing = conn.execute(
            text("SELECT id FROM users WHERE lower(email) = lower(:email)"), {"email": email}
        ).first()
        if existing:
            return uuid.UUID(str(existing[0]))
        conn.execute(
            text(
                """
                INSERT INTO users (id, email, display_name, is_admin)
                VALUES (:id, :email, :name, :admin)
                """
            ),
            {"id": user_id, "email": email, "name": display_name, "admin": is_admin},
        )
    return user_id


def create_invitation(
    engine: Engine,
    email: str,
    *,
    created_by: uuid.UUID | None = None,
    ttl_hours: int = INVITATION_TTL_HOURS,
    note: str | None = None,
) -> tuple[uuid.UUID, str]:
    """Create an invitation; returns (id, token). The token is shown once."""
    token = new_token()
    invitation_id = uuid.uuid4()
    expires_at = datetime.now(timezone.utc) + timedelta(hours=ttl_hours)
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                INSERT INTO invitations (id, email, token_hash, created_by, expires_at, note)
                VALUES (:id, :email, :hash, :created_by, :expires_at, :note)
                """
            ),
            {
                "id": invitation_id,
                "email": email,
                "hash": hash_token(token),
                "created_by": created_by,
                "expires_at": expires_at,
                "note": note,
            },
        )
    return invitation_id, token


def revoke_invitation(engine: Engine, invitation_id: uuid.UUID) -> bool:
    with engine.begin() as conn:
        result = conn.execute(
            text(
                "UPDATE invitations SET revoked_at = now() "
                "WHERE id = :id AND accepted_at IS NULL AND revoked_at IS NULL"
            ),
            {"id": invitation_id},
        )
        return result.rowcount > 0


def redeem_invitation(
    engine: Engine,
    token: str,
    *,
    session_ttl_hours: int = DEFAULT_SESSION_TTL_HOURS,
    user_agent: str | None = None,
) -> tuple[AuthUser, str]:
    """Redeem an invitation token once; returns (user, session token).

    Every failure mode is distinguishable in the message but none of them
    succeeds: unknown token, revoked, expired, or already redeemed.
    """
    digest = hash_token(token)
    now = datetime.now(timezone.utc)
    with engine.begin() as conn:
        row = conn.execute(
            text(
                """
                SELECT id, email, expires_at, accepted_at, revoked_at
                FROM invitations WHERE token_hash = :hash
                """
            ),
            {"hash": digest},
        ).mappings().first()
        if row is None:
            raise AuthError("This invitation link is not valid.")
        if row["revoked_at"] is not None:
            raise AuthError("This invitation was revoked.")
        if row["accepted_at"] is not None:
            raise AuthError("This invitation has already been used.")
        if row["expires_at"] <= now:
            raise AuthError("This invitation has expired.")
        user_id = create_user_in(conn, row["email"])
        conn.execute(
            text("UPDATE invitations SET accepted_at = now(), accepted_by = :uid WHERE id = :id"),
            {"uid": user_id, "id": row["id"]},
        )
        session_token = _insert_session(conn, user_id, session_ttl_hours, user_agent)
        user = _load_user(conn, user_id)
        # The redemption response is about the account; the session id is not
        # needed by the caller and is deliberately left unset here.
        return replace(user, session_id=None), session_token


def create_user_in(conn, email: str) -> uuid.UUID:
    existing = conn.execute(
        text("SELECT id FROM users WHERE lower(email) = lower(:email)"), {"email": email}
    ).first()
    if existing:
        conn.execute(
            text("UPDATE users SET disabled_at = NULL WHERE id = :id"), {"id": existing[0]}
        )
        return uuid.UUID(str(existing[0]))
    user_id = uuid.uuid4()
    conn.execute(
        text("INSERT INTO users (id, email, display_name) VALUES (:id, :email, NULL)"),
        {"id": user_id, "email": email},
    )
    return user_id


def _insert_session(conn, user_id: uuid.UUID, ttl_hours: int, user_agent: str | None) -> str:
    token = new_token()
    conn.execute(
        text(
            """
            INSERT INTO sessions (id, user_id, token_hash, expires_at, user_agent)
            VALUES (:id, :uid, :hash, :expires_at, :agent)
            """
        ),
        {
            "id": uuid.uuid4(),
            "uid": user_id,
            "hash": hash_token(token),
            "expires_at": datetime.now(timezone.utc) + timedelta(hours=ttl_hours),
            "agent": (user_agent or "")[:200] or None,
        },
    )
    return token


def _load_user(conn, user_id: uuid.UUID) -> AuthUser:
    row = conn.execute(
        text(
            "SELECT id, email, display_name, is_admin FROM users WHERE id = :id "
            "AND disabled_at IS NULL"
        ),
        {"id": user_id},
    ).mappings().first()
    if row is None:
        raise AuthError("This account is not active.")
    return AuthUser(
        id=row["id"],
        email=row["email"],
        display_name=row["display_name"],
        is_admin=bool(row["is_admin"]),
    )


# --- sessions ----------------------------------------------------------------------


def authenticate(engine: Engine, token: str | None) -> AuthUser:
    """Resolve a session token to its user. Raises AuthError for anything else.

    Expiry and revocation are checked on every call, so revoking a session takes
    effect immediately rather than at the next login.
    """
    if not token:
        raise AuthError("Sign in to access this workspace.")
    digest = hash_token(token)
    now = datetime.now(timezone.utc)
    with engine.begin() as conn:
        row = conn.execute(
            text(
                """
                SELECT s.id AS session_id, s.expires_at, s.revoked_at, s.user_id
                FROM sessions s WHERE s.token_hash = :hash
                """
            ),
            {"hash": digest},
        ).mappings().first()
        if row is None:
            raise AuthError("Your session is not valid; sign in again.")
        if row["revoked_at"] is not None:
            raise AuthError("Your session was revoked.")
        if row["expires_at"] <= now:
            raise AuthError("Your session has expired; sign in again.")
        conn.execute(
            text("UPDATE sessions SET last_seen_at = now() WHERE id = :id"),
            {"id": row["session_id"]},
        )
        user = _load_user(conn, row["user_id"])
    return replace(user, session_id=row["session_id"])


def sign_out(engine: Engine, session_id: uuid.UUID) -> None:
    with engine.begin() as conn:
        conn.execute(
            text("UPDATE sessions SET revoked_at = now() WHERE id = :id"), {"id": session_id}
        )


def revoke_user_sessions(engine: Engine, user_id: uuid.UUID) -> int:
    with engine.begin() as conn:
        result = conn.execute(
            text(
                "UPDATE sessions SET revoked_at = now() "
                "WHERE user_id = :uid AND revoked_at IS NULL"
            ),
            {"uid": user_id},
        )
        return result.rowcount


def list_sessions(engine: Engine, user_id: uuid.UUID) -> list[dict]:
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                """
                SELECT id, created_at, expires_at, last_seen_at, revoked_at
                FROM sessions WHERE user_id = :uid ORDER BY created_at DESC
                """
            ),
            {"uid": user_id},
        ).mappings().all()
    return [
        {
            "id": str(r["id"]),
            "created_at": r["created_at"].isoformat(),
            "expires_at": r["expires_at"].isoformat(),
            "last_seen_at": r["last_seen_at"].isoformat(),
            "revoked": r["revoked_at"] is not None,
        }
        for r in rows
    ]


# --- ownership helpers -------------------------------------------------------------


def owner_id_for(user: AuthUser) -> uuid.UUID | None:
    """The `owner_id` value a hosted user's rows carry.

    In local mode this is None, which is exactly how local rows were stored
    before accounts existed — so upgrading does not reinterpret or hide local
    data.
    """
    return None if is_local(user) else user.id


# --- CSRF --------------------------------------------------------------------------


def csrf_token_for(session_token: str) -> str:
    """A deterministic CSRF token bound to the session.

    Deterministic and non-secret: the cookie is readable by the page (that is the
    point of double-submit) while the session cookie is HttpOnly, so a
    cross-origin attacker can send the cookies but cannot read the CSRF value to
    echo it in the header.
    """
    return hashlib.sha256(f"csrf:{session_token}".encode("utf-8")).hexdigest()[:32]


def verify_csrf(session_token: str | None, cookie_value: str | None, header_value: str | None) -> None:
    if session_token is None:
        return  # local mode has no session to protect
    expected = csrf_token_for(session_token)
    if not cookie_value or not header_value:
        raise ForbiddenError(
            "This request is missing its CSRF token. Reload the page and try again."
        )
    if not (
        secrets.compare_digest(cookie_value, expected)
        and secrets.compare_digest(header_value, expected)
    ):
        raise ForbiddenError("This request's CSRF token is not valid for your session.")
