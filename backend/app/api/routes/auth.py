"""Auth routes — login, refresh, logout, current-user, password reset.

Satisfies Requirements:
  - 1.1: POST /auth/login issues signed access + refresh tokens on valid credentials.
  - 1.3: POST /auth/refresh issues a new access token from a valid refresh token.
  - 1.4: POST /auth/logout revokes the refresh token.
  - 1.5: GET /auth/me returns user identity + resolved Authorization_Scope.
  - 1.6: POST /auth/forgot-password and /auth/reset-password implement the
          single-use reset token flow.
  - 21.1: All endpoints mounted under /api/v1 via the auth router.
"""

import logging
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser, get_db
from app.core.exceptions import AuthenticationError
from app.core.security import InvalidTokenError
from app.schemas.auth import (
    AccessTokenResponse,
    CognitoCodeExchangeRequest,
    CognitoRefreshRequest,
    CognitoTokenResponse,
    CurrentUserResponse,
    LoginRequest,
    LogoutRequest,
    PasswordResetConfirm,
    PasswordResetRequest,
    RefreshRequest,
    TokenPair,
)
from app.services.auth_service import AuthenticationError as ServiceAuthError
from app.services.auth_service import auth_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])

# Reusable annotated dependency for DB session in route handlers
DbSession = Annotated[AsyncSession, Depends(get_db)]


@router.post("/cognito/exchange", response_model=CognitoTokenResponse)
async def cognito_exchange(body: CognitoCodeExchangeRequest) -> CognitoTokenResponse:
    """Exchange a Cognito authorization code using PKCE (no client secret)."""
    try:
        result = await auth_service.exchange_cognito_code(
            code=body.code,
            code_verifier=body.code_verifier,
            redirect_uri=body.redirect_uri,
        )
        return CognitoTokenResponse(**result)
    except InvalidTokenError as exc:
        raise AuthenticationError(str(exc)) from None


@router.post("/cognito/refresh", response_model=CognitoTokenResponse)
async def cognito_refresh(body: CognitoRefreshRequest) -> CognitoTokenResponse:
    """Proxy Cognito refresh without exposing a client secret to the SPA."""
    try:
        result = await auth_service.refresh_cognito(body.refresh_token)
        return CognitoTokenResponse(**result)
    except InvalidTokenError as exc:
        raise AuthenticationError(str(exc)) from None


@router.post("/login", response_model=TokenPair)
async def login(body: LoginRequest, session: DbSession) -> TokenPair:
    """Authenticate a user and issue a token pair.

    Requirement 1.1: Issue signed access + refresh tokens on valid credentials.
    Requirement 1.2: Reject invalid credentials without issuing tokens.
    """
    try:
        return await auth_service.login(
            session=session,
            email=body.email,
            password=body.password,
            mfa_code=body.mfa_code,
        )
    except ServiceAuthError as exc:
        raise AuthenticationError(str(exc)) from None


@router.post("/refresh", response_model=AccessTokenResponse)
async def refresh(body: RefreshRequest, session: DbSession) -> AccessTokenResponse:
    """Issue a new access token from a valid refresh token.

    Requirement 1.3: Issue a new access token for a valid, unrevoked refresh token.
    """
    try:
        access_token = await auth_service.refresh(session=session, refresh_token=body.refresh_token)
        return AccessTokenResponse(access_token=access_token)
    except InvalidTokenError as exc:
        raise AuthenticationError(str(exc)) from None


@router.post("/logout", status_code=204)
async def logout(body: LogoutRequest, session: DbSession) -> None:
    """Revoke a refresh token on logout.

    Requirement 1.4: Revoke the refresh token so it cannot be reused.
    """
    try:
        await auth_service.logout(session=session, refresh_token=body.refresh_token)
    except InvalidTokenError as exc:
        raise AuthenticationError(str(exc)) from None


@router.get("/me", response_model=CurrentUserResponse)
async def me(
    current_user: CurrentUser,
    session: DbSession,
) -> CurrentUserResponse:
    """Return the authenticated user's identity and resolved authorization scope.

    Requirement 1.5: Return user identity + resolved Authorization_Scope.
    """
    return await auth_service.me(session=session, user=current_user)


@router.post("/forgot-password", status_code=202)
async def forgot_password(body: PasswordResetRequest, session: DbSession) -> dict:
    """Initiate a password reset by generating a single-use reset token.

    Requirement 1.6: Issue a single-use reset token.
    Always returns 202 to prevent user enumeration.
    """
    await auth_service.request_password_reset(session=session, email=body.email)
    return {"message": "If the email exists, a reset link has been sent."}


@router.post("/reset-password", status_code=200)
async def reset_password(body: PasswordResetConfirm, session: DbSession) -> dict:
    """Complete a password reset using a valid reset token.

    Requirement 1.6: Update the password only when a valid reset token is presented.
    """
    try:
        await auth_service.reset_password(
            session=session, token=body.token, new_password=body.new_password
        )
        return {"message": "Password has been reset successfully."}
    except InvalidTokenError as exc:
        raise AuthenticationError(str(exc)) from None
