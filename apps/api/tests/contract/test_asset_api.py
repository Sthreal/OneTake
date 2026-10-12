from __future__ import annotations

from datetime import UTC, datetime, timedelta
from hashlib import sha256
from io import BytesIO

import httpx
from PIL import Image
from sqlalchemy import select
from sqlalchemy.orm import Session

from onetake_api.modules.asset.adapters.sqlalchemy_repository import (
    AssetModel,
    SqlAlchemyAssetRepository,
)
from onetake_api.modules.asset.application.service import PRESIGN_EXPIRES_SECONDS
from onetake_api.modules.asset.domain.model import create_pending_asset
from onetake_api.modules.outbox.adapters.sqlalchemy_repository import OutboxEventModel


def _png_bytes(width: int = 600, height: int = 600, color: tuple[int, int, int] = (240, 90, 30)) -> bytes:
    stream = BytesIO()
    Image.new("RGB", (width, height), color).save(stream, format="PNG")
    return stream.getvalue()


def _create_project(client, name: str = "素材项目") -> str:
    response = client.post("/api/v1/projects", json={"product_name": name})
    assert response.status_code == 201
    return response.json()["data"]["project_id"]


def _metadata(content: bytes, width: int = 600, height: int = 600) -> dict[str, object]:
    return {
        "original_filename": "product.png",
        "mime_type": "image/png",
        "size_bytes": len(content),
        "width": width,
        "height": height,
        "sha256": sha256(content).hexdigest(),
    }


def _presign_and_upload(client, project_id: str, content: bytes) -> dict[str, object]:
    presign = client.post(
        f"/api/v1/projects/{project_id}/assets/presign",
        json=_metadata(content),
    )
    assert presign.status_code == 201
    payload = presign.json()["data"]
    upload = httpx.put(
        payload["upload_url"],
        content=content,
        headers={"Content-Type": "image/png"},
        timeout=10,
    )
    assert upload.status_code == 200
    return payload


def test_presign_upload_complete_and_list(client, db_session: Session) -> None:
    project_id = _create_project(client)
    content = _png_bytes()
    payload = _presign_and_upload(client, project_id, content)

    complete = client.post(
        f"/api/v1/projects/{project_id}/assets/{payload['asset_id']}/complete",
        json=_metadata(content),
    )
    assert complete.status_code == 200
    data = complete.json()["data"]
    assert data["status"] == "ready"
    assert data["sha256"] == sha256(content).hexdigest()

    listing = client.get(f"/api/v1/projects/{project_id}/assets")
    assert listing.status_code == 200
    assert [item["asset_id"] for item in listing.json()["data"]] == [payload["asset_id"]]

    event = db_session.scalar(
        select(OutboxEventModel).where(OutboxEventModel.aggregate_id == payload["asset_id"])
    )
    assert event is not None
    assert event.event_name == "AssetRegistered"
    assert event.status == "pending"


def test_presign_missing_project(client) -> None:
    content = _png_bytes()
    response = client.post(
        "/api/v1/projects/prj_missing/assets/presign",
        json=_metadata(content),
    )
    assert response.status_code == 404


def test_presign_rejects_unsupported_mime(client) -> None:
    project_id = _create_project(client)
    response = client.post(
        f"/api/v1/projects/{project_id}/assets/presign",
        json={
            "original_filename": "product.gif",
            "mime_type": "image/gif",
            "size_bytes": 1024,
            "width": 600,
            "height": 600,
        },
    )
    assert response.status_code == 422


def test_presign_rejects_large_file(client) -> None:
    project_id = _create_project(client)
    response = client.post(
        f"/api/v1/projects/{project_id}/assets/presign",
        json={
            "original_filename": "large.png",
            "mime_type": "image/png",
            "size_bytes": 10 * 1024 * 1024 + 1,
            "width": 600,
            "height": 600,
        },
    )
    assert response.status_code == 422


def test_presign_rejects_invalid_dimensions(client) -> None:
    project_id = _create_project(client)
    response = client.post(
        f"/api/v1/projects/{project_id}/assets/presign",
        json={
            "original_filename": "small.png",
            "mime_type": "image/png",
            "size_bytes": 1024,
            "width": 100,
            "height": 600,
        },
    )
    assert response.status_code == 422


def test_complete_before_upload_conflicts(client) -> None:
    project_id = _create_project(client)
    content = _png_bytes()
    presign = client.post(
        f"/api/v1/projects/{project_id}/assets/presign",
        json=_metadata(content),
    )
    asset_id = presign.json()["data"]["asset_id"]
    complete = client.post(
        f"/api/v1/projects/{project_id}/assets/{asset_id}/complete",
        json=_metadata(content),
    )
    assert complete.status_code == 409
    assert complete.json()["error"]["code"] == "ASSET_NOT_UPLOADED"


def test_duplicate_image_is_rejected(client) -> None:
    project_id = _create_project(client)
    content = _png_bytes(color=(10, 20, 30))
    payload = _presign_and_upload(client, project_id, content)
    metadata = _metadata(content)
    complete = client.post(
        f"/api/v1/projects/{project_id}/assets/{payload['asset_id']}/complete",
        json=metadata,
    )
    assert complete.status_code == 200

    duplicate = client.post(
        f"/api/v1/projects/{project_id}/assets/presign",
        json=metadata,
    )
    assert duplicate.status_code == 409
    assert duplicate.json()["error"]["code"] == "ASSET_DUPLICATE"


