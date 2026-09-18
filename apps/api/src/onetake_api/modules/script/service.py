from __future__ import annotations

import hashlib
from dataclasses import dataclass, replace

from sqlalchemy.orm import Session

from onetake_api.config import get_settings
from onetake_api.integrations.mock_script.adapter import MockScriptAdapter
from onetake_api.integrations.object_storage.dependencies import get_object_storage
from onetake_api.integrations.object_storage.public import ObjectStoragePublicService
from onetake_api.integrations.qwen_vl_script.adapter import QwenVlScriptAdapter
from onetake_api.modules.job.public import JobPublicService
from onetake_api.modules.main_image.public import MainImagePublicService
from onetake_api.modules.outbox.public import OutboxPublicService
from onetake_api.modules.pipeline.public import PipelinePublicService
from onetake_api.modules.project.public import ProjectPublicService
from onetake_api.modules.script.content import (
    NormalizedScript,
    normalize_edited,
    normalize_generated,
    normalize_input,
)
from onetake_api.modules.script.domain import (
    ACTIVE_STATUSES,
    EDITABLE_STATUSES,
    STATUS_CONFIRMED,
    STATUS_FAILED,
    STATUS_GENERATING,
    STATUS_QUEUED,
    STATUS_READY,
    ScriptInput,
    ScriptVersion,
)
from onetake_api.modules.script.repository import ScriptRepository
from onetake_api.platform.clock import SystemClock
from onetake_api.platform.errors import DomainError
from onetake_api.platform.ids import new_id
from onetake_api.platform.queue import get_queue


class ScriptNotFoundError(DomainError):
    code = "SCRIPT_NOT_FOUND"
    http_status = 404


class ScriptConflictError(DomainError):
    code = "SCRIPT_CONFLICT"
    http_status = 409
    retryable = True


class ScriptProviderConfigurationError(DomainError):
    code = "SCRIPT_PROVIDER_NOT_CONFIGURED"
    http_status = 422


@dataclass(frozen=True)
class ScriptView:
    version: ScriptVersion | None


def _adapter():
    settings = get_settings()
    if settings.mock_providers or settings.script_provider == "mock":
        return MockScriptAdapter()
    if not settings.dashscope_api_key:
        raise ScriptProviderConfigurationError("真实文案缺少 DASHSCOPE_API_KEY")
    return QwenVlScriptAdapter(
        api_key=settings.dashscope_api_key,
        endpoint=settings.script_endpoint,
        model=settings.script_model,
    )


def _facts_dict(script_input: ScriptInput) -> dict:
    return {
        "product_name": script_input.product_name,
        "product_note": script_input.product_note,
        "pain_point": script_input.pain_point,
        "selling_points": list(script_input.selling_points),
        "usage_scenario": script_input.usage_scenario,
        "offer": script_input.offer,
    }


def _input_from_version(version: ScriptVersion) -> ScriptInput:
    return ScriptInput(
        product_name=str(version.facts.get("product_name", "")),
        product_note=version.facts.get("product_note"),
        pain_point=str(version.facts.get("pain_point", "")),
        selling_points=tuple(version.facts.get("selling_points", [])),
        usage_scenario=str(version.facts.get("usage_scenario", "")),
        offer=version.facts.get("offer"),
    )


