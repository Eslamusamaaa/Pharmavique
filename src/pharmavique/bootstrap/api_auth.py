"""Accounts: sign up, sign in, refresh, sign out, read and delete the account.

Search, drug pages, alternatives and pharmacies stay open without an account. An account is for
saved data (medicines, alerts, shelf lists), for the company and operator views, and for the
routes that run a model (assistant, scans, voice) while the `login_for_ai` feature is on. Error
answers are deliberately plain: a wrong email and a wrong password look the same.
"""

import logging
from collections.abc import Callable, Coroutine
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, Response, status
from fastapi.responses import HTMLResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field

from pharmavique.bootstrap.features import Features, get_features
from pharmavique.bootstrap.unsubscribe import read_token
from pharmavique.identity.application.service import IdentityService, Session, UserView
from pharmavique.identity.contracts import TokenVerifier
from pharmavique.identity.domain.user import (
    CodeLocked,
    EmailNotVerified,
    EmailTaken,
    InvalidCode,
    InvalidCredentials,
    RoleReview,
    SessionRejected,
)
from pharmavique.shared_kernel.email import EmailError, EmailMessage, EmailSender
from pharmavique.shared_kernel.errors import InvariantViolation
from pharmavique.shared_kernel.principal import Principal, Role

router = APIRouter(prefix="/v1/auth", tags=["accounts"])
_log = logging.getLogger(__name__)
_bearer = HTTPBearer(auto_error=False)


class RegisterIn(BaseModel):
    email: str = Field(max_length=254)
    password: str = Field(max_length=200)
    role: Role


class LoginIn(BaseModel):
    email: str = Field(max_length=254)
    password: str = Field(max_length=200)


class RefreshIn(BaseModel):
    refresh_token: str = Field(min_length=10, max_length=200)


class UserOut(BaseModel):
    id: UUID
    email: str
    role: Role
    tenant_id: UUID | None
    email_verified: bool = True
    email_notifications: bool = True
    # pharmacist and company accounts: pending, verified or rejected by an operator (ADR-020)
    role_review: RoleReview = RoleReview.NOT_NEEDED


class SessionOut(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"  # noqa: S105 (the OAuth token type, not a secret)
    expires_in: int
    user: UserOut


def user_out(view: UserView) -> UserOut:
    return UserOut(
        id=view.id,
        email=view.email,
        role=view.role,
        tenant_id=view.tenant_id,
        email_verified=view.email_verified,
        email_notifications=view.email_notifications,
        role_review=view.role_review,
    )


def _session(session: Session) -> SessionOut:
    return SessionOut(
        access_token=session.access_token,
        refresh_token=session.refresh_token,
        expires_in=session.expires_in,
        user=user_out(session.user),
    )


def get_identity(request: Request) -> IdentityService:
    service: IdentityService | None = request.app.state.identity
    if service is None:
        raise HTTPException(
            status_code=503,
            detail="accounts are not configured: set PHARMAVIQUE_DATABASE_URL and "
            "PHARMAVIQUE_JWT_SECRET, then migrate",
        )
    return service


def _unauthorized(detail: str = "sign in first") -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detail,
        headers={"WWW-Authenticate": "Bearer"},
    )


