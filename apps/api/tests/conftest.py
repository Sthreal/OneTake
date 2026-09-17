from __future__ import annotations

from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from minio import Minio
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from onetake_api.config import get_settings
from onetake_api.integrations.object_storage.dependencies import get_object_storage
from onetake_api.integrations.object_storage.minio_storage import MinioAssetStorage
from onetake_api.integrations.object_storage.public import ObjectStoragePublicService
from onetake_api.main import app
from onetake_api.platform.database import get_session


@pytest.fixture
def db_session() -> Generator[Session, None, None]:
    engine = create_engine(get_settings().database_url, pool_pre_ping=True)
    connection = engine.connect()
    transaction = connection.begin()
    session = Session(bind=connection, expire_on_commit=False, join_transaction_mode="create_savepoint")
    try:
        yield session
    finally:
        session.close()
        transaction.rollback()
        connection.close()
        engine.dispose()


@pytest.fixture
def minio_client() -> Minio:
    settings = get_settings()
    return Minio(
        settings.minio_endpoint,
        access_key=settings.minio_root_user,
        secret_key=settings.minio_root_password,
        secure=settings.minio_secure,
    )


@pytest.fixture
def object_storage(minio_client: Minio) -> ObjectStoragePublicService:
    settings = get_settings()
    return ObjectStoragePublicService(
        MinioAssetStorage(
            internal_client=minio_client,
            public_client=minio_client,
            bucket=settings.minio_bucket,
        )
    )


@pytest.fixture
def client(
    db_session: Session,
    object_storage: ObjectStoragePublicService,
) -> Generator[TestClient, None, None]:
    def override_get_session() -> Generator[Session, None, None]:
        yield db_session

    app.dependency_overrides[get_session] = override_get_session
    app.dependency_overrides[get_object_storage] = lambda: object_storage
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()