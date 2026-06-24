"""User, role, and invitation schemas — request/response models.

Satisfies Requirements:
  - 3.1: User creation, invitation, and activation schemas.
  - 3.3: Role assignment with study/site scope.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import EmailStr, Field

from app.schemas.base import BaseCreateSchema, BaseSchema, BaseUpdateSchema

# --- User Schemas ---


class UserResponse(BaseSchema):
    """Public representation of a User."""

    id: UUID
    email: str
    first_name: str
    last_name: str
    status: str
    mfa_enabled: bool
    created_at: datetime


class UserCreate(BaseCreateSchema):
    """Payload for creating a new User account."""

    email: EmailStr
    first_name: str = Field(..., min_length=1, max_length=150)
    last_name: str = Field(..., min_length=1, max_length=150)
    password: str = Field(..., min_length=8)


class UserUpdate(BaseUpdateSchema):
    """Partial update payload for an existing User."""

    first_name: str | None = Field(default=None, min_length=1, max_length=150)
    last_name: str | None = Field(default=None, min_length=1, max_length=150)
    status: str | None = None


# --- Role Schemas ---


class RoleResponse(BaseSchema):
    """Public representation of a Role."""

    id: UUID
    name: str
    scope_level: str
    description: str | None = None
    is_system: bool


# --- Invitation Schemas ---


class InvitationCreate(BaseCreateSchema):
    """Payload for inviting a User with a role and optional study/site scope."""

    email: EmailStr
    role_id: UUID
    study_id: UUID | None = None
    site_id: UUID | None = None


class InvitationResponse(BaseSchema):
    """Public representation of an Invitation."""

    id: UUID
    email: str
    token: str
    role_id: UUID
    study_id: UUID | None = None
    site_id: UUID | None = None
    status: str
    created_at: datetime
    expires_at: datetime


# --- Role Assignment Schema ---


class RoleAssignmentRequest(BaseCreateSchema):
    """Payload for assigning a role to a user with optional study/site scope."""

    role_id: UUID
    study_id: UUID | None = None
    site_id: UUID | None = None


# --- Role Create Schema ---


class RoleCreateRequest(BaseCreateSchema):
    """Payload for creating a new Role."""

    name: str = Field(..., min_length=1, max_length=100)
    scope_level: str = Field(..., description="system, study, or site")
    description: str | None = None


# --- Invitation Accept Schema ---


class InvitationAcceptRequest(BaseCreateSchema):
    """Payload for accepting an invitation and activating the account."""

    token: str = Field(..., description="Single-use invitation token")
    password: str = Field(..., min_length=8)
    first_name: str = Field(..., min_length=1, max_length=150)
    last_name: str = Field(..., min_length=1, max_length=150)
