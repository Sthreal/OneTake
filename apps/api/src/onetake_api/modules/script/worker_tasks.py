from onetake_api.modules.script.public import ScriptPublicService
from onetake_api.platform.database import SessionLocal


def run_script_job(job_id: str) -> None:
    session = SessionLocal()
    try:
        ScriptPublicService().process_job(session, job_id)
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