def test_sixth_asset_is_rejected(client) -> None:
    project_id = _create_project(client)
    for index in range(5):
        response = client.post(
            f"/api/v1/projects/{project_id}/assets/presign",
            json={
                "original_filename": f"product-{index}.png",
                "mime_type": "image/png",
                "size_bytes": 1024 + index,
                "width": 600,
                "height": 600,
            },
        )
        assert response.status_code == 201

    sixth = client.post(
        f"/api/v1/projects/{project_id}/assets/presign",
        json={
            "original_filename": "product-6.png",
            "mime_type": "image/png",
            "size_bytes": 1024,
            "width": 600,
            "height": 600,
        },
    )
    assert sixth.status_code == 422


def test_asset_list_is_project_scoped(client, db_session: Session) -> None:
    first_project = _create_project(client, "项目一")
    second_project = _create_project(client, "项目二")
    content = _png_bytes(color=(1, 2, 3))
    payload = _presign_and_upload(client, first_project, content)
    complete = client.post(
        f"/api/v1/projects/{first_project}/assets/{payload['asset_id']}/complete",
        json=_metadata(content),
    )
    assert complete.status_code == 200

    assert len(client.get(f"/api/v1/projects/{first_project}/assets").json()["data"]) == 1
    assert client.get(f"/api/v1/projects/{second_project}/assets").json()["data"] == []


def test_presign_is_idempotent_while_pending(client) -> None:
    """预签名成功后 PUT 失败：客户端带着同一个 sha256 重试，应复用原登记而不是报重复。"""
    project_id = _create_project(client)
    content = _png_bytes(color=(9, 40, 90))
    metadata = _metadata(content)

    first = client.post(f"/api/v1/projects/{project_id}/assets/presign", json=metadata)
    assert first.status_code == 201
    first_payload = first.json()["data"]

    # 模拟 PUT 到 MinIO 失败后的重试
    retry = client.post(f"/api/v1/projects/{project_id}/assets/presign", json=metadata)
    assert retry.status_code == 201
    retry_payload = retry.json()["data"]
    assert retry_payload["asset_id"] == first_payload["asset_id"]
    assert retry_payload["object_key"] == first_payload["object_key"]
    assert len(client.get(f"/api/v1/projects/{project_id}/assets").json()["data"]) == 1

    upload = httpx.put(
        retry_payload["upload_url"],
        content=content,
        headers={"Content-Type": "image/png"},
        timeout=10,
    )
    assert upload.status_code == 200
    complete = client.post(
        f"/api/v1/projects/{project_id}/assets/{retry_payload['asset_id']}/complete",
        json=metadata,
    )
    assert complete.status_code == 200
    assert complete.json()["data"]["status"] == "ready"


def test_retry_at_quota_reuses_the_pending_slot(client) -> None:
    """配额用满时，失败素材的重试仍应落在自己那一格上，而不是被配额挡回去。"""
    project_id = _create_project(client)
    for index in range(4):
        content = _png_bytes(color=(index + 1, 80, 160))
        payload = _presign_and_upload(client, project_id, content)
        complete = client.post(
            f"/api/v1/projects/{project_id}/assets/{payload['asset_id']}/complete",
            json=_metadata(content),
        )
        assert complete.status_code == 200

    pending_content = _png_bytes(color=(200, 30, 30))
    pending_metadata = _metadata(pending_content)
    presign = client.post(
        f"/api/v1/projects/{project_id}/assets/presign",
        json=pending_metadata,
    )
    assert presign.status_code == 201
    asset_id = presign.json()["data"]["asset_id"]

    # 此时项目里已有 5 条登记，重试必须命中复用分支而不是配额校验
    retry = client.post(
        f"/api/v1/projects/{project_id}/assets/presign",
        json=pending_metadata,
    )
    assert retry.status_code == 201
    assert retry.json()["data"]["asset_id"] == asset_id

    upload = httpx.put(
        retry.json()["data"]["upload_url"],
        content=pending_content,
        headers={"Content-Type": "image/png"},
        timeout=10,
    )
    assert upload.status_code == 200
    complete = client.post(
        f"/api/v1/projects/{project_id}/assets/{asset_id}/complete",
        json=pending_metadata,
    )
    assert complete.status_code == 200
    assert len(client.get(f"/api/v1/projects/{project_id}/assets").json()["data"]) == 5


def test_expired_pending_asset_releases_quota(client, db_session: Session) -> None:
    """过了预签名有效期仍未完成的登记会被回收，不再长期占着项目配额。"""
    project_id = _create_project(client)
    repository = SqlAlchemyAssetRepository()
    stale_at = datetime.now(UTC) - timedelta(seconds=PRESIGN_EXPIRES_SECONDS + 60)
    for index in range(5):
        repository.add(
            db_session,
            create_pending_asset(
                asset_id=f"ast_stale_{index}",
                project_id=project_id,
                object_key=f"projects/{project_id}/assets/ast_stale_{index}/original.png",
                original_filename=f"stale-{index}.png",
                mime_type="image/png",
                size_bytes=1024 + index,
                width=600,
                height=600,
                sha256=f"{index:064d}",
                now=stale_at,
            ),
        )
    db_session.flush()
    assert len(client.get(f"/api/v1/projects/{project_id}/assets").json()["data"]) == 5

    content = _png_bytes(color=(11, 22, 33))
    response = client.post(
        f"/api/v1/projects/{project_id}/assets/presign",
        json=_metadata(content),
    )
    assert response.status_code == 201
    remaining = client.get(f"/api/v1/projects/{project_id}/assets").json()["data"]
    assert [item["asset_id"] for item in remaining] == [response.json()["data"]["asset_id"]]
