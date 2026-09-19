from functools import lru_cache
from typing import Literal

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
    recognition_provider: Literal["mock", "real"] = "mock"
    image_edit_provider: Literal["mock", "real"] = "mock"
    matting_provider: Literal["mock", "real", "aliyun"] = "mock"
    script_provider: Literal["mock", "real"] = "mock"
    voice_provider: Literal["mock", "real"] = "mock"
    composition_provider: Literal["mock", "shotstack"] = "mock"
    creative_planner_provider: Literal["rules", "qwen"] = "rules"
    wan_i2v_provider: Literal["mock", "real"] = "mock"
    product_scene_enabled: bool = False
    content_qa_provider: Literal["rules", "qwen"] = "rules"
    recognition_model: str = "qwen-vl-plus"
    recognition_endpoint: str = "https://dashscope.aliyuncs.com/api/v1/services/aigc/multimodal-generation/generation"
    dashscope_api_key: str = ""
    image_edit_model: str = "qwen-image-edit-plus"
    image_edit_endpoint: str = "https://dashscope.aliyuncs.com/api/v1/services/aigc/multimodal-generation/generation"
    script_model: str = "qwen-vl-plus"
    script_endpoint: str = "https://dashscope.aliyuncs.com/api/v1/services/aigc/multimodal-generation/generation"
    voice_model: str = "cosyvoice-v2"
    photoroom_api_key: str = ""
    photoroom_endpoint: str = "https://sdk.photoroom.com/v1/segment"
    shotstack_api_key: str = ""
    shotstack_env: Literal["stage", "v1"] = "stage"
    shotstack_api_base: str = "https://api.shotstack.io"
    shotstack_poll_interval_seconds: float = 2.0
    shotstack_poll_timeout_seconds: int = 600
    shotstack_max_retries: int = 3
    shotstack_retry_backoff_seconds: float = 2.0
    creative_planner_model: str = "qwen-plus"
    creative_planner_endpoint: str = "https://dashscope.aliyuncs.com/api/v1/services/aigc/text-generation/generation"
    content_qa_model: str = "qwen-vl-plus"
    content_qa_endpoint: str = "https://dashscope.aliyuncs.com/api/v1/services/aigc/multimodal-generation/generation"
    content_qa_frame_count: int = 5
    wan_i2v_model: str = ""
    wan_i2v_resolution: Literal["720P", "1080P"] = "720P"
    wan_i2v_with_audio: bool = False
    wan_i2v_max_seconds: int = 5
    alibaba_cloud_access_key_id: str = ""
    alibaba_cloud_access_key_secret: str = ""
    alibaba_cloud_region_id: str = "cn-shanghai"
    aliyun_imageseg_endpoint: str = "imageseg.cn-shanghai.aliyuncs.com"
    project_ttl_hours: int = 24

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
