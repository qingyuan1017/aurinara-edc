"""Shared cross-cutting ORM model boundary."""

from app.models.shared.audit import AuditEvent
from app.models.shared.export import Export, ExportStatus, ExportType
from app.models.shared.file_attachment import (
    FileAttachment,
    FileAttachmentModule,
    FileAttachmentObjectType,
)
from app.models.shared.identity import (
    Invitation,
    InvitationStatus,
    Permission,
    Role,
    RolePermission,
    ScopeLevel,
    User,
    UserRole,
    UserStatus,
)
from app.models.shared.notification import Notification, NotificationStatus
from app.models.shared.platform_projection import (
    PlatformMembershipProjection,
    PlatformProjectionEvent,
    PlatformRoleMapping,
)
from app.models.shared.revoked_token import RevokedToken

SHARED_MODEL_PACKAGE = "app.models.shared"

__all__ = [
    "SHARED_MODEL_PACKAGE",
    "AuditEvent",
    "Export",
    "ExportStatus",
    "ExportType",
    "FileAttachment",
    "FileAttachmentModule",
    "FileAttachmentObjectType",
    "Invitation",
    "InvitationStatus",
    "Notification",
    "NotificationStatus",
    "Permission",
    "PlatformMembershipProjection",
    "PlatformProjectionEvent",
    "PlatformRoleMapping",
    "RevokedToken",
    "Role",
    "RolePermission",
    "ScopeLevel",
    "User",
    "UserRole",
    "UserStatus",
]
