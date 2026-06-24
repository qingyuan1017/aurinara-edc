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
    database_url: PostgresDsn = "postgresql+asyncpg://postgres:postgres@localhost:5432/edc"  # type: ignore[assignment]
    database_echo: bool = False
    database_pool_size: int = 10
    database_max_overflow: int = 20

    # --- Security ---
    secret_key: str = "CHANGE-ME-IN-PRODUCTION"
    access_token_expire_minutes: int = 30
    refresh_token_expire_days: int = 7
    inactivity_timeout_minutes: int = 30

    # --- Optional: AWS Cognito / OIDC ---
    cognito_user_pool_id: str | None = None
    cognito_region: str | None = None
    cognito_app_client_id: str | None = None

    # --- Optional: Object Storage (S3) ---
    s3_bucket_name: str | None = None
    s3_region: str | None = None

    # --- Optional: Redis ---
    redis_url: str | None = None

    # --- Logging ---
    log_level: str = "INFO"
    log_json: bool = False

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
