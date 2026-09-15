"""Operator commands for the hosted beta (ONLINE-03, ADR-0002).

These are administrator operations, run deliberately by the operator on the
server. They are not exposed over HTTP: creating invitations and attaching
legacy data are exactly the operations an external user must not reach, and a
CLI keeps them out of the request surface entirely.

Usage:
    python -m spago_core.admin invite ada@example.org [--admin] [--note "..."]
    python -m spago_core.admin users
    python -m spago_core.admin invitations
    python -m spago_core.admin revoke-invitation <invitation-id>
    python -m spago_core.admin revoke-sessions <email>
    python -m spago_core.admin assign-project <project-id> <email>
    python -m spago_core.admin legacy-projects

`invite` prints the invitation link once. The token is stored only as a hash, so
it cannot be recovered afterwards — re-issue instead.
"""
from __future__ import annotations

import argparse
import sys
import uuid

from sqlalchemy import text

from spago_core.config import get_settings
from spago_core.db import make_engine
from spago_core.services import auth as auth_svc

EXIT_OK = 0
EXIT_USAGE = 2
EXIT_NOT_FOUND = 1


def _engine():
    return make_engine(get_settings().database_url)


def cmd_invite(args) -> int:
    engine = _engine()
    try:
        # The inviting operator must exist as an admin, so an invitation is
        # always attributable.
        inviter = None
        if args.created_by:
            with engine.connect() as conn:
                row = conn.execute(
                    text("SELECT id FROM users WHERE lower(email) = lower(:e)"),
                    {"e": args.created_by},
                ).first()
            if row is None:
                print(
                    f"Unknown inviter {args.created_by!r}. Run "
                    "`python -m spago_core.admin invite <that-email> --admin` first.",
                    file=sys.stderr,
                )
                return EXIT_NOT_FOUND
            inviter = uuid.UUID(str(row[0]))
        invitation_id, token = auth_svc.create_invitation(
            engine,
            args.email,
            created_by=inviter,
            ttl_hours=args.ttl_hours,
            note=args.note,
        )
    finally:
        engine.dispose()

    print(f"Invitation {invitation_id} for {args.email} (expires in {args.ttl_hours}h).")
    print("Redeem link (shown once; the token is stored only as a hash):")
    print(f"  {args.base_url.rstrip('/')}/?invite={token}")
    if args.note:
        print(f"Note: {args.note}")
    return EXIT_OK


def cmd_users(_args) -> int:
    engine = _engine()
    try:
        with engine.connect() as conn:
            rows = conn.execute(
                text(
                    """
                    SELECT u.email, u.display_name, u.is_admin, u.created_at, u.disabled_at,
                           (SELECT count(*) FROM projects p WHERE p.owner_id = u.id) AS projects,
                           (SELECT count(*) FROM sessions s
                             WHERE s.user_id = u.id AND s.revoked_at IS NULL
                               AND s.expires_at > now()) AS live_sessions
                    FROM users u ORDER BY u.created_at
                    """
                )
            ).mappings().all()
    finally:
        engine.dispose()
    if not rows:
        print("No users yet.")
        return EXIT_OK
    for r in rows:
        state = "disabled" if r["disabled_at"] else "active"
        print(
            f"{r['email']:<40} {state:<9} admin={str(bool(r['is_admin'])):<5} "
            f"projects={r['projects']:<3} live_sessions={r['live_sessions']}"
        )
    return EXIT_OK


def cmd_invitations(_args) -> int:
    engine = _engine()
    try:
        with engine.connect() as conn:
            rows = conn.execute(
                text(
                    """
                    SELECT id, email, created_at, expires_at, accepted_at, revoked_at, note
                    FROM invitations ORDER BY created_at DESC
                    """
                )
            ).mappings().all()
    finally:
        engine.dispose()
    if not rows:
        print("No invitations.")
        return EXIT_OK
    for r in rows:
        if r["revoked_at"]:
            state = "revoked"
        elif r["accepted_at"]:
            state = "accepted"
        else:
            state = "pending"
        print(f"{r['id']}  {r['email']:<36} {state:<9} expires {r['expires_at']:%Y-%m-%d}")
    return EXIT_OK


def cmd_revoke_invitation(args) -> int:
    engine = _engine()
    try:
        ok = auth_svc.revoke_invitation(engine, uuid.UUID(args.invitation_id))
    finally:
        engine.dispose()
    if not ok:
        print("Nothing to revoke (unknown, expired or already accepted).", file=sys.stderr)
        return EXIT_NOT_FOUND
    print(f"Invitation {args.invitation_id} revoked.")
    return EXIT_OK


