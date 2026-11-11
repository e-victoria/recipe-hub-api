import os
from dataclasses import dataclass, field


def _split(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


@dataclass(frozen=True)
class Settings:
    # The Nuxt dev/preview server; override with a comma-separated list in production.
    cors_origins: list[str] = field(
        default_factory=lambda: _split(os.getenv("CORS_ORIGINS", "http://localhost:3000"))
    )
    # Required to use the database; see .env.example for the local value.
    database_url: str | None = field(default_factory=lambda: os.getenv("DATABASE_URL") or None)
    # How long a sign-in lasts before the user has to log in again.
    session_days: int = field(default_factory=lambda: int(os.getenv("SESSION_DAYS", "30")))
    s3_bucket: str = field(default_factory=lambda: os.getenv("S3_BUCKET", "recipe-hub-images"))
    s3_region: str = field(default_factory=lambda: os.getenv("S3_REGION", "us-east-1"))
    # Set for the local RustFS server; unset means AWS S3.
    # Credentials come from the standard AWS_* variables.
    s3_endpoint_url: str | None = field(default_factory=lambda: os.getenv("S3_ENDPOINT_URL"))
    # Unset turns the AI assistant off: its endpoints answer 503.
    anthropic_api_key: str | None = field(
        default_factory=lambda: os.getenv("ANTHROPIC_API_KEY") or None
    )
    ai_model: str = field(default_factory=lambda: os.getenv("AI_MODEL", "claude-opus-5-5"))


settings = Settings()
