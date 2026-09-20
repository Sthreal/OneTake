from __future__ import annotations

import logging

from onetake_api.integrations.object_storage.dependencies import get_object_storage
from onetake_api.modules.maintenance.service import MediaLifecycleService
from onetake_api.platform.database import SessionLocal

logger = logging.getLogger(__name__)


def run_media_cleanup() -> dict[str, int]:
    session = SessionLocal()
    try:
        result = MediaLifecycleService().cleanup_expired_media(
            session,
            storage=get_object_storage(),
        )
        session.commit()
        payload = {
            "scanned_projects": result.scanned_projects,
            "deleted_objects": result.deleted_objects,
            "failed_projects": result.failed_projects,
        }
        logger.info("媒体生命周期清理完成 %s", payload)
        return payload
    except Exception:
        session.rollback()
        logger.exception("媒体生命周期清理任务失败")
        raise
    finally:
        session.close()