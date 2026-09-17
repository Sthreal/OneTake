from onetake_api.modules.recognition.service import RecognitionService
from onetake_api.platform.database import SessionLocal


def run_recognition_job(job_id: str) -> None:
    session = SessionLocal()
    try:
        RecognitionService().process_job(session, job_id)
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
