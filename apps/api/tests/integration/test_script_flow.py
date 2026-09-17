from __future__ import annotations

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
from onetake_api.modules.script.content import ScriptGenerationError
from onetake_api.modules.script.service import ScriptApplicationService


class FakeQueue:
    def enqueue(self, *_args, **_kwargs):
        return None


class FailingScriptAdapter:
    provider_name = "mock-failing"
    model = "qwen-vl-plus"

    def generate(self, **_kwargs):
        raise ScriptGenerationError("模拟文案生成失败")


def _png() -> bytes:
    output = BytesIO()
    Image.new("RGBA", (300, 300), (255, 255, 255, 0)).save(output, format="PNG")
    return output.getvalue()


def _seed_confirmed_main_image(
    session: Session,
    object_storage: ObjectStoragePublicService,
) -> str:
    project = ProjectPublicService().create_project(session, product_name="便携榨汁杯", product_note="白色杯身")
    key = f"projects/{project.id}/main-image/test/main-2000.png"
    object_storage.put_bytes(object_key=key, content=_png(), mime_type="image/png")
    now = datetime.now(UTC)
    version = MainImageVersion(
        id="miv_script_test",
        project_id=project.id,
        source_asset_id="ast_script_test",
        status="confirmed",
        image_edit_run_id="edt_test",
        matting_run_id="mat_test",
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
    )
    MainImageRepository().add(session, version)
    PipelinePublicService().mark_main_image_confirmed(session, project.id)
    session.flush()
    return project.id


def test_script_flow_success_and_edit(
    db_session: Session,
    object_storage: ObjectStoragePublicService,
    monkeypatch,
) -> None:
    monkeypatch.setattr("onetake_api.modules.script.service.get_queue", lambda _name: FakeQueue())
    project_id = _seed_confirmed_main_image(db_session, object_storage)
    service = ScriptApplicationService(storage=object_storage)

    queued = service.request(
        db_session,
        project_id=project_id,
        pain_point="清洗麻烦",
        selling_points=["杯身可拆卸", "适合随身携带"],
        usage_scenario="通勤和办公室",
        offer=None,
    )
    assert queued.version is not None
    assert queued.version.status == "queued"

    job = JobPublicService().find_active(db_session, project_id, "script")
    assert job is not None
    ready = service.process_job(db_session, job.id)
    assert ready.status == "ready"
    assert 85 <= ready.character_count <= 120
    assert ready.full_text
    assert PipelinePublicService().get_or_create(db_session, project_id).status == "script_ready"

    edited = service.update(
        db_session,
        project_id=project_id,
        hook=ready.hook,
        pain_point=ready.pain_point,
        selling_points=ready.selling_points,
        usage_scenario=ready.usage_scenario,
        cta="想确认这些已经写明的特点，现在就来进一步看看。",
    )
    assert edited.version is not None
    assert edited.version.status == "ready"
    assert edited.version.full_text.endswith("看看。")

    confirmed = service.confirm(db_session, project_id)
    assert confirmed.version is not None
    assert confirmed.version.status == "confirmed"
    pipeline = PipelinePublicService().get_or_create(db_session, project_id)
    assert pipeline.status == "script_confirmed"
    assert pipeline.current_step == 4


def test_script_failure_does_not_mark_complete(
    db_session: Session,
    object_storage: ObjectStoragePublicService,
    monkeypatch,
) -> None:
    monkeypatch.setattr("onetake_api.modules.script.service.get_queue", lambda _name: FakeQueue())
    monkeypatch.setattr("onetake_api.modules.script.service._adapter", lambda: FailingScriptAdapter())
    project_id = _seed_confirmed_main_image(db_session, object_storage)
    service = ScriptApplicationService(storage=object_storage)

    service.request(
        db_session,
        project_id=project_id,
        pain_point="清洗麻烦",
        selling_points=["杯身可拆卸"],
        usage_scenario="通勤和办公室",
        offer=None,
    )
    job = JobPublicService().find_active(db_session, project_id, "script")
    assert job is not None
    failed = service.process_job(db_session, job.id)
    assert failed.status == "failed"
    assert failed.error_code == "SCRIPT_GENERATION_ERROR"
    assert PipelinePublicService().get_or_create(db_session, project_id).status == "failed"
