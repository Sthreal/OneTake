from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from minio import Minio
from redis import Redis
from sqlalchemy import text

from onetake_api.config import get_settings
from onetake_api.modules.asset.api import router as asset_router
from onetake_api.modules.job.api import router as job_router
from onetake_api.modules.main_image.api import router as main_image_router
from onetake_api.modules.pipeline.api import router as pipeline_router
from onetake_api.modules.project.api import router as project_router
from onetake_api.modules.provider.api import router as provider_router
from onetake_api.modules.provider.service import get_provider_statuses
from onetake_api.modules.recognition.api import router as recognition_router
from onetake_api.modules.script.api import router as script_router
from onetake_api.modules.voice.api import router as voice_router
from onetake_api.platform.database import engine
from onetake_api.platform.errors import register_error_handlers
from onetake_api.platform.logging import configure_logging, register_request_logging

configure_logging()
settings = get_settings()
app = FastAPI(
    title="One Take API",
    version="0.7.0",
    description="One Take 商品 AI 视频生成 MVP API",
)

register_request_logging(app)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
register_error_handlers(app)
app.include_router(project_router)
app.include_router(provider_router)
app.include_router(asset_router)
app.include_router(pipeline_router)
app.include_router(recognition_router)
app.include_router(main_image_router)
app.include_router(script_router)
app.include_router(voice_router)
app.include_router(job_router)


def check_postgres() -> tuple[bool, str]:
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        return True, "ok"
    except Exception as exc:
        return False, exc.__class__.__name__


def check_redis() -> tuple[bool, str]:
    try:
        client = Redis.from_url(settings.redis_url, socket_connect_timeout=2)
        client.ping()
        return True, "ok"
    except Exception as exc:
        return False, exc.__class__.__name__


def check_minio() -> tuple[bool, str]:
    try:
        client = Minio(
            settings.minio_endpoint,
            access_key=settings.minio_root_user,
            secret_key=settings.minio_root_password,
            secure=settings.minio_secure,
        )
        exists = client.bucket_exists(settings.minio_bucket)
        return (True, "ok") if exists else (False, "bucket_missing")
    except Exception as exc:
        return False, exc.__class__.__name__


@app.get("/health")
@app.get("/api/health")
def health() -> JSONResponse:
    checks = {
        "postgres": check_postgres(),
        "redis": check_redis(),
        "minio": check_minio(),
    }
    services = {
        name: {"ok": result[0], "detail": result[1]}
        for name, result in checks.items()
    }
    is_ready = all(item["ok"] for item in services.values())
    return JSONResponse(
        status_code=200 if is_ready else 503,
        content={
            "status": "ok" if is_ready else "degraded",
            "stage": "m1-voice",
            "mock_providers": settings.mock_providers,
            "services": services,
        },
    )


@app.get("/api/info")
def info() -> dict[str, object]:
    return {
        "name": "One Take",
        "version": "0.7.0",
        "stage": "m1-voice",
        "architecture": "modular-monolith",
        "orchestration": "pipeline",
        "providers": {
            **{item.capability: item.effective_provider for item in get_provider_statuses()},
            "tts": "mock",
            "avatar_video": "mock",
            "product_video": "mock",
            "composition": "mock",
        },
    }
