from __future__ import annotations

from datetime import UTC, datetime
from hashlib import sha256
from io import BytesIO

from PIL import Image
from sqlalchemy.orm import Session

from onetake_api.integrations.object_storage.public import ObjectStoragePublicService
from onetake_api.modules.asset.adapters.sqlalchemy_repository import SqlAlchemyAssetRepository
from onetake_api.modules.asset.domain.model import ASSET_STATUS_READY, create_pending_asset
from onetake_api.modules.job.public import JobPublicService
from onetake_api.modules.main_image.service import MainImageApplicationService
from onetake_api.modules.pipeline.public import PipelinePublicService
from onetake_api.modules.project.public import ProjectPublicService
from onetake_api.modules.recognition.service import RecognitionService


class FakeQueue:
    def enqueue(self, *_args, **_kwargs):
        return None


def _product_png() -> bytes:
    image = Image.new("RGB", (900, 900), (255, 255, 255))
    product = Image.new("RGB", (360, 520), (235, 78, 54))
    image.paste(product, (270, 190))
    output = BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


def test_main_image_flow_success(
    db_session: Session,
    object_storage: ObjectStoragePublicService,
    monkeypatch,
) -> None:
    monkeypatch.setattr("onetake_api.modules.recognition.service.get_queue", lambda _name: FakeQueue())
    monkeypatch.setattr("onetake_api.modules.main_image.service.get_queue", lambda _name: FakeQueue())

    project = ProjectPublicService().create_project(db_session, product_name="主图项目", product_note=None)
    content = _product_png()
    now = datetime.now(UTC)
    asset = create_pending_asset(
        asset_id="ast_main_image",
        project_id=project.id,
        object_key=f"projects/{project.id}/assets/ast_main_image/original.png",
        original_filename="商品.png",
        mime_type="image/png",
        size_bytes=len(content),
        width=900,
        height=900,
        sha256=sha256(content).hexdigest(),
        now=now,
    )
    asset = asset.__class__(**{**asset.__dict__, "status": ASSET_STATUS_READY})
    SqlAlchemyAssetRepository().add(db_session, asset)
    object_storage.put_bytes(object_key=asset.object_key, content=content, mime_type="image/png")
    db_session.flush()

    recognition = RecognitionService()
    run = recognition.request(db_session, project.id)
    recognition_job = JobPublicService().find_active(db_session, project.id, "recognition")
    assert recognition_job is not None
    recognition.process_job(db_session, recognition_job.id)
    _, candidates = recognition.latest(db_session, project.id)
    recognition.confirm(db_session, project.id, run.id, candidates[0].id)

    service = MainImageApplicationService(storage=object_storage)
    queued = service.request(db_session, project.id)
    assert queued.version.status == "queued"
    assert PipelinePublicService().get_or_create(db_session, project.id).status == "main_image_queued"

    image_edit_job = JobPublicService().find_active(db_session, project.id, "image_edit")
    assert image_edit_job is not None
    service.process_image_edit_job(db_session, image_edit_job.id)

    matting_job = JobPublicService().find_active(db_session, project.id, "matting")
    assert matting_job is not None
    service.process_matting_job(db_session, matting_job.id)

    finalize_job = JobPublicService().find_active(db_session, project.id, "main_image")
    assert finalize_job is not None
    ready = service.process_finalize_job(db_session, finalize_job.id)
    assert ready.status == "ready"
    assert ready.png_width == 2000
    assert ready.png_height == 2000
    assert ready.jpg_width == 1000
    assert ready.jpg_height == 1000
    assert ready.jpg_size_bytes is not None and ready.jpg_size_bytes <= 3 * 1024 * 1024
    assert ready.product_ratio is not None and 0.8 <= ready.product_ratio <= 0.85
    assert PipelinePublicService().get_or_create(db_session, project.id).status == "main_image_ready"

    view = service.latest(db_session, project.id)
    assert view is not None
    assert view.png_url is not None
    assert view.jpg_url is not None

    confirmed = service.confirm(db_session, project.id)
    assert confirmed.version.status == "confirmed"
    assert PipelinePublicService().get_or_create(db_session, project.id).status == "main_image_confirmed"
