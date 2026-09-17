from typing import Protocol

from sqlalchemy.orm import Session

from onetake_api.modules.asset.domain.model import Asset


class AssetRepository(Protocol):
    def add(self, session: Session, asset: Asset) -> None: ...
    def get(self, session: Session, asset_id: str) -> Asset | None: ...
    def update(self, session: Session, asset: Asset) -> None: ...
    def list_by_project(self, session: Session, project_id: str) -> list[Asset]: ...
    def count_by_project(self, session: Session, project_id: str) -> int: ...
    def find_by_sha256(
        self,
        session: Session,
        project_id: str,
        sha256: str,
        exclude_asset_id: str | None = None,
    ) -> Asset | None: ...