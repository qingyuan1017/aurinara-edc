"""Per-Environment Pydantic settings.

Satisfies Requirement 25.1 — isolated Environments (local, dev, test, staging, production)
with separate database, object storage, secrets, authentication, and logging configuration.
"""

from enum import StrEnum
from functools import lru_cache

from pydantic import PostgresDsn, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Environment(StrEnum):
    """Supported deployment environments."""

    LOCAL = "local"
    DEVELOPMENT = "development"
    TEST = "test"
    STAGING = "staging"
    PRODUCTION = "production"


class Settings(BaseSettings):
    """Application settings loaded from environment variables or .env file.

    Each environment has separate configuration for database, object storage,
    secrets, authentication, and logging (Requirement 25.1).
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # --- Core ---
    app_name: str = "Clinical EDC"
    environment: Environment = Environment.LOCAL
    debug: bool = False
    api_v1_prefix: str = "/api/v1"

    # --- Database ---
    # Every deployment supplies an environment-specific URL.  The namespace
    # is also used by local storage and queue implementations so test/staging
    # data cannot accidentally share a production namespace.
    database_url: PostgresDsn = "postgresql+asyncpg://edetek:edetekpassword@localhost:5432/edc"  # type: ignore[assignment]
    database_echo: bool = False
    database_pool_size: int = 10
    database_max_overflow: int = 20
    environment_namespace: str = "local"

    # --- Environment isolation and recovery ---
    secrets_backend: str = "environment"
    secrets_namespace: str = "local"
    auth_issuer: str | None = None
    auth_audience: str | None = None
    logging_sink: str = "stdout"
    logging_namespace: str = "local"
    retention_days: int = 2555
    # CTMS retention is independently configurable per owned/shared resource.
    # A missing override inherits the platform retention period.
    ctms_operational_retention_days: int | None = None
    ctms_projection_retention_days: int | None = None
    ctms_event_attempt_retention_days: int | None = None
    ctms_event_log_retention_days: int | None = None
    ctms_failed_event_retention_days: int | None = None
    ctms_conflict_retention_days: int | None = None
    ctms_export_retention_days: int | None = None
    ctms_attachment_retention_days: int | None = None
    ctms_notification_retention_days: int | None = None
    ctms_audit_retention_days: int | None = None
    ctms_retention_batch_size: int = 500
    backup_enabled: bool = False
    backup_storage_uri: str | None = None
    restore_enabled: bool = False
    backup_schedule: str | None = None

    # --- Security ---
    secret_key: str = "CHANGE-ME-IN-PRODUCTION"
    access_token_expire_minutes: int = 30
    refresh_token_expire_days: int = 7
    inactivity_timeout_minutes: int = 30

    # --- Optional: AWS Cognito / OIDC ---
    cognito_user_pool_id: str | None = None
    cognito_region: str | None = None
    cognito_app_client_id: str | None = None

    # --- Object storage (local by default; S3-compatible when configured) ---
    object_storage_backend: str = "local"
    object_storage_local_dir: str = "attachments"
    object_storage_namespace: str = "local"
    max_attachment_size_bytes: int = 50 * 1024 * 1024
    # Comma-separated allowlist for CTMS operational attachments.  EDC's
    # legacy attachment path remains backward compatible, while CTMS uploads
    # reject unknown types instead of treating arbitrary bytes as clinical data.
    operational_attachment_allowed_mime_types: str = (
        "application/pdf,text/plain,text/csv,image/jpeg,image/png,image/gif,"
        "application/zip,application/msword,application/vnd.openxmlformats-officedocument.wordprocessingml.document,"
        "application/vnd.ms-excel,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    s3_bucket_name: str | None = None
    s3_region: str | None = None
    s3_endpoint_url: str | None = None
    s3_access_key_id: str | None = None
    s3_secret_access_key: str | None = None

    # --- CTMS phased capability rollout ---
    # Disabling CTMS only hides CTMS capabilities; it never deletes CTMS data
    # or changes EDC routes and clinical workflows.
    ctms_enabled: bool = True
    ctms_phase: int = 1

    @field_validator("ctms_phase")
    @classmethod
    def validate_ctms_phase(cls, value: int) -> int:
        """Accept only the published CTMS delivery phases (0 means disabled)."""
        if value not in (0, 1, 2, 3):
            raise ValueError("CTMS_PHASE must be 0, 1, 2, or 3")
        return value

    # --- Optional: Redis ---
    redis_url: str | None = None
    ctms_worker_enabled: bool = True
    ctms_escalations_enabled: bool = False
    ctms_queue_capacity: int = 1000
    ctms_coordination_max_attempts: int = 3
    ctms_coordination_backoff_base_seconds: int = 1
    ctms_coordination_backoff_max_seconds: int = 60
    ctms_projection_lag_warning_seconds: int = 300

    # --- Optional: AWS Bedrock AgentCore AI assistant ---
    ai_assistant_enabled: bool = False
    ctms_ai_enabled: bool = False
    bedrock_agentcore_runtime_arn: str | None = None
    bedrock_agentcore_region: str | None = None

    # --- Logging ---
    log_level: str = "INFO"
    log_json: bool = False

    @property
    def environment_metadata(self) -> dict[str, object]:
        """Return safe, non-secret environment metadata for capability APIs."""
        return {
            "name": self.environment.value,
            "namespace": self.environment_namespace,
            "database_isolated": True,
            "object_storage_backend": self.object_storage_backend,
            "object_storage_namespace": self.object_storage_namespace,
            "secrets_backend": self.secrets_backend,
            "secrets_namespace": self.secrets_namespace,
            "auth_configured": bool(self.auth_issuer or self.cognito_user_pool_id),
            "logging_sink": self.logging_sink,
            "logging_namespace": self.logging_namespace,
            "retention_days": self.retention_days,
            "backup_enabled": self.backup_enabled,
            "restore_enabled": self.restore_enabled,
        }

    @field_validator(
        "retention_days",
        "ctms_operational_retention_days",
        "ctms_projection_retention_days",
        "ctms_event_attempt_retention_days",
        "ctms_event_log_retention_days",
        "ctms_failed_event_retention_days",
        "ctms_conflict_retention_days",
        "ctms_export_retention_days",
        "ctms_attachment_retention_days",
        "ctms_notification_retention_days",
        "ctms_audit_retention_days",
        "ctms_queue_capacity",
        "ctms_coordination_max_attempts",
        "ctms_coordination_backoff_base_seconds",
        "ctms_coordination_backoff_max_seconds",
        "ctms_projection_lag_warning_seconds",
        "ctms_retention_batch_size",
    )
    @classmethod
    def validate_positive_settings(cls, value: int | None) -> int | None:
        """Reject unsafe zero/negative retention and queue settings."""
        if value is not None and value <= 0:
            raise ValueError("retention and CTMS capacity settings must be positive")
        return value

    @field_validator("environment_namespace", "secrets_namespace", "logging_namespace")
    @classmethod
    def validate_namespace(cls, value: str) -> str:
        """Keep isolation namespaces explicit and non-empty."""
        normalized = value.strip()
        if not normalized:
            raise ValueError("environment namespaces must not be empty")
        return normalized

    @field_validator("database_url", mode="before")
    @classmethod
    def validate_database_url(cls, v: str) -> str:
        """Ensure the database URL is provided."""
        if not v:
            raise ValueError("DATABASE_URL must be set")
        return v

    @property
    def is_production(self) -> bool:
        return self.environment == Environment.PRODUCTION

    @property
    def is_testing(self) -> bool:
        return self.environment == Environment.TEST


@lru_cache
def get_settings() -> Settings:
    """Singleton-cached settings instance."""
    return Settings()
