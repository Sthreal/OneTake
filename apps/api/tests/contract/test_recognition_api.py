from datetime import UTC, datetime

from sqlalchemy.orm import Session

from onetake_api.modules.asset.adapters.sqlalchemy_repository import SqlAlchemyAssetRepository
from onetake_api.modules.asset.domain.model import ASSET_STATUS_READY, create_pending_asset
from onetake_api.modules.job.public import JobPublicService
from onetake_api.modules.pipeline.public import PipelinePublicService
from onetake_api.modules.recognition.service import RecognitionService


class FakeQueue:
    def enqueue(self, *_args, **_kwargs):
        return None


def _add_ready_asset(session: Session, project_id: str) -> None:
    now = datetime.now(UTC)
    asset = create_pending_asset(
        asset_id="ast_api_recognition",
        project_id=project_id,
        object_key=f"projects/{project_id}/assets/ast_api_recognition/original.png",
        original_filename="商品图.png",
        mime_type="image/png",
        size_bytes=1024,
        width=640,
        height=640,
        sha256="b" * 64,
        now=now,
    )
    asset = asset.__class__(**{**asset.__dict__, "status": ASSET_STATUS_READY})
    SqlAlchemyAssetRepository().add(session, asset)
    session.flush()


def test_recognition_api_flow(client, db_session: Session, monkeypatch) -> None:
    monkeypatch.setattr("onetake_api.modules.recognition.service.get_queue", lambda _name: FakeQueue())
    project = client.post("/api/v1/projects", json={"product_name": "识别项目"}).json()["data"]
    _add_ready_asset(db_session, project["project_id"])

    response = client.post(f"/api/v1/projects/{project['project_id']}/recognition")
    assert response.status_code == 202
    run = response.json()["data"]["run"]
    assert run["status"] == "queued"

    job = JobPublicService().find_active(db_session, project["project_id"], "recognition")
    assert job is not None
    RecognitionService().process_job(db_session, job.id)

    latest = client.get(f"/api/v1/projects/{project['project_id']}/recognition").json()["data"]
    assert latest["run"]["status"] == "ready"
    assert len(latest["candidates"]) == 1

    confirmed = client.post(
        f"/api/v1/projects/{project['project_id']}/recognition/{run['run_id']}/confirm",
        json={"asset_id": latest["candidates"][0]["asset_id"], "candidate_id": latest["candidates"][0]["candidate_id"]},
    )
    assert confirmed.status_code == 200
    assert confirmed.json()["data"]["run"]["status"] == "confirmed"

    pipeline = client.get(f"/api/v1/projects/{project['project_id']}/pipeline")
    assert pipeline.status_code == 200
    assert pipeline.json()["data"]["status"] == "recognition_confirmed"
