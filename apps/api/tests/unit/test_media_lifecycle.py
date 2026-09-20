from datetime import UTC, datetime
from types import SimpleNamespace

from onetake_api.modules.maintenance.service import MediaLifecycleService


class FakeStorage:
    def __init__(self, *, fail_prefix: str | None = None) -> None:
        self.deleted_prefixes: list[str] = []
        self.fail_prefix = fail_prefix

    def delete_prefix(self, *, prefix: str) -> int:
        self.deleted_prefixes.append(prefix)
        if prefix == self.fail_prefix:
            raise RuntimeError("storage failed")
        return 2


class FakeProjects:
    def __init__(self, *, expired: list | None = None) -> None:
        self.expired = expired or []

    def get_project(self, _session, *, project_id: str):
        return SimpleNamespace(id=project_id)

    def list_expired(self, _session, *, before: datetime):
        return self.expired


class FakeOutbox:
    def __init__(self) -> None:
        self.events: list[dict] = []

    def enqueue(self, _session, **kwargs) -> None:
        self.events.append(kwargs)


class FakeClock:
    def now(self) -> datetime:
        return datetime(2026, 9, 20, tzinfo=UTC)


def test_delete_project_media_deletes_only_project_prefix() -> None:
    service = MediaLifecycleService()
    service._projects = FakeProjects()
    service._outbox = FakeOutbox()
    service._clock = FakeClock()
    storage = FakeStorage()

    deleted = service.delete_project_media(None, project_id="prj_1", storage=storage)

    assert deleted == 2
    assert storage.deleted_prefixes == ["projects/prj_1/"]
    assert service._outbox.events[0]["event_name"] == "ProjectMediaDeleted"
    assert service._outbox.events[0]["payload"] == {"project_id": "prj_1", "deleted_objects": 2}


def test_cleanup_expired_media_reports_failed_project() -> None:
    service = MediaLifecycleService()
    service._projects = FakeProjects(expired=[SimpleNamespace(id="prj_1"), SimpleNamespace(id="prj_2")])
    service._outbox = FakeOutbox()
    service._clock = FakeClock()
    storage = FakeStorage(fail_prefix="projects/prj_2/")

    result = service.cleanup_expired_media(None, storage=storage)

    assert result.scanned_projects == 2
    assert result.deleted_objects == 2
    assert result.failed_projects == 1
    assert storage.deleted_prefixes == ["projects/prj_1/", "projects/prj_2/"]