from onetake_api.modules.voice.public import VoicePublicService
from onetake_api.platform.database import SessionLocal


def run_voice_job(job_id: str) -> None:
    session = SessionLocal()
    try:
        VoicePublicService().process_job(session, job_id)
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
