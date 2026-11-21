"""Accounts: sign up, sign in, refresh, sign out, read and delete the account.

Search, drug pages and the assistant stay open without an account. An account is for saved data
(medicines, alerts, shelf lists) and for the company and operator views. Error answers are
deliberately plain: a wrong email and a wrong password look the same.
"""

from collections.abc import Callable, Coroutine
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field

from pharmavique.identity.application.service import IdentityService, Session, UserView
from pharmavique.identity.contracts import TokenVerifier
from pharmavique.identity.domain.user import EmailTaken, InvalidCredentials, SessionRejected
from pharmavique.shared_kernel.errors import InvariantViolation
from pharmavique.shared_kernel.principal import Principal, Role

router = APIRouter(prefix="/v1/auth", tags=["accounts"])
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


class SessionOut(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"  # noqa: S105 (the OAuth token type, not a secret)
    expires_in: int
    user: UserOut


def _user(view: UserView) -> UserOut:
    return UserOut(id=view.id, email=view.email, role=view.role, tenant_id=view.tenant_id)


def _session(session: Session) -> SessionOut:
    return SessionOut(
        access_token=session.access_token,
        refresh_token=session.refresh_token,
        expires_in=session.expires_in,
        user=_user(session.user),
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


def require_roles(*roles: Role) -> Callable[[Principal], Coroutine[Any, Any, Principal]]:
    """A dependency that lets only these roles through (403 for any other signed-in caller)."""
    allowed = frozenset(roles)

    async def check(principal: Annotated[Principal, Depends(current_principal)]) -> Principal:
        if not principal.roles & allowed:
            raise HTTPException(status_code=403, detail="this account cannot use this view")
        return principal

    return check


@router.post("/register", response_model=SessionOut, status_code=201, summary="Create an account")
async def register(
    body: RegisterIn, service: Annotated[IdentityService, Depends(get_identity)]
) -> SessionOut:
    try:
        return _session(await service.register(body.email, body.password, body.role))
    except InvariantViolation as error:
        raise HTTPException(status_code=422, detail=str(error)) from None
    except EmailTaken:
        raise HTTPException(status_code=409, detail="this email already has an account") from None


@router.post("/login", response_model=SessionOut, summary="Sign in")
async def login(
    body: LoginIn, service: Annotated[IdentityService, Depends(get_identity)]
) -> SessionOut:
    try:
        return _session(await service.login(body.email, body.password))
    except InvalidCredentials:
        raise _unauthorized("wrong email or password") from None


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
    return _user(view)


@router.delete("/me", status_code=204, summary="Delete the account and everything saved in it")
async def delete_me(
    principal: Annotated[Principal, Depends(current_principal)],
    service: Annotated[IdentityService, Depends(get_identity)],
) -> Response:
    await service.delete_account(principal.user_id)
    return Response(status_code=204)
