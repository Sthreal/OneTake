from __future__ import annotations

import logging
import hashlib
from dataclasses import dataclass, replace

from sqlalchemy.orm import Session

from onetake_api.config import get_settings
from onetake_api.integrations.mock_script.adapter import MockScriptAdapter
from onetake_api.integrations.object_storage.dependencies import get_object_storage
from onetake_api.integrations.object_storage.public import ObjectStoragePublicService
from onetake_api.integrations.qwen_vl_script.adapter import (
    REVIEW_DIMENSIONS,
    QwenVlScriptAdapter,
    QwenVlScriptError,
    ScriptReview,
)
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
from onetake_api.modules.script.review_gate import (
    GATE_ENFORCE,
    GATE_WARN,
    STATUS_FAILED,
    STATUS_PASSED,
    STATUS_REVIEWED,
    assess_revision,
    draft_from_mapping,
    draft_from_version,
    draft_to_dict,
    effective_gate_status,
    facts_with_gate,
    facts_without_gate,
    inline_review_enabled,
    is_review_passed,
    script_fingerprint,
    stored_gate,
)
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


class ScriptReviewRequiredError(DomainError):
    """付费视频或文案确认前，当前稿还没有 apply / ack。"""

    code = "SCRIPT_REVIEW_REQUIRED"
    http_status = 409
    retryable = True


