"""Auth schemas — request/response models for Auth_Service endpoints.

Satisfies Requirements:
  - 1.1: LoginRequest accepts email + password + optional MFA code.
  - 1.1: TokenPair returns access + refresh tokens.
  - 1.5: CurrentUserResponse returns identity + resolved authorization scope.
  - 1.6: PasswordResetRequest / PasswordResetConfirm for reset flow.
"""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, EmailStr, Field


class LoginRequest(BaseModel):
    """Credentials submitted for authentication."""

    email: EmailStr
    password: str = Field(..., min_length=1)
    mfa_code: str | None = Field(
        default=None, description="TOTP code; required if MFA is enabled for the user"
    )


class TokenPair(BaseModel):
    """Access + refresh token pair issued on successful login."""

    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class RefreshRequest(BaseModel):
    """Refresh token submitted to obtain a new access token."""

    refresh_token: str


class AccessTokenResponse(BaseModel):
    """New access token issued on successful refresh."""

    access_token: str
    token_type: str = "bearer"


class LogoutRequest(BaseModel):
    """Refresh token to revoke on logout."""

    refresh_token: str


class RoleAssignment(BaseModel):
    """A single role assignment with scope context."""

    role_name: str
    scope_level: str
    study_id: UUID | None = None
    site_id: UUID | None = None
    permissions: list[str] = []


class CurrentUserResponse(BaseModel):
    """User identity + resolved authorization scope."""

    id: UUID
    email: str
    first_name: str
    last_name: str
    status: str
    mfa_enabled: bool
    roles: list[RoleAssignment] = []


class PasswordResetRequest(BaseModel):
    """Request to initiate a password reset."""

    email: EmailStr


class PasswordResetConfirm(BaseModel):
    """Token + new password to complete a password reset."""

    token: str
    new_password: str = Field(..., min_length=8)
