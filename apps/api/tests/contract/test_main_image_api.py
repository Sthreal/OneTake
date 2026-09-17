from datetime import UTC, datetime
from hashlib import sha256
from io import BytesIO

from PIL import Image
from sqlalchemy.orm import Session

from onetake_api.modules.asset.adapters.sqlalchemy_repository import SqlAlchemyAssetRepository
from onetake_api.modules.asset.domain.model import ASSET_STATUS_READY, create_pending_asset
from onetake_api.modules.job.public import JobPublicService
from onetake_api.modules.recognition.service import RecognitionService


class FakeQueue:
    def enqueue(self, *_args, **_kwargs):
        return None


def _png() -> bytes:
    output = BytesIO()
    image = Image.new("RGB", (800, 800), (255, 255, 255))
    image.paste(Image.new("RGB", (320, 480), (30, 110, 220)), (240, 160))
    image.save(output, format="PNG")
    return output.getvalue()


def test_main_image_requires_confirmed_recognition(client) -> None:
    project = client.post("/api/v1/projects", json={"product_name": "主图前置"}).json()["data"]
    response = client.post(f"/api/v1/projects/{project['project_id']}/main-image")
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "MAIN_IMAGE_CONFLICT"


def test_main_image_get_empty_state(client) -> None:
    project = client.post("/api/v1/projects", json={"product_name": "主图空状态"}).json()["data"]
    response = client.get(f"/api/v1/projects/{project['project_id']}/main-image")
    assert response.status_code == 200
    assert response.json()["data"]["version"] is None


def test_main_image_api_can_start_after_confirmation(client, db_session: Session, monkeypatch) -> None:
    monkeypatch.setattr("onetake_api.modules.recognition.service.get_queue", lambda _name: FakeQueue())
    monkeypatch.setattr("onetake_api.modules.main_image.service.get_queue", lambda _name: FakeQueue())
    project = client.post("/api/v1/projects", json={"product_name": "主图接口"}).json()["data"]
    content = _png()
    now = datetime.now(UTC)
    asset = create_pending_asset(
        asset_id="ast_main_api",
        project_id=project["project_id"],
        object_key=f"projects/{project['project_id']}/assets/ast_main_api/original.png",
        original_filename="商品.png",
        mime_type="image/png",
        size_bytes=len(content),
        width=800,
        height=800,
        sha256=sha256(content).hexdigest(),
        now=now,
    )
    asset = asset.__class__(**{**asset.__dict__, "status": ASSET_STATUS_READY})
    SqlAlchemyAssetRepository().add(db_session, asset)
    db_session.flush()

    recognition = RecognitionService()
    run = recognition.request(db_session, project["project_id"])
    job = JobPublicService().find_active(db_session, project["project_id"], "recognition")
    assert job is not None
    recognition.process_job(db_session, job.id)
    _, candidates = recognition.latest(db_session, project["project_id"])
    recognition.confirm(db_session, project["project_id"], run.id, candidates[0].id)

    response = client.post(f"/api/v1/projects/{project['project_id']}/main-image")
    assert response.status_code == 202
    data = response.json()["data"]["version"]
    assert data["status"] == "queued"
    assert data["png_url"] is None
