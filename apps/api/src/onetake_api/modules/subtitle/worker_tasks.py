from onetake_api.modules.subtitle.public import SubtitlePublicService
from onetake_api.platform.database import SessionLocal


def run_subtitle_job(job_id: str) -> None:
    session = SessionLocal()
    try:
        SubtitlePublicService().process_job(session, job_id)
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
