"""FastAPI authentication dependencies and auth routes (ONLINE-03, ADR-0002).

The dependency is the single place that turns a request into an `AuthUser`, so
every workspace route receives an identity instead of trusting a header. In
`disabled` mode it returns the local identity, which is why the local product
needs no accounts; in `required` mode it fails closed.
"""
from __future__ import annotations

import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field

from spago_core.config import Settings, get_settings
from spago_core.services import auth as auth_svc

router = APIRouter(prefix="/api/v1/auth")

#: Methods that change state, and therefore require a CSRF token.
_STATE_CHANGING = {"POST", "PUT", "PATCH", "DELETE"}


def get_engine(request: Request):
    return request.app.state.engine


def current_user(request: Request, settings: Settings = Depends(get_settings)) -> auth_svc.AuthUser:
    """Resolve the caller. Never returns None: an unauthenticated caller in
    hosted mode is a 401, not an anonymous identity."""
    if not settings.auth_required:
        return auth_svc.LOCAL_USER
    token = request.cookies.get(auth_svc.SESSION_COOKIE)
    try:
        user = auth_svc.authenticate(request.app.state.engine, token)
    except auth_svc.AuthError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    if request.method in _STATE_CHANGING:
        try:
            auth_svc.verify_csrf(
                token,
                request.cookies.get(auth_svc.CSRF_COOKIE),
                request.headers.get(auth_svc.CSRF_HEADER),
            )
        except auth_svc.AuthError as exc:
            raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    return user


def require_admin(user: auth_svc.AuthUser = Depends(current_user)) -> auth_svc.AuthUser:
    if not user.is_admin:
        raise HTTPException(status_code=403, detail="This operation requires an administrator.")
    return user


# --- status and session lifecycle ---------------------------------------------------


class AuthStatusResponse(BaseModel):
    mode: str
    required: bool
    authenticated: bool
    email: Optional[str] = None
    display_name: Optional[str] = None
    is_admin: bool = False
    csrf_token: Optional[str] = None
    session_expires_at: Optional[str] = None
    note: str = ""


@router.get("/status", response_model=AuthStatusResponse)
def auth_status(request: Request, settings: Settings = Depends(get_settings)):
    """Public status: whether sign-in is required and whether this caller is in.

    Deliberately does not reveal whether an arbitrary email has an account.
    """
    if not settings.auth_required:
        return AuthStatusResponse(
            mode="disabled",
            required=False,
            authenticated=True,
            email=None,
            display_name="Local user",
            is_admin=True,
            note=(
                "This deployment runs in local single-user mode: no sign-in is required and "
                "existing data is not attached to an account."
            ),
        )
    token = request.cookies.get(auth_svc.SESSION_COOKIE)
    try:
        user = auth_svc.authenticate(request.app.state.engine, token)
    except auth_svc.AuthError as exc:
        return AuthStatusResponse(
            mode="required",
            required=True,
            authenticated=False,
            note=exc.detail,
        )
    return AuthStatusResponse(
        mode="required",
        required=True,
        authenticated=True,
        email=user.email,
        display_name=user.display_name,
        is_admin=user.is_admin,
        # The page needs the CSRF value to send it back in the header; it is not
        # a secret, and the session token itself stays HttpOnly.
        csrf_token=auth_svc.csrf_token_for(token or ""),
        note="Signed in.",
    )


class RedeemRequest(BaseModel):
    # extra is forbidden so a client cannot smuggle in an email, an admin flag or
    # a provider endpoint alongside the token.
    model_config = {"extra": "forbid"}

    token: str = Field(min_length=8, max_length=400)


class SessionResponse(BaseModel):
    email: str
    display_name: Optional[str] = None
    is_admin: bool = False
    csrf_token: str
    expires_in_hours: int


@router.post("/invitations/redeem", response_model=SessionResponse)
def redeem(
    body: RedeemRequest,
    request: Request,
    response: Response,
    engine=Depends(get_engine),
    settings: Settings = Depends(get_settings),
):
    """Redeem an invitation once and start a session."""
    if not settings.auth_required:
        raise HTTPException(
            status_code=409,
            detail="This deployment does not use accounts; sign-in is not applicable.",
        )
    try:
        user, session_token = auth_svc.redeem_invitation(
            engine,
            body.token,
            session_ttl_hours=settings.session_ttl_hours,
            user_agent=request.headers.get("user-agent"),
        )
    except auth_svc.AuthError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc

    _set_session_cookies(response, session_token, settings)
    return SessionResponse(
        email=user.email,
        display_name=user.display_name,
        is_admin=user.is_admin,
        csrf_token=auth_svc.csrf_token_for(session_token),
        expires_in_hours=settings.session_ttl_hours,
    )


@router.post("/logout")
def logout(
    request: Request,
    response: Response,
    user: auth_svc.AuthUser = Depends(current_user),
    engine=Depends(get_engine),
):
    if user.session_id is not None:
        auth_svc.sign_out(engine, user.session_id)
    response.delete_cookie(auth_svc.SESSION_COOKIE, path="/")
    response.delete_cookie(auth_svc.CSRF_COOKIE, path="/")
    return {"signed_out": True}


class SessionInfo(BaseModel):
    id: str
    created_at: str
    expires_at: str
    last_seen_at: str
    revoked: bool


@router.get("/sessions", response_model=list[SessionInfo])
def list_my_sessions(
    user: auth_svc.AuthUser = Depends(current_user), engine=Depends(get_engine)
):
    """A user's own sessions, so a leaked laptop can be seen and closed."""
    if user.session_id is None:
        return []
    return [SessionInfo(**row) for row in auth_svc.list_sessions(engine, user.id)]


def _set_session_cookies(response: Response, session_token: str, settings: Settings) -> None:
    max_age = max(1, int(settings.session_ttl_hours)) * 3600
    # HttpOnly: page scripts cannot read the session token.
    response.set_cookie(
        auth_svc.SESSION_COOKIE,
        session_token,
        max_age=max_age,
        httponly=True,
        samesite="lax",
        secure=settings.cookie_secure,
        path="/",
    )
    # Readable by the page on purpose: this is the double-submit CSRF value.
    response.set_cookie(
        auth_svc.CSRF_COOKIE,
        auth_svc.csrf_token_for(session_token),
        max_age=max_age,
        httponly=False,
        samesite="lax",
        secure=settings.cookie_secure,
        path="/",
    )