class ScriptApplicationService:
    def __init__(self, storage: ObjectStoragePublicService | None = None) -> None:
        self._repository = ScriptRepository()
        self._projects = ProjectPublicService()
        self._main_images = MainImagePublicService()
        self._pipeline = PipelinePublicService()
        self._jobs = JobPublicService()
        self._outbox = OutboxPublicService()
        self._clock = SystemClock()
        self._storage = storage

    @property
    def storage(self) -> ObjectStoragePublicService:
        return self._storage or get_object_storage()

    def latest(self, session: Session, project_id: str) -> ScriptView:
        self._projects.get_project(session, project_id=project_id)
        return ScriptView(self._repository.latest(session, project_id))

    def request(
        self,
        session: Session,
        *,
        project_id: str,
        pain_point: str,
        selling_points: list[str],
        usage_scenario: str,
        offer: str | None,
    ) -> ScriptView:
        project = self._projects.get_project(session, project_id=project_id)
        main_image = self._main_images.latest(session, project_id)
        if main_image is None or main_image.version.status != STATUS_CONFIRMED:
            raise ScriptConflictError("请先确认主图，再生成文案")
        if not main_image.version.transparent_object_key:
            raise ScriptConflictError("已确认主图没有可用文件")

        script_input = normalize_input(
            product_name=project.product_name,
            product_note=project.product_note,
            pain_point=pain_point,
            selling_points=selling_points,
            usage_scenario=usage_scenario,
            offer=offer,
        )
        latest = self._repository.latest(session, project_id)
        if latest and latest.status in ACTIVE_STATUSES:
            return ScriptView(latest)

        adapter = _adapter()
        now = self._clock.now()
        version = ScriptVersion(
            id=new_id("scr"),
            project_id=project_id,
            version_number=self._repository.next_version_number(session, project_id),
            status=STATUS_QUEUED,
            provider=adapter.provider_name,
            model=adapter.model,
            source_object_key=main_image.version.transparent_object_key,
            facts=_facts_dict(script_input),
            hook="",
            pain_point="",
            selling_points=[],
            usage_scenario="",
            offer=script_input.offer,
            cta="",
            full_text="",
            character_count=0,
            estimated_duration_seconds=0,
            error_code=None,
            created_at=now,
            updated_at=now,
            completed_at=None,
            confirmed_at=None,
        )
        self._repository.add(session, version)
        session.flush()
        pipeline = self._pipeline.mark_script_queued(session, project_id)
        input_hash = hashlib.sha256(
            f"{main_image.version.id}:{version.id}:{version.facts}".encode()
        ).hexdigest()
        job = self._jobs.create(
            session,
            project_id=project_id,
            pipeline_run_id=pipeline.id,
            job_type="script",
            provider=adapter.provider_name,
            input_hash=input_hash,
            idempotency_key=f"script:{project_id}:{version.id}",
            reference_id=version.id,
        )
        self._outbox.enqueue(
            session,
            event_name="ScriptRequested",
            aggregate_type="script",
            aggregate_id=version.id,
            occurred_at=now,
            payload={"project_id": project_id, "version_id": version.id},
        )
        session.commit()
        try:
            get_queue("script").enqueue(
                "onetake_api.modules.script.worker_tasks.run_script_job",
                job.id,
                job_id=job.id,
                job_timeout=180,
            )
        except Exception as exc:
            job = self._jobs.get(session, job.id)
            if job:
                self._jobs.mark_failed(session, job, "QUEUE_UNAVAILABLE")
            self._mark_failed(session, version, "QUEUE_UNAVAILABLE")
            raise ScriptConflictError("文案任务提交失败") from exc
        return ScriptView(version)

    def update(
        self,
        session: Session,
        *,
        project_id: str,
        hook: str | None,
        pain_point: str | None,
        selling_points: list[str] | None,
        usage_scenario: str | None,
        cta: str | None,
    ) -> ScriptView:
        self._projects.get_project(session, project_id=project_id)
        version = self._repository.latest(session, project_id)
        if version is None:
            raise ScriptNotFoundError("文案版本不存在")
        if version.status not in EDITABLE_STATUSES:
            raise ScriptConflictError("当前文案状态不允许编辑")
        script_input = _input_from_version(version)
        current = NormalizedScript(
            hook=version.hook,
            pain_point=version.pain_point,
            selling_points=version.selling_points,
            usage_scenario=version.usage_scenario,
            offer=version.offer,
            cta=version.cta,
            full_text=version.full_text,
            character_count=version.character_count,
            estimated_duration_seconds=version.estimated_duration_seconds,
        )
        normalized = normalize_edited(
            current=current,
            hook=hook,
            pain_point=pain_point,
            selling_points=selling_points,
            usage_scenario=usage_scenario,
            cta=cta,
            script_input=script_input,
        )
        updated = replace(
            version,
            status=STATUS_READY,
            hook=normalized.hook,
            pain_point=normalized.pain_point,
            selling_points=normalized.selling_points,
            usage_scenario=normalized.usage_scenario,
            cta=normalized.cta,
            full_text=normalized.full_text,
            character_count=normalized.character_count,
            estimated_duration_seconds=normalized.estimated_duration_seconds,
            error_code=None,
            updated_at=self._clock.now(),
            confirmed_at=None,
        )
        self._repository.update(session, updated)
        self._pipeline.mark_script_ready(session, project_id)
        self._outbox.enqueue(
            session,
            event_name="ScriptEdited",
            aggregate_type="script",
            aggregate_id=version.id,
            occurred_at=updated.updated_at,
            payload={"project_id": project_id, "version_id": version.id},
        )
        session.commit()
        return ScriptView(updated)

    def confirm(self, session: Session, project_id: str) -> ScriptView:
        self._projects.get_project(session, project_id=project_id)
        version = self._repository.latest(session, project_id)
        if version is None:
            raise ScriptNotFoundError("文案版本不存在")
        if version.status != STATUS_READY:
            raise ScriptConflictError("文案尚未准备确认")
        now = self._clock.now()
        confirmed = replace(version, status=STATUS_CONFIRMED, updated_at=now, confirmed_at=now)
        self._repository.update(session, confirmed)
        self._pipeline.mark_script_confirmed(session, project_id)
        self._outbox.enqueue(
            session,
            event_name="ScriptConfirmed",
            aggregate_type="script",
            aggregate_id=version.id,
            occurred_at=now,
            payload={"project_id": project_id, "version_id": version.id},
        )
        session.commit()
        return ScriptView(confirmed)

    def process_job(self, session: Session, job_id: str) -> ScriptVersion:
        job = self._jobs.get(session, job_id)
        if not job or job.job_type != "script" or job.status not in {"queued", "running"}:
            raise ScriptNotFoundError("文案任务不存在或不可执行")
        version = self._repository.get(session, job.reference_id)
        if version is None:
            raise ScriptNotFoundError("文案版本不存在")

        job = self._jobs.mark_running(session, job)
        version = replace(version, status=STATUS_GENERATING, updated_at=self._clock.now())
        self._repository.update(session, version)
        self._pipeline.mark_script_generating(session, version.project_id)
        session.commit()

        try:
            image_bytes = b"".join(self.storage.read_object(object_key=version.source_object_key))
            script_input = _input_from_version(version)
            draft = _adapter().generate(
                image_bytes=image_bytes,
                mime_type="image/png",
                script_input=script_input,
            )
            normalized = normalize_generated(draft, script_input)
            now = self._clock.now()
            version = replace(
                version,
                status=STATUS_READY,
                hook=normalized.hook,
                pain_point=normalized.pain_point,
                selling_points=normalized.selling_points,
                usage_scenario=normalized.usage_scenario,
                offer=normalized.offer,
                cta=normalized.cta,
                full_text=normalized.full_text,
                character_count=normalized.character_count,
                estimated_duration_seconds=normalized.estimated_duration_seconds,
                error_code=None,
                updated_at=now,
                completed_at=now,
            )
            self._repository.update(session, version)
            self._jobs.mark_succeeded(session, job)
            self._pipeline.mark_script_ready(session, version.project_id)
            self._outbox.enqueue(
                session,
                event_name="ScriptGenerated",
                aggregate_type="script",
                aggregate_id=version.id,
                occurred_at=now,
                payload={
                    "project_id": version.project_id,
                    "version_id": version.id,
                    "character_count": normalized.character_count,
                },
            )
            session.commit()
            return version
        except DomainError as exc:
            self._jobs.mark_failed(session, job, exc.code)
            return self._mark_failed(session, version, exc.code)
        except Exception:
            self._jobs.mark_failed(session, job, "SCRIPT_PROVIDER_ERROR")
            return self._mark_failed(session, version, "SCRIPT_PROVIDER_ERROR")

    def _mark_failed(self, session: Session, version: ScriptVersion, error_code: str) -> ScriptVersion:
        now = self._clock.now()
        failed = replace(version, status=STATUS_FAILED, error_code=error_code, updated_at=now, completed_at=now)
        self._repository.update(session, failed)
        self._pipeline.mark_script_failed(session, version.project_id)
        self._outbox.enqueue(
            session,
            event_name="ScriptFailed",
            aggregate_type="script",
            aggregate_id=version.id,
            occurred_at=now,
            payload={"project_id": version.project_id, "version_id": version.id, "error_code": error_code},
        )
        session.commit()
        return failed
