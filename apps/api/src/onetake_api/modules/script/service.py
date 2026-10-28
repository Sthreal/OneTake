from __future__ import annotations

import logging
import hashlib
from dataclasses import dataclass, replace

from sqlalchemy.orm import Session

from onetake_api.config import get_settings
from onetake_api.integrations.mock_script.adapter import MockScriptAdapter
from onetake_api.integrations.object_storage.dependencies import get_object_storage
from onetake_api.integrations.object_storage.public import ObjectStoragePublicService
from onetake_api.integrations.qwen_vl_script.adapter import QwenVlScriptAdapter, QwenVlScriptError, ScriptReview
from onetake_api.modules.job.public import JobPublicService
from onetake_api.modules.main_image.public import MainImagePublicService
from onetake_api.modules.outbox.public import OutboxPublicService
from onetake_api.modules.pipeline.public import PipelinePublicService
from onetake_api.modules.project.public import ProjectPublicService
from onetake_api.modules.script.angles import (
    DEFAULT_ANGLES,
    FACT_ANGLE,
    FACT_ANGLE_INDEX,
    FACT_BATCH_ID,
    FACT_SELECTED,
    is_selected_facts,
)
from onetake_api.modules.script.content import (
    NormalizedScript,
    ScriptGenerationError,
    normalize_edited,
    normalize_generated,
    normalize_input,
)
from onetake_api.modules.script.domain import (
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


logger = logging.getLogger(__name__)


class ScriptProviderConfigurationError(DomainError):
    code = "SCRIPT_PROVIDER_NOT_CONFIGURED"
    http_status = 422


@dataclass(frozen=True)
class ScriptView:
    version: ScriptVersion | None
    candidates: tuple[ScriptVersion, ...] = ()
    selected_version_id: str | None = None


# 三个角度各一次 provider 调用。单次超时 120 秒，再留余量。不在这里发 live 请求。
_SCRIPT_JOB_TIMEOUT_SECONDS = 420


def normalize_with_review_fallback(*, reviewed_draft, original_draft, script_input, review):
    """审稿后的稿子若**过不了既有内容校验**，退回未审稿版本（审稿是增强，不是新失败点）。

    真机实测踩到：审稿把 hook/pain_point/cta 都改写了，但改写稿不满足当时的字数口径/事实白名单 →
    原来的实现直接 `ScriptGenerationError` 让整条文案**生成失败** ✗。
    现在：先试审稿版，失败就退未审稿版（**不再多花一次调用**），并把 review 置空（如实反映"这次没用上审稿"）。
    """
    try:
        return normalize_generated(reviewed_draft, script_input), review
    except ScriptGenerationError as exc:
        if review is None:
            raise
        logger.warning("审稿版不满足内容约束（%s），退回未审稿版本", exc.message)
        return normalize_generated(original_draft, script_input), None

def apply_script_review(adapter, *, script_input, draft, enabled: bool):
    """批次 2b：审稿是**增强**，不是必经路径。

    - 未启用 / 适配器没实现 `review` → 直接用未审稿版本（零行为变更）；
    - 审稿**失败**（超时、结构不合法、卖点条数被改）→ 退回未审稿版本，只记一行原因
      （绝不因为"审稿没跑成"让整条文案生成失败）。
    - 产物仍要过 `normalize_generated` 的全部既有校验（事实/字数/数字白名单），审稿不能绕过它们。
    """
    if not enabled or adapter is None or not hasattr(adapter, "review"):
        return draft, None
    try:
        review: ScriptReview = adapter.review(script_input=script_input, draft=draft)
    except QwenVlScriptError as exc:
        logger.warning("文案审稿失败，使用未审稿版本：%s", exc.message)
        return draft, None
    return review.revised, review


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
        return self._present(session, project_id, self._repository.latest(session, project_id))

    def _present(self, session: Session, project_id: str, version: ScriptVersion | None) -> ScriptView:
        if version is None:
            return ScriptView(version=None)
        batch_id = (version.facts or {}).get(FACT_BATCH_ID)
        if not batch_id:
            return ScriptView(version=version, candidates=(version,), selected_version_id=version.id)
        candidates = tuple(self._repository.list_batch(session, project_id, batch_id))
        if not candidates:
            selected_id = version.id if is_selected_facts(version.facts) else None
            return ScriptView(version=version, candidates=(version,), selected_version_id=selected_id)
        selected = next(
            (item for item in candidates if (item.facts or {}).get(FACT_SELECTED)),
            candidates[0],
        )
        return ScriptView(version=selected, candidates=candidates, selected_version_id=selected.id)

    def _batch_of(self, session: Session, version: ScriptVersion) -> list[ScriptVersion]:
        batch_id = (version.facts or {}).get(FACT_BATCH_ID)
        if not batch_id:
            return [version]
        found = self._repository.list_batch(session, version.project_id, batch_id)
        return found or [version]

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
        if self._repository.has_active(session, project_id):
            return self._present(session, project_id, self._repository.latest(session, project_id))

        adapter = _adapter()
        now = self._clock.now()
        batch_id = new_id("sbg")
        base_facts = _facts_dict(script_input)
        start_number = self._repository.next_version_number(session, project_id)
        versions: list[ScriptVersion] = []
        for index, angle in enumerate(DEFAULT_ANGLES):
            version = ScriptVersion(
                id=new_id("scr"),
                project_id=project_id,
                version_number=start_number + index,
                status=STATUS_QUEUED,
                provider=adapter.provider_name,
                model=adapter.model,
                source_object_key=main_image.version.transparent_object_key,
                facts={
                    **base_facts,
                    FACT_ANGLE: angle,
                    FACT_ANGLE_INDEX: index,
                    FACT_BATCH_ID: batch_id,
                    FACT_SELECTED: index == 0,
                },
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
            versions.append(version)
        session.flush()
        primary = versions[0]
        pipeline = self._pipeline.mark_script_queued(session, project_id)
        input_hash = hashlib.sha256(
            f"{main_image.version.id}:{batch_id}:{primary.facts}".encode()
        ).hexdigest()
        job = self._jobs.create(
            session,
            project_id=project_id,
            pipeline_run_id=pipeline.id,
            job_type="script",
            provider=adapter.provider_name,
            input_hash=input_hash,
            idempotency_key=f"script:{project_id}:{batch_id}",
            reference_id=primary.id,
        )
        self._outbox.enqueue(
            session,
            event_name="ScriptRequested",
            aggregate_type="script",
            aggregate_id=primary.id,
            occurred_at=now,
            payload={
                "project_id": project_id,
                "version_id": primary.id,
                "generation_batch_id": batch_id,
                "candidate_version_ids": [item.id for item in versions],
            },
        )
        session.commit()
        try:
            get_queue("script").enqueue(
                "onetake_api.modules.script.worker_tasks.run_script_job",
                job.id,
                job_id=job.id,
                job_timeout=_SCRIPT_JOB_TIMEOUT_SECONDS,
            )
        except Exception as exc:
            job = self._jobs.get(session, job.id)
            if job:
                self._jobs.mark_failed(session, job, "QUEUE_UNAVAILABLE")
            self._mark_batch_failed(session, versions, "QUEUE_UNAVAILABLE")
            raise ScriptConflictError("文案任务提交失败") from exc
        return self._present(session, project_id, primary)

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
        return self._present(session, project_id, updated)

    def select(self, session: Session, *, project_id: str, version_id: str) -> ScriptView:
        self._projects.get_project(session, project_id=project_id)
        target = self._repository.get(session, version_id)
        if target is None or target.project_id != project_id:
            raise ScriptNotFoundError("文案版本不存在")
        current = self._repository.latest(session, project_id)
        if current is None:
            raise ScriptNotFoundError("文案版本不存在")
        batch_id = (current.facts or {}).get(FACT_BATCH_ID)
        if not batch_id or (target.facts or {}).get(FACT_BATCH_ID) != batch_id:
            raise ScriptConflictError("只能选用最近一次生成的文案角度")
        candidates = self._repository.list_batch(session, project_id, batch_id)
        if any(item.status == STATUS_CONFIRMED for item in candidates):
            raise ScriptConflictError("文案已确认，不能再切换角度")
        if target.status != STATUS_READY:
            raise ScriptConflictError("该角度文案尚未准备好，不能选用")
        if is_selected_facts(target.facts):
            return self._present(session, project_id, target)
        now = self._clock.now()
        for item in candidates:
            chosen = item.id == target.id
            updated = replace(
                item,
                facts={**item.facts, FACT_SELECTED: chosen},
                updated_at=now,
            )
            self._repository.update(session, updated)
        self._outbox.enqueue(
            session,
            event_name="ScriptAngleSelected",
            aggregate_type="script",
            aggregate_id=target.id,
            occurred_at=now,
            payload={
                "project_id": project_id,
                "version_id": target.id,
                "generation_batch_id": batch_id,
                "angle": (target.facts or {}).get(FACT_ANGLE),
            },
        )
        session.commit()
        return self._present(session, project_id, self._repository.get(session, target.id))

    def confirm(self, session: Session, project_id: str) -> ScriptView:
        self._projects.get_project(session, project_id=project_id)
        version = self._repository.latest(session, project_id)
        if version is None:
            raise ScriptNotFoundError("文案版本不存在")
        if not is_selected_facts(version.facts):
            raise ScriptConflictError("只能确认当前选中的文案角度")
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
            payload={
                "project_id": project_id,
                "version_id": version.id,
                "angle": (version.facts or {}).get(FACT_ANGLE),
            },
        )
        session.commit()
        return self._present(session, project_id, confirmed)

    def process_job(self, session: Session, job_id: str) -> ScriptVersion:
        job = self._jobs.get(session, job_id)
        if not job or job.job_type != "script" or job.status not in {"queued", "running"}:
            raise ScriptNotFoundError("文案任务不存在或不可执行")
        version = self._repository.get(session, job.reference_id)
        if version is None:
            raise ScriptNotFoundError("文案版本不存在")

        now = self._clock.now()
        batch = [
            replace(item, status=STATUS_GENERATING, updated_at=now)
            for item in self._batch_of(session, version)
        ]
        for item in batch:
            self._repository.update(session, item)
        job = self._jobs.mark_running(session, job)
        self._pipeline.mark_script_generating(session, version.project_id)
        session.commit()

        try:
            image_bytes = b"".join(self.storage.read_object(object_key=batch[0].source_object_key))
            script_input = _input_from_version(batch[0])
            adapter = _adapter()
            settings = get_settings()
            review_enabled = bool(getattr(settings, "script_review_enabled", False))
            ready: list[ScriptVersion] = []
            for item in batch:
                angle = (item.facts or {}).get(FACT_ANGLE)
                draft = adapter.generate(
                    image_bytes=image_bytes,
                    mime_type="image/png",
                    script_input=script_input,
                    angle=angle if isinstance(angle, str) else None,
                )
                # 批次 2b：可选审稿（多一次付费调用；默认关闭）。审稿失败只降级，不影响成稿。
                # 切片 C 的闸门不在这里。三个角度共用这一开关，默认不打审稿。
                generated_draft = draft
                draft, review = apply_script_review(
                    adapter, script_input=script_input, draft=draft, enabled=review_enabled,
                )
                if review is not None:
                    logger.info(
                        "文案审稿：未通过维度=%s，改写字段=%s",
                        review.failed_dimensions, review.changed_fields,
                    )
                normalized, review = normalize_with_review_fallback(
                    reviewed_draft=draft, original_draft=generated_draft,
                    script_input=script_input, review=review,
                )
                finished_at = self._clock.now()
                ready.append(replace(
                    item,
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
                    updated_at=finished_at,
                    completed_at=finished_at,
                ))
            for item in ready:
                self._repository.update(session, item)
            self._jobs.mark_succeeded(session, job)
            self._pipeline.mark_script_ready(session, version.project_id)
            selected = next((item for item in ready if is_selected_facts(item.facts)), ready[0])
            self._outbox.enqueue(
                session,
                event_name="ScriptGenerated",
                aggregate_type="script",
                aggregate_id=selected.id,
                occurred_at=selected.completed_at or self._clock.now(),
                payload={
                    "project_id": selected.project_id,
                    "version_id": selected.id,
                    "character_count": selected.character_count,
                    "generation_batch_id": (selected.facts or {}).get(FACT_BATCH_ID),
                    "candidate_version_ids": [item.id for item in ready],
                },
            )
            session.commit()
            logger.info(
                "文案多角度已生成 batch=%s angles=%s",
                (selected.facts or {}).get(FACT_BATCH_ID),
                [(item.facts or {}).get(FACT_ANGLE) for item in ready],
            )
            return selected
        except DomainError as exc:
            logger.warning("文案生成未通过校验：%s %s", exc.code, getattr(exc, "message", exc))
            self._jobs.mark_failed(session, job, exc.code)
            return self._mark_batch_failed(session, batch, exc.code)
        except Exception:
            self._jobs.mark_failed(session, job, "SCRIPT_PROVIDER_ERROR")
            return self._mark_batch_failed(session, batch, "SCRIPT_PROVIDER_ERROR")

    def _mark_batch_failed(self, session: Session, versions: list[ScriptVersion], error_code: str) -> ScriptVersion:
        now = self._clock.now()
        failed: list[ScriptVersion] = []
        for version in versions:
            item = replace(
                version,
                status=STATUS_FAILED,
                error_code=error_code,
                updated_at=now,
                completed_at=now,
            )
            self._repository.update(session, item)
            failed.append(item)
        project_id = versions[0].project_id
        self._pipeline.mark_script_failed(session, project_id)
        selected = next((item for item in failed if is_selected_facts(item.facts)), failed[0])
        self._outbox.enqueue(
            session,
            event_name="ScriptFailed",
            aggregate_type="script",
            aggregate_id=selected.id,
            occurred_at=now,
            payload={
                "project_id": project_id,
                "version_id": selected.id,
                "error_code": error_code,
                "generation_batch_id": (selected.facts or {}).get(FACT_BATCH_ID),
                "candidate_version_ids": [item.id for item in failed],
            },
        )
        session.commit()
        return selected
