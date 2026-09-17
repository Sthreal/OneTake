from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from onetake_api.modules.outbox.adapters.sqlalchemy_repository import OutboxEventModel
from onetake_api.modules.project.adapters.sqlalchemy_repository import ProjectModel


def test_create_project_api(client) -> None:
    response = client.post(
        "/api/v1/projects",
        json={
            "product_name": "便携式榨汁杯",
            "product_note": "白色杯身",
        },
    )
    assert response.status_code == 201
    body = response.json()
    assert body["data"]["project_id"].startswith("prj_")
    assert body["data"]["status"] == "draft"
    assert body["request_id"].startswith("req_")
    assert response.headers["X-Request-ID"] == body["request_id"]


def test_get_project_api(client) -> None:
    created = client.post(
        "/api/v1/projects",
        json={"product_name": "便携式榨汁杯"},
    ).json()["data"]

    response = client.get(f"/api/v1/projects/{created['project_id']}")
    assert response.status_code == 200
    assert response.json()["data"]["project_id"] == created["project_id"]


def test_get_missing_project_api(client) -> None:
    response = client.get("/api/v1/projects/prj_missing")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "PROJECT_NOT_FOUND"


def test_empty_product_name_is_rejected(client, db_session: Session) -> None:
    before = db_session.query(ProjectModel).count()
    response = client.post("/api/v1/projects", json={"product_name": "   "})
    assert response.status_code == 422
    assert db_session.query(ProjectModel).count() == before


def test_long_product_note_is_rejected(client) -> None:
    response = client.post(
        "/api/v1/projects",
        json={"product_name": "榨汁杯", "product_note": "a" * 241},
    )
    assert response.status_code == 422


def test_project_created_event_exists(client, db_session: Session) -> None:
    project_id = client.post(
        "/api/v1/projects",
        json={"product_name": "事件项目"},
    ).json()["data"]["project_id"]

    event = db_session.scalar(
        select(OutboxEventModel).where(OutboxEventModel.aggregate_id == project_id)
    )
    assert event is not None
    assert event.event_name == "ProjectCreated"
    assert event.event_version == 1
    assert event.status == "pending"