def cmd_revoke_sessions(args) -> int:
    engine = _engine()
    try:
        with engine.begin() as conn:
            row = conn.execute(
                text("SELECT id FROM users WHERE lower(email) = lower(:e)"), {"e": args.email}
            ).first()
            if row is None:
                print(f"Unknown user {args.email!r}.", file=sys.stderr)
                return EXIT_NOT_FOUND
            count = auth_svc.revoke_user_sessions(engine, uuid.UUID(str(row[0])))
    finally:
        engine.dispose()
    print(f"Revoked {count} active session(s) for {args.email}.")
    return EXIT_OK


def cmd_assign_project(args) -> int:
    """Attach a legacy project to a user. Never automatic (ADR-0002)."""
    engine = _engine()
    try:
        with engine.begin() as conn:
            user = conn.execute(
                text("SELECT id FROM users WHERE lower(email) = lower(:e)"), {"e": args.email}
            ).first()
            if user is None:
                print(f"Unknown user {args.email!r}.", file=sys.stderr)
                return EXIT_NOT_FOUND
            project = conn.execute(
                text("SELECT id, owner_id FROM projects WHERE id = :id"),
                {"id": uuid.UUID(args.project_id)},
            ).mappings().first()
            if project is None:
                print(f"Unknown project {args.project_id}.", file=sys.stderr)
                return EXIT_NOT_FOUND
            if project["owner_id"] is not None:
                print(
                    "This project already has an owner; refusing to reassign it. "
                    "Update it deliberately in SQL if that is really intended.",
                    file=sys.stderr,
                )
                return EXIT_USAGE
            conn.execute(
                text("UPDATE projects SET owner_id = :owner WHERE id = :id"),
                {"owner": user[0], "id": project["id"]},
            )
    finally:
        engine.dispose()
    print(f"Project {args.project_id} assigned to {args.email}.")
    return EXIT_OK


def cmd_legacy_projects(_args) -> int:
    """List unassigned projects so an operator can decide their fate."""
    engine = _engine()
    try:
        with engine.connect() as conn:
            rows = conn.execute(
                text(
                    """
                    SELECT p.id, p.name, p.created_at,
                           (SELECT count(*) FROM project_items i WHERE i.project_id = p.id) AS items
                    FROM projects p WHERE p.owner_id IS NULL ORDER BY p.created_at
                    """
                )
            ).mappings().all()
    finally:
        engine.dispose()
    if not rows:
        print("No unassigned projects.")
        return EXIT_OK
    print("Unassigned projects are invisible to hosted users until assigned:")
    for r in rows:
        print(f"{r['id']}  {r['name']:<32} items={r['items']}")
    return EXIT_OK


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="spago_core.admin", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    invite = sub.add_parser("invite", help="create an invitation for one email address")
    invite.add_argument("email")
    invite.add_argument("--admin", action="store_true", help="accepted from the CLI only; informational")
    invite.add_argument("--created-by", help="email of the inviting administrator")
    invite.add_argument("--ttl-hours", type=int, default=auth_svc.INVITATION_TTL_HOURS)
    invite.add_argument("--note")
    invite.add_argument("--base-url", default="http://localhost:8000")
    invite.set_defaults(func=cmd_invite)

    users = sub.add_parser("users", help="list accounts, projects and live sessions")
    users.set_defaults(func=cmd_users)

    invitations = sub.add_parser("invitations", help="list invitations and their state")
    invitations.set_defaults(func=cmd_invitations)

    revoke_invite = sub.add_parser("revoke-invitation", help="revoke a pending invitation")
    revoke_invite.add_argument("invitation_id")
    revoke_invite.set_defaults(func=cmd_revoke_invitation)

    revoke_sessions = sub.add_parser("revoke-sessions", help="sign a user out everywhere")
    revoke_sessions.add_argument("email")
    revoke_sessions.set_defaults(func=cmd_revoke_sessions)

    assign = sub.add_parser("assign-project", help="attach an unassigned project to a user")
    assign.add_argument("project_id")
    assign.add_argument("email")
    assign.set_defaults(func=cmd_assign_project)

    legacy = sub.add_parser("legacy-projects", help="list unassigned projects")
    legacy.set_defaults(func=cmd_legacy_projects)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
