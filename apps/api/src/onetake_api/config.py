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
    mock_recognition_mode: str = "success"
    dashscope_api_key: str = ""
    image_edit_model: str = "qwen-image-edit-plus"
    image_edit_endpoint: str = "https://dashscope.aliyuncs.com/api/v1/services/aigc/multimodal-generation/generation"
    script_model: str = "qwen-vl-plus"
    script_endpoint: str = "https://dashscope.aliyuncs.com/api/v1/services/aigc/multimodal-generation/generation"
    photoroom_api_key: str = ""
    photoroom_endpoint: str = "https://sdk.photoroom.com/v1/segment"
    project_ttl_hours: int = 24

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
