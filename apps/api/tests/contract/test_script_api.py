from datetime import UTC, datetime
from io import BytesIO

from PIL import Image
from sqlalchemy.orm import Session

from onetake_api.integrations.object_storage.public import ObjectStoragePublicService
from onetake_api.modules.job.public import JobPublicService
from onetake_api.modules.main_image.domain import MainImageVersion
from onetake_api.modules.main_image.repository import MainImageRepository
from onetake_api.modules.pipeline.public import PipelinePublicService
from onetake_api.modules.project.public import ProjectPublicService
from onetake_api.modules.script.service import ScriptApplicationService


class FakeQueue:
    def enqueue(self, *_args, **_kwargs):
        return None


def _seed_confirmed_main_image(session: Session, storage: ObjectStoragePublicService) -> str:
    project = ProjectPublicService().create_project(session, product_name="文案接口商品", product_note=None)
    key = f"projects/{project.id}/main-image/test/main-2000.png"
    output = BytesIO()
    Image.new("RGBA", (300, 300), (255, 255, 255, 0)).save(output, format="PNG")
    storage.put_bytes(object_key=key, content=output.getvalue(), mime_type="image/png")
    now = datetime.now(UTC)
    MainImageRepository().add(
        session,
        MainImageVersion(
            id="miv_script_api",
            project_id=project.id,
            source_asset_id="ast_script_api",
            status="confirmed",
            image_edit_run_id="edt_script_api",
            matting_run_id="mat_script_api",
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


def test_script_requires_confirmed_main_image(client) -> None:
    project = client.post("/api/v1/projects", json={"product_name": "文案前置"}).json()["data"]
    response = client.post(
        f"/api/v1/projects/{project['project_id']}/script/generate",
        json={"pain_point": "清洗麻烦", "selling_points": ["杯身可拆卸"], "usage_scenario": "通勤"},
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "SCRIPT_CONFLICT"


def test_script_get_empty_state(client) -> None:
    project = client.post("/api/v1/projects", json={"product_name": "文案空状态"}).json()["data"]
    response = client.get(f"/api/v1/projects/{project['project_id']}/script")
    assert response.status_code == 200
    assert response.json()["data"]["version"] is None


def test_script_api_flow(client, db_session: Session, object_storage: ObjectStoragePublicService, monkeypatch) -> None:
    monkeypatch.setattr("onetake_api.modules.script.service.get_queue", lambda _name: FakeQueue())
    project_id = _seed_confirmed_main_image(db_session, object_storage)
    response = client.post(
        f"/api/v1/projects/{project_id}/script/generate",
        json={
            "pain_point": "清洗麻烦",
            "selling_points": ["杯身可拆卸", "适合随身携带"],
            "usage_scenario": "通勤和办公室",
            "offer": None,
        },
    )
    assert response.status_code == 202
    assert response.json()["data"]["version"]["status"] == "queued"

    job = JobPublicService().find_active(db_session, project_id, "script")
    assert job is not None
    ScriptApplicationService(storage=object_storage).process_job(db_session, job.id)

    ready = client.get(f"/api/v1/projects/{project_id}/script").json()["data"]["version"]
    assert ready["status"] == "ready"
    assert ready["provider"] == "mock-qwen-vl-plus"

    edited = client.patch(
        f"/api/v1/projects/{project_id}/script",
        json={"cta": "想确认这些已经写明的特点，现在就来进一步看看。"},
    )
    assert edited.status_code == 200
    assert edited.json()["data"]["version"]["status"] == "ready"

    confirmed = client.post(f"/api/v1/projects/{project_id}/script/confirm")
    assert confirmed.status_code == 200
    assert confirmed.json()["data"]["version"]["status"] == "confirmed"
