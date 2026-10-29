"""壳层出稿前奏：只把识别和主图确认掉，不生成文案，也不要求打开自动链。

MOCK_PROVIDERS=true（conftest）下就地跑完。文案闸「请先确认主图，再生成文案」
在前奏之前会挡住，前奏之后同一请求可以入队。
"""
from __future__ import annotations

from datetime import UTC, datetime
from hashlib import sha256
from io import BytesIO

import pytest
from PIL import Image
from sqlalchemy.orm import Session

from onetake_api.config import get_settings
from onetake_api.integrations.object_storage.public import ObjectStoragePublicService
from onetake_api.modules.asset.adapters.sqlalchemy_repository import SqlAlchemyAssetRepository
from onetake_api.modules.asset.domain.model import ASSET_STATUS_READY, create_pending_asset
from onetake_api.modules.pipeline.orchestrator import PipelineOrchestrator
from onetake_api.modules.project.public import ProjectPublicService
from onetake_api.modules.recognition.service import RecognitionValidationError
from onetake_api.modules.script.public import ScriptPublicService
from onetake_api.modules.script.service import ScriptConflictError


class FakeQueue:
    def enqueue(self, *_args, **_kwargs):
        return None


_QUEUE_MODULES = (
    "onetake_api.modules.recognition.service",
    "onetake_api.modules.main_image.service",
    "onetake_api.modules.script.service",
    "onetake_api.modules.voice.service",
    "onetake_api.modules.subtitle.api",
)


def _patch_queues(monkeypatch) -> None:
    for module in _QUEUE_MODULES:
        monkeypatch.setattr(f"{module}.get_queue", lambda _name: FakeQueue())
    monkeypatch.setattr(
        "onetake_api.modules.pipeline.orchestrator._queue_has_worker",
        lambda: False,
    )


def _product_png() -> bytes:
    image = Image.new("RGB", (900, 900), (255, 255, 255))
    product = Image.new("RGB", (360, 520), (235, 78, 54))
    image.paste(product, (270, 190))
    output = BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


def _project_with_asset(session: Session, storage: ObjectStoragePublicService, name: str):
    project = ProjectPublicService().create_project(session, product_name=name, product_note="轻便")
    content = _product_png()
    now = datetime.now(UTC)
    asset = create_pending_asset(
        asset_id=f"ast_{project.id}",
        project_id=project.id,
        object_key=f"projects/{project.id}/assets/ast/original.png",
        original_filename="商品.png",
        mime_type="image/png",
        size_bytes=len(content),
        width=900,
        height=900,
        sha256=sha256(content).hexdigest(),
        now=now,
    )
    asset = asset.__class__(**{**asset.__dict__, "status": ASSET_STATUS_READY})
    SqlAlchemyAssetRepository().add(session, asset)
    storage.put_bytes(object_key=asset.object_key, content=content, mime_type="image/png")
    session.flush()
    return project


def _request_script(session: Session, project_id: str):
    return ScriptPublicService().request(
        session,
        project_id=project_id,
        pain_point="清洗麻烦",
        selling_points=["杯身可拆"],
        usage_scenario="通勤路上",
        offer=None,
    )


def test_prelude_confirms_main_image_without_auto_run_or_script(
    db_session: Session,
    object_storage: ObjectStoragePublicService,
    monkeypatch,
) -> None:
    monkeypatch.setenv("AUTO_RUN_ENABLED", "false")
    get_settings.cache_clear()
    _patch_queues(monkeypatch)
    assert get_settings().auto_run_enabled is False

    project = _project_with_asset(db_session, object_storage, "壳层前奏")
    with pytest.raises(ScriptConflictError, match="请先确认主图，再生成文案"):
        _request_script(db_session, project.id)

    view = PipelineOrchestrator().ensure_confirmed_main_image(db_session, project.id)
    assert view.version.status == "confirmed"
    assert ScriptPublicService().latest(db_session, project.id).version is None

    again = PipelineOrchestrator().ensure_confirmed_main_image(db_session, project.id)
    assert again.version.status == "confirmed"
    assert again.version.id == view.version.id

    script = _request_script(db_session, project.id)
    assert script.version is not None
    assert script.version.status in {"queued", "generating", "ready"}


def test_prelude_without_asset_does_not_invent_a_main_image(
    db_session: Session,
    monkeypatch,
) -> None:
    _patch_queues(monkeypatch)
    project = ProjectPublicService().create_project(db_session, product_name="没图", product_note=None)
    with pytest.raises(RecognitionValidationError, match="素材"):
        PipelineOrchestrator().ensure_confirmed_main_image(db_session, project.id)
