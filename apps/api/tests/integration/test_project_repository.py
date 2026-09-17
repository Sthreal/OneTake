from __future__ import annotations

from sqlalchemy.orm import Session

from onetake_api.modules.project.public import ProjectPublicService


def test_create_and_get_project(db_session: Session) -> None:
    service = ProjectPublicService()
    created = service.create_project(
        db_session,
        product_name="便携式榨汁杯",
        product_note="白色杯身",
    )
    loaded = service.get_project(db_session, project_id=created.id)
    assert loaded.id == created.id
    assert loaded.product_name == "便携式榨汁杯"
    assert loaded.product_note == "白色杯身"
    assert loaded.status == "draft"
    assert created.id.startswith("prj_")

def test_list_projects_returns_newest_first(db_session: Session) -> None:
    service = ProjectPublicService()
    first = service.create_project(db_session, product_name="项目一", product_note=None)
    second = service.create_project(db_session, product_name="项目二", product_note=None)

    items = service.list_projects(db_session, limit=2)
    assert [item.id for item in items] == [second.id, first.id]


def test_update_project_and_write_event(db_session: Session) -> None:
    service = ProjectPublicService()
    project = service.create_project(db_session, product_name="旧名称", product_note="旧说明")
    updated = service.update_project(
        db_session,
        project_id=project.id,
        product_name="新名称",
        product_note="新说明",
        update_product_note=True,
    )
    assert updated.product_name == "新名称"
    assert updated.product_note == "新说明"
    assert updated.updated_at >= project.updated_at
