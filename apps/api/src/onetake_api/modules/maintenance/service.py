from __future__ import annotations

import logging
from dataclasses import dataclass

from sqlalchemy.orm import Session

from onetake_api.integrations.object_storage.public import ObjectStoragePublicService
from onetake_api.modules.outbox.public import OutboxPublicService
from onetake_api.modules.project.public import ProjectPublicService
from onetake_api.platform.clock import SystemClock

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class MediaCleanupResult:
    scanned_projects: int
    deleted_objects: int
    failed_projects: int


class MediaLifecycleService:
    def __init__(self) -> None:
        self._projects = ProjectPublicService()
        self._outbox = OutboxPublicService()
        self._clock = SystemClock()

    def delete_project_media(
        self,
        session: Session,
        *,
        project_id: str,
        storage: ObjectStoragePublicService,
    ) -> int:
        self._projects.get_project(session, project_id=project_id)
        deleted_objects = storage.delete_prefix(prefix=f"projects/{project_id}/")
        now = self._clock.now()
        self._outbox.enqueue(
            session,
            event_name="ProjectMediaDeleted",
            aggregate_type="project",
            aggregate_id=project_id,
            occurred_at=now,
            payload={"project_id": project_id, "deleted_objects": deleted_objects},
        )
        return deleted_objects

    def cleanup_expired_media(
        self,
        session: Session,
        *,
        storage: ObjectStoragePublicService,
    ) -> MediaCleanupResult:
        projects = self._projects.list_expired(session, before=self._clock.now())
        deleted_objects = 0
        failed_projects = 0
        for project in projects:
            try:
                deleted_objects += self.delete_project_media(
                    session,
                    project_id=project.id,
                    storage=storage,
                )
            except Exception:
                failed_projects += 1
                logger.exception("清理过期项目媒体失败 project_id=%s", project.id)
        return MediaCleanupResult(
            scanned_projects=len(projects),
            deleted_objects=deleted_objects,
            failed_projects=failed_projects,
        )