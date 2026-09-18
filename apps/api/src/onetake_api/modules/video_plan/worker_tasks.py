from onetake_api.modules.video_plan.public import VideoPlanPublicService
from onetake_api.platform.database import SessionLocal


def run_video_job(job_id: str) -> None:
    session = SessionLocal()
    try:
        VideoPlanPublicService().process_job(session, job_id)
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
