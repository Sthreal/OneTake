from datetime import UTC, datetime

from sqlalchemy.orm import Session

from onetake_api.modules.asset.adapters.sqlalchemy_repository import SqlAlchemyAssetRepository
from onetake_api.modules.asset.domain.model import ASSET_STATUS_READY, create_pending_asset
from onetake_api.modules.job.public import JobPublicService
from onetake_api.modules.project.public import ProjectPublicService
from onetake_api.modules.recognition.service import RecognitionService


class FakeQueue:
    def enqueue(self, *_args, **_kwargs):
        return None


def test_recognition_flow_success(db_session: Session, monkeypatch) -> None:
    monkeypatch.setattr("onetake_api.modules.recognition.service.get_queue", lambda _name: FakeQueue())
    project = ProjectPublicService().create_project(db_session, product_name="榨汁杯", product_note=None)
    now = datetime.now(UTC)
    asset = create_pending_asset(
        asset_id="ast_recognition",
        project_id=project.id,
        object_key=f"projects/{project.id}/assets/ast_recognition/original.png",
        original_filename="榨汁杯.png",
        mime_type="image/png",
        size_bytes=1024,
        width=640,
        height=640,
        sha256="a" * 64,
        now=now,
    )
    asset = asset.__class__(**{**asset.__dict__, "status": ASSET_STATUS_READY})
    repository = SqlAlchemyAssetRepository()
    repository.add(db_session, asset)
    db_session.flush()

    service = RecognitionService()
    run = service.request(db_session, project.id)
    job = JobPublicService().find_active(db_session, project.id, "recognition")
    assert job is not None
    processed = service.process_job(db_session, job.id)
    assert processed.status == "ready"

    latest, candidates = service.latest(db_session, project.id)
    assert latest is not None
    assert latest.id == run.id
    assert len(candidates) == 1

    confirmed = service.confirm(db_session, project.id, run.id, candidates[0].id)
    assert confirmed.status == "confirmed"
    assert confirmed.selected_asset_id == asset.id
