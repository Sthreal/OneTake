"""切片 B 契约：一次 generate ≥3 候选，select 后 latest 切换，旧客户端默认角 0。"""
from datetime import UTC, datetime
from io import BytesIO

import pytest
from PIL import Image
from sqlalchemy.orm import Session

from onetake_api.integrations.object_storage.public import ObjectStoragePublicService
from onetake_api.modules.content_plan.service import ContentPlanApplicationService, ContentPlanConflictError
from onetake_api.modules.job.public import JobPublicService
from onetake_api.modules.main_image.domain import MainImageVersion
from onetake_api.modules.main_image.repository import MainImageRepository
from onetake_api.modules.pipeline.public import PipelinePublicService
from onetake_api.modules.project.public import ProjectPublicService
from onetake_api.modules.script.repository import ScriptRepository
from onetake_api.modules.script.service import ScriptApplicationService, ScriptConflictError


class FakeQueue:
    def enqueue(self, *_args, **_kwargs):
        return None


def _seed(session: Session, storage: ObjectStoragePublicService) -> str:
    project = ProjectPublicService().create_project(session, product_name="文案角度商品", product_note=None)
    key = f"projects/{project.id}/main-image/test/main-2000.png"
    output = BytesIO()
    Image.new("RGBA", (300, 300), (255, 255, 255, 0)).save(output, format="PNG")
    storage.put_bytes(object_key=key, content=output.getvalue(), mime_type="image/png")
    now = datetime.now(UTC)
    MainImageRepository().add(
        session,
        MainImageVersion(
            id=f"miv_{project.id[-12:]}",
            project_id=project.id,
            source_asset_id=f"ast_{project.id[-12:]}",
            status="confirmed",
            image_edit_run_id="edt_angles",
            matting_run_id="mat_angles",
            transparent_object_key=key,
            jpg_object_key=None,
            png_width=2000,
            png_height=2000,
            jpg_width=1000,
            jpg_height=1000,
            jpg_size_bytes=1000,
            product_ratio=0.82,
            error_code=None,
            created_at=now,
            updated_at=now,
            completed_at=now,
            confirmed_at=now,
        ),
    )
    PipelinePublicService().mark_main_image_confirmed(session, project.id)
    session.flush()
    return project.id


def _payload() -> dict:
    return {
        "pain_point": "清洗麻烦",
        "selling_points": ["杯身可拆卸", "适合随身携带"],
        "usage_scenario": "通勤和办公室",
        "offer": None,
    }


def _generate_ready(client, db_session, object_storage, monkeypatch) -> tuple[str, dict]:
    monkeypatch.setattr("onetake_api.modules.script.service.get_queue", lambda _name: FakeQueue())
    project_id = _seed(db_session, object_storage)
    created = client.post(f"/api/v1/projects/{project_id}/script/generate", json=_payload())
    assert created.status_code == 202
    job = JobPublicService().find_active(db_session, project_id, "script")
    assert job is not None
    ScriptApplicationService(storage=object_storage).process_job(db_session, job.id)
    body = client.get(f"/api/v1/projects/{project_id}/script").json()["data"]
    return project_id, body


def test_generate_returns_three_candidates_and_defaults_to_angle_zero(
    client, db_session: Session, object_storage: ObjectStoragePublicService, monkeypatch
) -> None:
    monkeypatch.setattr("onetake_api.modules.script.service.get_queue", lambda _name: FakeQueue())
    project_id = _seed(db_session, object_storage)
    created = client.post(f"/api/v1/projects/{project_id}/script/generate", json=_payload())
    assert created.status_code == 202
    queued = created.json()["data"]
    assert len(queued["candidates"]) >= 3
    assert [item["angle"] for item in queued["candidates"][:3]] == ["pain_point", "scene", "comparison"]
    assert queued["version"]["version_id"] == queued["candidates"][0]["version_id"]
    assert queued["selected_version_id"] == queued["version"]["version_id"]
    assert queued["version"]["angle"] == "pain_point"
    assert queued["version"]["version_number"] == min(item["version_number"] for item in queued["candidates"])
    assert len(ScriptRepository().list_for_project(db_session, project_id)) == 3

    again = client.post(f"/api/v1/projects/{project_id}/script/generate", json=_payload())
    assert again.status_code == 202
    assert again.json()["data"]["version"]["version_id"] == queued["version"]["version_id"]
    assert len(ScriptRepository().list_for_project(db_session, project_id)) == 3

    job = JobPublicService().find_active(db_session, project_id, "script")
    assert job is not None
    ScriptApplicationService(storage=object_storage).process_job(db_session, job.id)
    ready = client.get(f"/api/v1/projects/{project_id}/script").json()["data"]
    assert ready["version"]["status"] == "ready"
    assert ready["version"]["angle"] == "pain_point"
    assert ready["version"]["version_id"] == ready["candidates"][0]["version_id"]
    hooks = [item["hook"] for item in ready["candidates"]]
    scenarios = [item["usage_scenario"] for item in ready["candidates"]]
    assert len(set(hooks)) == 3
    assert len(set(scenarios)) == 3
    assert all(45 <= item["character_count"] <= 72 for item in ready["candidates"])
    assert [item["selected"] for item in ready["candidates"]] == [True, False, False]

    PipelinePublicService().mark_audio_subtitle_confirmed(db_session, project_id)
    with pytest.raises(ContentPlanConflictError, match="文案尚未确认"):
        ContentPlanApplicationService().generate(db_session, project_id)

    confirmed = client.post(f"/api/v1/projects/{project_id}/script/confirm")
    assert confirmed.status_code == 200
    confirmed_body = confirmed.json()["data"]
    assert confirmed_body["version"]["status"] == "confirmed"
    assert confirmed_body["version"]["angle"] == "pain_point"
    assert [item["status"] for item in confirmed_body["candidates"]] == ["confirmed", "ready", "ready"]

    PipelinePublicService().mark_audio_subtitle_confirmed(db_session, project_id)
    with pytest.raises(ContentPlanConflictError, match="字幕尚未确认"):
        ContentPlanApplicationService().generate(db_session, project_id)
    assert ContentPlanApplicationService().latest(db_session, project_id) is None


