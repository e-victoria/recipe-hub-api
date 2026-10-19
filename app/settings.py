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
    s3_bucket: str = field(default_factory=lambda: os.getenv("S3_BUCKET", "recipe-hub-images"))
    s3_region: str = field(default_factory=lambda: os.getenv("S3_REGION", "us-east-1"))
    # Set for the local RustFS server; unset means AWS S3.
    # Credentials come from the standard AWS_* variables.
    s3_endpoint_url: str | None = field(default_factory=lambda: os.getenv("S3_ENDPOINT_URL"))


settings = Settings()
