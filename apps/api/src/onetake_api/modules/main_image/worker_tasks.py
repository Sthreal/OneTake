from onetake_api.modules.main_image.public import MainImagePublicService
from onetake_api.platform.database import SessionLocal


def _run(task_name: str, job_id: str) -> None:
    session = SessionLocal()
    try:
        service = MainImagePublicService()
        getattr(service, task_name)(session, job_id)
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def run_image_edit_job(job_id: str) -> None:
    _run("process_image_edit_job", job_id)


def run_matting_job(job_id: str) -> None:
    _run("process_matting_job", job_id)


def run_main_image_job(job_id: str) -> None:
    _run("process_finalize_job", job_id)
