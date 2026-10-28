from __future__ import annotations

from sqlalchemy.orm import Session

from onetake_api.modules.preview.domain import PreviewArtifact
from onetake_api.modules.preview.service import PreviewService


class PreviewPublicService:
    def __init__(self, service: PreviewService | None = None) -> None:
        self._service = service or PreviewService()

    def build_preview(self, session: Session, project_id: str, *, force: bool = False) -> PreviewArtifact:
        return self._service.build_preview(session, project_id, force=force)

    def latest(self, session: Session, project_id: str) -> PreviewArtifact:
        return self._service.latest(session, project_id)
