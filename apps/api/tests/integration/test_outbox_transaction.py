from __future__ import annotations

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from onetake_api.modules.outbox.adapters.sqlalchemy_repository import OutboxEventModel
from onetake_api.modules.outbox.public import OutboxPublicService
from onetake_api.modules.project.adapters.sqlalchemy_repository import ProjectModel
from onetake_api.modules.project.public import ProjectPublicService


def _count(session: Session, model) -> int:
    return session.scalar(select(func.count()).select_from(model)) or 0


def test_outbox_write_rolls_back_with_project(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    before_projects = _count(db_session, ProjectModel)
    before_events = _count(db_session, OutboxEventModel)

    def fail_enqueue(*_args, **_kwargs):
        raise RuntimeError("outbox unavailable")

    monkeypatch.setattr(OutboxPublicService, "enqueue", fail_enqueue)

    with pytest.raises(RuntimeError):
        with db_session.begin_nested():
            ProjectPublicService().create_project(
                db_session,
                product_name="失败项目",
                product_note=None,
            )

    assert _count(db_session, ProjectModel) == before_projects
    assert _count(db_session, OutboxEventModel) == before_events