def test_select_makes_that_angle_latest_and_only_it_can_be_confirmed(
    client, db_session: Session, object_storage: ObjectStoragePublicService, monkeypatch
) -> None:
    project_id, ready = _generate_ready(client, db_session, object_storage, monkeypatch)
    comparison = next(item for item in ready["candidates"] if item["angle"] == "comparison")
    selected = client.post(
        f"/api/v1/projects/{project_id}/script/select",
        json={"version_id": comparison["version_id"]},
    )
    assert selected.status_code == 200
    body = selected.json()["data"]
    assert body["selected_version_id"] == comparison["version_id"]
    assert body["version"]["angle"] == "comparison"
    assert body["version"]["angle_label"] == "对比测评"
    assert body["version"]["version_id"] != ready["candidates"][0]["version_id"]

    latest = client.get(f"/api/v1/projects/{project_id}/script").json()["data"]
    assert latest["version"]["version_id"] == comparison["version_id"]
    assert latest["version"]["angle"] == "comparison"

    confirmed = client.post(f"/api/v1/projects/{project_id}/script/confirm")
    assert confirmed.status_code == 200
    confirmed_body = confirmed.json()["data"]
    assert confirmed_body["version"]["version_id"] == comparison["version_id"]
    assert confirmed_body["version"]["status"] == "confirmed"
    statuses = {item["angle"]: item["status"] for item in confirmed_body["candidates"]}
    assert statuses == {"pain_point": "ready", "scene": "ready", "comparison": "confirmed"}

    blocked = client.post(
        f"/api/v1/projects/{project_id}/script/select",
        json={"version_id": ready["candidates"][0]["version_id"]},
    )
    assert blocked.status_code == 409
    assert blocked.json()["error"]["code"] == "SCRIPT_CONFLICT"

    PipelinePublicService().mark_audio_subtitle_confirmed(db_session, project_id)
    with pytest.raises(ContentPlanConflictError, match="字幕尚未确认"):
        ContentPlanApplicationService().generate(db_session, project_id)
    assert ContentPlanApplicationService().latest(db_session, project_id) is None


def test_confirm_rejects_a_non_selected_candidate(
    client, db_session: Session, object_storage: ObjectStoragePublicService, monkeypatch
) -> None:
    project_id, ready = _generate_ready(client, db_session, object_storage, monkeypatch)
    scene = next(item for item in ready["candidates"] if item["angle"] == "scene")
    service = ScriptApplicationService(storage=object_storage)
    scene_version = ScriptRepository().get(db_session, scene["version_id"])
    assert scene_version is not None

    def _unselected_latest(_session, _project_id):
        return scene_version

    monkeypatch.setattr(service._repository, "latest", _unselected_latest)
    with pytest.raises(ScriptConflictError, match="只能确认当前选中的文案角度"):
        service.confirm(db_session, project_id)


def test_select_unknown_version_is_not_found(
    client, db_session: Session, object_storage: ObjectStoragePublicService, monkeypatch
) -> None:
    project_id, _ready = _generate_ready(client, db_session, object_storage, monkeypatch)
    missing = client.post(
        f"/api/v1/projects/{project_id}/script/select",
        json={"version_id": "scr_missing"},
    )
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "SCRIPT_NOT_FOUND"


def test_second_generate_after_ready_starts_a_new_batch(
    client, db_session: Session, object_storage: ObjectStoragePublicService, monkeypatch
) -> None:
    monkeypatch.setattr("onetake_api.modules.script.service.get_queue", lambda _name: FakeQueue())
    project_id, ready = _generate_ready(client, db_session, object_storage, monkeypatch)
    second = client.post(f"/api/v1/projects/{project_id}/script/generate", json=_payload())
    assert second.status_code == 202
    body = second.json()["data"]
    assert body["version"]["version_id"] != ready["version"]["version_id"]
    assert body["version"]["angle"] == "pain_point"
    assert len(ScriptRepository().list_for_project(db_session, project_id)) == 6
    assert body["version"]["version_number"] == min(item["version_number"] for item in body["candidates"])
