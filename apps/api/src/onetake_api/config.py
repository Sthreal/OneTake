from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_env: str = "development"
    database_url: str = "postgresql+psycopg://onetake:onetake_dev_password@localhost:5432/onetake"
    redis_url: str = "redis://localhost:6379/0"
    minio_endpoint: str = "localhost:9000"
    minio_public_endpoint: str = "localhost:9000"
    minio_root_user: str = "onetake"
    minio_root_password: str = "onetake_dev_password"
    minio_bucket: str = "onetake-media"
    minio_secure: bool = False
    minio_region: str = "us-east-1"
    mock_providers: bool = True
    project_ttl_hours: int = 24

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()