from datetime import UTC, datetime

from sqlalchemy.orm import Session

from onetake_api.modules.asset.adapters.sqlalchemy_repository import SqlAlchemyAssetRepository
from onetake_api.modules.asset.domain.model import create_pending_asset
from onetake_api.modules.project.public import ProjectPublicService


def test_asset_repository_lifecycle(db_session: Session) -> None:
    project = ProjectPublicService().create_project(
        db_session,
        product_name="素材测试商品",
        product_note=None,
    )
    now = datetime.now(UTC)
    asset = create_pending_asset(
        asset_id="ast_test",
        project_id=project.id,
        object_key=f"projects/{project.id}/assets/ast_test/original.png",
        original_filename="test.png",
        mime_type="image/png",
        size_bytes=1024,
        width=600,
        height=600,
        sha256="a" * 64,
        now=now,
    )
    repository = SqlAlchemyAssetRepository()
    repository.add(db_session, asset)
    db_session.flush()

    assert repository.get(db_session, asset.id) is not None
    assert repository.count_by_project(db_session, project.id) == 1
    assert [item.id for item in repository.list_by_project(db_session, project.id)] == [asset.id]
    assert repository.find_by_sha256(db_session, project.id, "a" * 64) is not None