class ScriptReviewRejectedError(DomainError):
    """审稿改写不能应用（等长或内容校验失败）。人仍可以 ack 保留原稿。"""

    code = "SCRIPT_REVIEW_LENGTH"
    http_status = 409
    retryable = True

    def __init__(self, message: str, *, code: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class ScriptView:
    version: ScriptVersion | None
    candidates: tuple[ScriptVersion, ...] = ()
    selected_version_id: str | None = None


# 三个角度各一次 provider 调用。单次超时 120 秒，再留余量。不在这里发 live 请求。
_SCRIPT_JOB_TIMEOUT_SECONDS = 420


@dataclass(frozen=True)
class ScriptReviewView:
    version: ScriptVersion
    gate_mode: str
    gate_status: str
    decision: str | None
    dimensions: dict
    failed_dimensions: list[str]
    revised: dict | None
    changed_fields: list[str]
    length_ok: bool
    length_errors: list[str]
    error_code: str | None
    blocks_paid_video: bool


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


def _json_dimensions(review: ScriptReview) -> dict:
    raw = review.dimensions if isinstance(review.dimensions, dict) else {}
    cleaned: dict = {}
    for name in REVIEW_DIMENSIONS:
        item = raw.get(name) if isinstance(raw.get(name), dict) else {}
        cleaned[name] = {
            "passed": bool(item.get("passed")),
            "reason": str(item.get("reason") or ""),
        }
    return cleaned


def _attempt_gate(
    version: ScriptVersion,
    *,
    status: str,
    length_ok: bool,
    length_errors: list[str],
    error_code: str | None,
    dimensions: dict,
    failed_dimensions: list[str],
    changed_fields: list[str],
    revised: dict | None,
) -> dict:
    fingerprint = script_fingerprint(version)
    return {
        "attempted": True,
        "source_fingerprint": fingerprint,
        "fingerprint": fingerprint,
        "status": status,
        "decision": None,
        "length_ok": length_ok,
        "length_errors": list(length_errors),
        "error_code": error_code,
        "dimensions": dimensions,
        "failed_dimensions": list(failed_dimensions),
        "changed_fields": list(changed_fields),
        "revised": revised,
    }


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
        # 手改等于换了一份口播，上一轮 apply/ack 作废，付费前要重新审。
        updated = replace(
            version,
            facts=facts_without_gate(version.facts),
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

    def confirm(self, session: Session, project_id: str, *, enforce_review_gate: bool = True) -> ScriptView:
        self._projects.get_project(session, project_id=project_id)
        version = self._repository.latest(session, project_id)
        if version is None:
            raise ScriptNotFoundError("文案版本不存在")
        if not is_selected_facts(version.facts):
            raise ScriptConflictError("只能确认当前选中的文案角度")
        if version.status != STATUS_READY:
            raise ScriptConflictError("文案尚未准备确认")
        mode = get_settings().script_review_gate
        if enforce_review_gate and mode == GATE_ENFORCE and not is_review_passed(version):
            raise ScriptReviewRequiredError("文案确认前需要先完成审稿：应用改写或明确保留原稿")
        if enforce_review_gate and mode == GATE_WARN and not is_review_passed(version):
            logger.warning("审稿闸未通过（warn，不拦截文案确认）project_id=%s", project_id)
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

    def review_gate_passed(self, session: Session, project_id: str) -> bool:
        self._projects.get_project(session, project_id=project_id)
        version = self._repository.latest(session, project_id)
        if version is None:
            return False
        return is_review_passed(version)

    def review(self, session: Session, project_id: str) -> ScriptReviewView:
        """对当前 ready / confirmed 稿跑四维审稿。等长失败整次失败，不改口播、不过闸。"""
        version = self._require_reviewable(session, project_id)
        script_input = _input_from_version(version)
        original = draft_from_version(version)
        adapter = _adapter()
        if not hasattr(adapter, "review"):
            raise ScriptProviderConfigurationError("当前文案适配器不支持审稿")
        try:
            result: ScriptReview = adapter.review(script_input=script_input, draft=original)
        except QwenVlScriptError as exc:
            logger.warning("文案审稿调用失败，不自动过闸：%s", exc.message)
            self._store_gate(
                session,
                version,
                _attempt_gate(
                    version,
                    status=STATUS_FAILED,
                    length_ok=False,
                    length_errors=[],
                    error_code=exc.code,
                    dimensions={},
                    failed_dimensions=[],
                    changed_fields=[],
                    revised=None,
                ),
            )
            raise
        assessment = assess_revision(original, result.revised, script_input)
        dimensions = _json_dimensions(result)
        dims_ok = all(name in (result.dimensions or {}) for name in REVIEW_DIMENSIONS)
        if assessment.ok and dims_ok:
            gate_status = STATUS_REVIEWED
            error_code = None
            length_ok = True
            logger.info(
                "文案审稿完成，等待 apply 或 ack：未通过维度=%s，改写字段=%s",
                list(result.failed_dimensions),
                list(result.changed_fields),
            )
        else:
            gate_status = STATUS_FAILED
            length_ok = False
            if assessment.length_errors or assessment.failure_code == "SCRIPT_REVIEW_LENGTH":
                error_code = "SCRIPT_REVIEW_LENGTH"
            else:
                error_code = "SCRIPT_REVIEW_FAILED"
            logger.warning(
                "文案审稿未通过，不自动过闸 code=%s errors=%s message=%s",
                error_code,
                list(assessment.length_errors),
                assessment.failure_message,
            )
        updated = self._store_gate(
            session,
            version,
            _attempt_gate(
                version,
                status=gate_status,
                length_ok=length_ok,
                length_errors=list(assessment.length_errors),
                error_code=error_code,
                dimensions=dimensions,
                failed_dimensions=list(result.failed_dimensions),
                changed_fields=list(result.changed_fields),
                revised=draft_to_dict(result.revised),
            ),
        )
        return self._review_view(updated)

    def apply_review(self, session: Session, project_id: str, *, action: str) -> ScriptReviewView:
        """应用改写，或明确 ack 保留原稿。未审过当前稿不能过闸。"""
        if action not in {"apply", "ack"}:
            raise ScriptConflictError("action 必须是 apply 或 ack")
        version = self._require_reviewable(session, project_id)
        if is_review_passed(version):
            return self._review_view(version)
        gate = stored_gate(version.facts)
        fingerprint = script_fingerprint(version)
        if not gate.get("attempted") or gate.get("source_fingerprint") != fingerprint:
            raise ScriptReviewRequiredError("请先对当前文案审稿，再应用改写或明确保留原稿")
        if action == "ack":
            updated = self._store_gate(
                session,
                version,
                {
                    **gate,
                    "status": STATUS_PASSED,
                    "decision": "acked",
                    "fingerprint": fingerprint,
                },
            )
            logger.info("审稿闸已通过（保留原稿）project_id=%s", project_id)
            return self._review_view(updated)

        if not gate.get("length_ok") or not isinstance(gate.get("revised"), dict):
            code = str(gate.get("error_code") or "SCRIPT_REVIEW_LENGTH")
            raise ScriptReviewRejectedError("这次审稿的改写不能应用，请明确保留原稿", code=code)
        revised = draft_from_mapping(gate["revised"])
        script_input = _input_from_version(version)
        assessment = assess_revision(draft_from_version(version), revised, script_input)
        if not assessment.ok or assessment.normalized is None:
            code = assessment.failure_code or "SCRIPT_REVIEW_LENGTH"
            raise ScriptReviewRejectedError(
                assessment.failure_message or "改写未通过等长或内容校验",
                code=code,
            )
        normalized = assessment.normalized
        now = self._clock.now()
        demote = version.status == STATUS_CONFIRMED and normalized.full_text != version.full_text
        rewritten = replace(
            version,
            status=STATUS_READY if demote else version.status,
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
            confirmed_at=None if demote else version.confirmed_at,
        )
        passed = self._store_gate(
            session,
            rewritten,
            {
                **gate,
                "status": STATUS_PASSED,
                "decision": "applied",
                "fingerprint": script_fingerprint(rewritten),
                "length_ok": True,
                "length_errors": [],
                "error_code": None,
            },
            demote=demote,
        )
        logger.info("审稿闸已通过（应用改写）project_id=%s", project_id)
        return self._review_view(passed)

    def _require_reviewable(self, session: Session, project_id: str) -> ScriptVersion:
        self._projects.get_project(session, project_id=project_id)
        version = self._repository.latest(session, project_id)
        if version is None:
            raise ScriptNotFoundError("文案版本不存在")
        if version.status not in EDITABLE_STATUSES:
            raise ScriptConflictError("当前文案状态不允许审稿")
        return version

    def _review_view(self, version: ScriptVersion) -> ScriptReviewView:
        mode = get_settings().script_review_gate
        gate = stored_gate(version.facts)
        status = effective_gate_status(version)
        visible = status != "pending"
        revised = gate.get("revised") if visible else None
        length_ok_raw = gate.get("length_ok") if visible else None
        return ScriptReviewView(
            version=version,
            gate_mode=mode,
            gate_status=status,
            decision=gate.get("decision") if status == STATUS_PASSED else None,
            dimensions=dict(gate.get("dimensions") or {}) if visible else {},
            failed_dimensions=list(gate.get("failed_dimensions") or []) if visible else [],
            revised=revised if isinstance(revised, dict) else None,
            changed_fields=list(gate.get("changed_fields") or []) if visible else [],
            length_ok=bool(length_ok_raw) if length_ok_raw is not None else False,
            length_errors=list(gate.get("length_errors") or []) if visible else [],
            error_code=gate.get("error_code") if visible else None,
            blocks_paid_video=mode == GATE_ENFORCE and status != STATUS_PASSED,
        )

    def _store_gate(
        self,
        session: Session,
        version: ScriptVersion,
        gate: dict,
        *,
        demote: bool = False,
    ) -> ScriptVersion:
        updated = replace(version, facts=facts_with_gate(version.facts, gate), updated_at=self._clock.now())
        self._repository.update(session, updated)
        if demote:
            self._pipeline.mark_script_ready(session, version.project_id)
        session.commit()
        return updated

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
            # enforce/warn：生成阶段不自动改写，也不把降级当成过闸。显式接口才写 review_gate。
            # off 且启用时，三个角度仍走原来的增强降级。
            review_enabled = inline_review_enabled(
                enabled=bool(getattr(settings, "script_review_enabled", False)),
                gate=str(getattr(settings, "script_review_gate", GATE_ENFORCE)),
            )
            ready: list[ScriptVersion] = []
            for item in batch:
                angle = (item.facts or {}).get(FACT_ANGLE)
                draft = adapter.generate(
                    image_bytes=image_bytes,
                    mime_type="image/png",
                    script_input=script_input,
                    angle=angle if isinstance(angle, str) else None,
                )
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
