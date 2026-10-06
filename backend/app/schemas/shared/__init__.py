"""Pydantic contracts for shared cross-cutting primitives."""

from app.schemas.shared.ai_assistant import (
    AIApplySuggestionRequest,
    AIChatMessage,
    AIChatRequest,
    AIEditCheckDraftRequest,
    AIQuerySummaryRequest,
)
from app.schemas.shared.audit import (
    AuditEventExport,
    AuditEventResponse,
    AuditSearchFilters,
)
from app.schemas.shared.auth import (
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
    RoleAssignment,
    TokenPair,
)
from app.schemas.shared.base import (
    BaseCreateSchema,
    BaseSchema,
    BaseUpdateSchema,
    ErrorBody,
    ErrorEnvelope,
    IDMixin,
    PaginatedResponse,
    TimestampMixin,
    UtcDatetime,
    serialize_utc,
)
from app.schemas.shared.export import (
    ExportCreate,
    ExportFilters,
    ExportListResponse,
    ExportResponse,
)
from app.schemas.shared.file_attachment import (
    FileAttachmentDelete,
    FileAttachmentResponse,
)
from app.schemas.shared.notification import NotificationResponse
from app.schemas.shared.permission import (
    AuthorizationScope,
    PermissionGrant,
    normalize_permission_code,
)
from app.schemas.shared.user import (
    InvitationAcceptRequest,
    InvitationCreate,
    InvitationResponse,
    RoleAssignmentRequest,
    RoleCreateRequest,
    RoleResponse,
    UserCreate,
    UserResponse,
    UserUpdate,
)

SHARED_SCHEMA_PACKAGE = "app.schemas.shared"

__all__ = [
    "SHARED_SCHEMA_PACKAGE",
    "AIApplySuggestionRequest",
    "AIChatMessage",
    "AIChatRequest",
    "AIEditCheckDraftRequest",
    "AIQuerySummaryRequest",
    "AccessTokenResponse",
    "AuditEventExport",
    "AuditEventResponse",
    "AuditSearchFilters",
    "AuthorizationScope",
    "BaseCreateSchema",
    "BaseSchema",
    "BaseUpdateSchema",
    "CognitoCodeExchangeRequest",
    "CognitoRefreshRequest",
    "CognitoTokenResponse",
    "CurrentUserResponse",
    "ErrorBody",
    "ErrorEnvelope",
    "ExportCreate",
    "ExportFilters",
    "ExportListResponse",
    "ExportResponse",
    "FileAttachmentDelete",
    "FileAttachmentResponse",
    "IDMixin",
    "InvitationAcceptRequest",
    "InvitationCreate",
    "InvitationResponse",
    "LoginRequest",
    "LogoutRequest",
    "NotificationResponse",
    "PaginatedResponse",
    "PasswordResetConfirm",
    "PasswordResetRequest",
    "PermissionGrant",
    "RefreshRequest",
    "RoleAssignment",
    "RoleAssignmentRequest",
    "RoleCreateRequest",
    "RoleResponse",
    "TimestampMixin",
    "TokenPair",
    "UserCreate",
    "UserResponse",
    "UserUpdate",
    "UtcDatetime",
    "normalize_permission_code",
    "serialize_utc",
]