async def current_principal(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> Principal:
    """The signed-in caller, or a 401. The token is checked without touching the database."""
    verifier: TokenVerifier | None = request.app.state.token_verifier
    if verifier is None:
        raise HTTPException(status_code=503, detail="accounts are not configured")
    if credentials is None:
        raise _unauthorized()
    principal = verifier.verify_token(credentials.credentials)
    if principal is None:
        raise _unauthorized("the session expired, sign in again")
    return principal


async def optional_principal(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> Principal | None:
    """The signed-in caller, or None when no token was sent. A token that was sent but is not
    valid is still a 401: it is never silently treated as "anonymous"."""
    if credentials is None:
        return None
    return await current_principal(request, credentials)


async def signed_in_for_ai(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
    features: Annotated[Features, Depends(get_features)],
) -> Principal | None:
    """For the routes that run a paid or rate-limited model (assistant, scans, voice): a
    signed-in account while the `login_for_ai` feature is on (owner's decision, 2026-11-25),
    otherwise the caller as `optional_principal` sees them."""
    if features.login_for_ai:
        return await current_principal(request, credentials)
    return await optional_principal(request, credentials)


def require_roles(*roles: Role) -> Callable[[Principal], Coroutine[Any, Any, Principal]]:
    """A dependency that lets only these roles through (403 for any other signed-in caller)."""
    allowed = frozenset(roles)

    async def check(principal: Annotated[Principal, Depends(current_principal)]) -> Principal:
        if not principal.roles & allowed:
            raise HTTPException(status_code=403, detail="this account cannot use this view")
        return principal

    return check


class RegisteredOut(BaseModel):
    email: str
    verification_required: bool = True  # enter the code that was emailed; there is no session yet


class VerifyIn(BaseModel):
    email: str = Field(max_length=254)
    code: str = Field(min_length=4, max_length=12)


class ResendIn(BaseModel):
    email: str = Field(max_length=254)


class NotificationsIn(BaseModel):
    email: bool


async def deliver(sender: EmailSender | None, message: EmailMessage) -> None:
    """Send after the response has gone out. A failure is logged without the address or the code;
    the person can ask for a new code."""
    if sender is None:
        _log.warning("no email sender is configured: a message was not sent")
        return
    try:
        await sender.send(message)
    except EmailError as error:
        _log.warning("an email could not be sent: %s", error)
    except Exception as error:  # nothing a sender does may break a finished request
        _log.warning("an email could not be sent (%s)", type(error).__name__)


def get_email_sender(request: Request) -> EmailSender | None:
    sender: EmailSender | None = request.app.state.email_sender
    return sender


@router.post(
    "/register",
    response_model=RegisteredOut,
    status_code=201,
    summary="Create an account; a confirmation code is emailed",
)
async def register(
    body: RegisterIn,
    background: BackgroundTasks,
    service: Annotated[IdentityService, Depends(get_identity)],
    sender: Annotated[EmailSender | None, Depends(get_email_sender)],
) -> RegisteredOut:
    try:
        registration = await service.register(body.email, body.password, body.role)
    except InvariantViolation as error:
        raise HTTPException(status_code=422, detail=str(error)) from None
    except EmailTaken:
        raise HTTPException(status_code=409, detail="this email already has an account") from None
    background.add_task(deliver, sender, registration.email)
    return RegisteredOut(email=registration.user.email)


@router.post("/verify-email", response_model=SessionOut, summary="Confirm the email with the code")
async def verify_email(
    body: VerifyIn, service: Annotated[IdentityService, Depends(get_identity)]
) -> SessionOut:
    try:
        return _session(await service.verify_email(body.email, body.code))
    except CodeLocked:
        raise HTTPException(
            status_code=429, detail="too many wrong codes, ask for a new one"
        ) from None
    except InvalidCode:
        raise HTTPException(status_code=400, detail="the code is wrong or has expired") from None


@router.post("/resend-code", status_code=202, summary="Email a new confirmation code")
async def resend_code(
    body: ResendIn,
    background: BackgroundTasks,
    service: Annotated[IdentityService, Depends(get_identity)],
    sender: Annotated[EmailSender | None, Depends(get_email_sender)],
) -> dict[str, str]:
    message = await service.resend_code(body.email)
    if message is not None:
        background.add_task(deliver, sender, message)
    # the same answer whether or not a code was sent: it must not reveal who has an account
    return {"detail": "if this account needs a code, a new one was sent"}


_PAGE = (
    '<!doctype html><html lang="ar" dir="rtl"><head><meta charset="utf-8">'
    '<meta name="viewport" content="width=device-width,initial-scale=1">'
    '<title>Pharmavique</title></head><body style="font-family:sans-serif;max-width:32rem;'
    'margin:3rem auto;padding:0 1rem">{body}</body></html>'
)


def _unsubscribe_secret(request: Request) -> str:
    secret: str | None = request.app.state.unsubscribe_secret
    if secret is None:
        raise HTTPException(status_code=503, detail="accounts are not configured")
    return secret


@router.get("/unsubscribe", response_class=HTMLResponse, summary="Unsubscribe page (from an email)")
async def unsubscribe_page(request: Request, token: str) -> HTMLResponse:
    if read_token(_unsubscribe_secret(request), token) is None:
        return HTMLResponse(
            _PAGE.format(body="<p>هذا الرابط غير صحيح. This link is not valid.</p>"), 400
        )
    body = (
        "<h2>إيقاف رسائل التنبيهات</h2><p>بنوقف إرسال تنبيهات أدويتك على الإيميل. "
        "التنبيهات تظل ظاهرة في التطبيق.</p>"
        "<p>Stop emailing alerts about your saved medicines? They stay in the app.</p>"
        f'<form method="post" action="/v1/auth/unsubscribe?token={token}">'
        '<button type="submit" style="font-size:1rem;padding:.6rem 1.2rem">'
        "إيقاف · Stop emails</button>"
        "</form>"
    )
    return HTMLResponse(_PAGE.format(body=body))


@router.post("/unsubscribe", response_class=HTMLResponse, summary="Turn email notifications off")
async def unsubscribe(
    request: Request, token: str, service: Annotated[IdentityService, Depends(get_identity)]
) -> HTMLResponse:
    user_id = read_token(_unsubscribe_secret(request), token)
    if user_id is None:
        return HTMLResponse(
            _PAGE.format(body="<p>هذا الرابط غير صحيح. This link is not valid.</p>"), 400
        )
    await service.set_email_notifications(user_id, False)
    return HTMLResponse(
        _PAGE.format(body="<h2>تم الإيقاف</h2><p>Done: no more notification emails.</p>")
    )


@router.put("/me/notifications", status_code=204, summary="Switch email notifications on or off")
async def set_notifications(
    body: NotificationsIn,
    principal: Annotated[Principal, Depends(current_principal)],
    service: Annotated[IdentityService, Depends(get_identity)],
) -> Response:
    if not await service.set_email_notifications(principal.user_id, body.email):
        raise _unauthorized("this account no longer exists")
    return Response(status_code=204)


@router.post("/login", response_model=SessionOut, summary="Sign in")
async def login(
    body: LoginIn, service: Annotated[IdentityService, Depends(get_identity)]
) -> SessionOut:
    try:
        return _session(await service.login(body.email, body.password))
    except InvalidCredentials:
        raise _unauthorized("wrong email or password") from None
    except EmailNotVerified:
        raise HTTPException(status_code=403, detail="email_not_verified") from None


@router.post(
    "/refresh", response_model=SessionOut, summary="Swap a refresh token for a new session"
)
async def refresh(
    body: RefreshIn, service: Annotated[IdentityService, Depends(get_identity)]
) -> SessionOut:
    try:
        return _session(await service.refresh(body.refresh_token))
    except SessionRejected:
        raise _unauthorized("the session ended, sign in again") from None


@router.post("/logout", status_code=204, summary="End this session")
async def logout(
    body: RefreshIn, service: Annotated[IdentityService, Depends(get_identity)]
) -> Response:
    await service.logout(body.refresh_token)
    return Response(status_code=204)


@router.get("/me", response_model=UserOut, summary="The signed-in account")
async def me(
    principal: Annotated[Principal, Depends(current_principal)],
    service: Annotated[IdentityService, Depends(get_identity)],
) -> UserOut:
    view = await service.profile(principal.user_id)
    if view is None:
        raise _unauthorized("this account no longer exists")
    return user_out(view)


@router.delete("/me", status_code=204, summary="Delete the account and everything saved in it")
async def delete_me(
    request: Request,
    principal: Annotated[Principal, Depends(current_principal)],
    service: Annotated[IdentityService, Depends(get_identity)],
) -> Response:
    watchlist = request.app.state.watchlist  # saved medicines, allergies and alerts go with it
    if watchlist is not None:
        await watchlist.forget(principal.user_id)
    await service.delete_account(principal.user_id)
    return Response(status_code=204)
