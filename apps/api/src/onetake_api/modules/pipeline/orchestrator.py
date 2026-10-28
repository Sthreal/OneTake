"""流水线推进器（S8 + S9 + S10 的**唯一**实现）。

**为什么只有一个文件**：总方案 §4.3 判定 S8（闸口自动放行）、S9（一键编排 + 断点续跑）、
S10（失败分类与恢复）**是同一件事** —— 「读阶段目录，决定下一步做什么」。分别实现就是新的
「同一件事两处实现」，正是 §1.4 要消除的形态。三者因此共用本模块。

**它不写 status**：`modules/pipeline/public.py` 的 `mark_*` 仍是状态机唯一写入口。本模块只
**调用**它，以及调用各模块既有的 `request / process_job / confirm` —— 与 rq worker 调的是
同一批函数，于是 `idempotency_key` 天然复用，续跑不会重复计费。

**它不碰前端**（总方案 §6 第 4 行：前端切片去掉、前端将重做），也不绕过 `MOCK_PROVIDERS`。
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass

from sqlalchemy.orm import Session

from onetake_api.config import get_settings
from onetake_api.modules.job.public import JobPublicService
from onetake_api.modules.main_image.domain import STATUS_CONFIRMED as MAIN_IMAGE_CONFIRMED
from onetake_api.modules.main_image.domain import STATUS_READY as MAIN_IMAGE_READY
from onetake_api.modules.main_image.domain import STATUS_FAILED as MAIN_IMAGE_FAILED
from onetake_api.modules.main_image.public import MainImagePublicService
from onetake_api.modules.outbox.public import OutboxPublicService
from onetake_api.modules.pipeline.domain import (
    STATUS_COMPLETED,
    STATUS_FAILED,
    STATUS_INTERRUPTED,
    PipelineRun,
)
from onetake_api.modules.pipeline.public import PipelinePublicService
from onetake_api.modules.pipeline.repository import PipelineRepository
from onetake_api.modules.pipeline.stage_catalog import (
    HUMAN_GATES,
    STAGE_BY_NAME,
    STAGE_NAMES,
    STAGES,
    StageSpec,
    get_stage,
    human_gate_after,
    stages_from,
    validate_catalog,
)
from onetake_api.modules.project.public import ProjectPublicService
from onetake_api.modules.recognition.domain import RUN_CONFIRMED as RECOGNITION_CONFIRMED
from onetake_api.modules.recognition.domain import RUN_READY as RECOGNITION_READY
from onetake_api.modules.recognition.domain import RUN_FAILED as RECOGNITION_FAILED
from onetake_api.modules.recognition.service import RecognitionService
from onetake_api.modules.script.domain import STATUS_CONFIRMED as SCRIPT_CONFIRMED
from onetake_api.modules.script.domain import STATUS_READY as SCRIPT_READY
from onetake_api.modules.script.domain import STATUS_FAILED as SCRIPT_FAILED
from onetake_api.modules.script.public import ScriptPublicService
from onetake_api.modules.subtitle.domain import SUBTITLE_CONFIRMED, SUBTITLE_READY
from onetake_api.modules.subtitle.public import SubtitlePublicService
from onetake_api.modules.video_plan.public import VideoPlanPublicService
from onetake_api.modules.voice.domain import VOICE_FAILED
from onetake_api.modules.voice.public import VoicePublicService
from onetake_api.platform.clock import SystemClock
from onetake_api.platform.errors import ERROR_POLICY, DomainError, resolve_error_policy
from onetake_api.platform.queue import get_queue

logger = logging.getLogger(__name__)

# 单个阶段内最多推进几步（触发 + 逐个子任务落地）。纯粹是防死循环的上限：正常路径远小于它，
# 超限说明有 job 卡在中间态 —— 交给人工，比静默空转诚实。
MAX_STAGE_STEPS = 12

# 「队列里已经有 worker 在消费」时，推进器**不自己处理 job**，而是等 worker 跑完再往下走。
# 为什么必须这样（实测缺陷）：内联处理与 rq worker 会**抢同一个 job** —— 两个进程都看到 queued
# 就都会去调供应商，于是同一次生成产生**两次付费调用**（真实配置下实测：阿里去背被重复调用一次），
# worker 侧还会留下一串「任务不存在或不可执行」的报错。
# 上限：等待外部 worker 的最长时间（秒）。超时不算失败 —— 阶段停在 not_ready/external_worker，
# 由调用方稍后重试（自动链本身是幂等的）。
EXTERNAL_WORKER_WAIT_SECONDS = 150.0
EXTERNAL_WORKER_POLL_SECONDS = 0.5

# 自动链使用的默认配音参数（音色与前端 VoicePanel 的默认一致）。
# 自动链的默认音色来自配置（`AUTO_RUN_VOICE_ID`）——真实 CosyVoice 的音色 ID 与 mock 不同，
# 硬编码会让真实配置**必然卡在配音段**（实测：cosyvoice-v2 + longxiaochun → 418 InvalidParameter）。
AUTO_VOICE_LANGUAGE = "zh"
AUTO_VOICE_SPEED = 1.0

# 终态：走到这里不会再变（孤儿检测据此排除）。
TERMINAL_STATUSES = frozenset({STATUS_COMPLETED, STATUS_FAILED, STATUS_INTERRUPTED})

# ---- 进程内注册表（S10 孤儿检测的另一半）----
# 纯 DB 分不出「真在跑」与「进程已死」；纯内存分不出跨进程。两半交叉才判得出孤儿：
# DB 里标了 auto_run、却不在本进程注册表里 → 说明进程已经死过一次 → 标 interrupted。
RUNNING_RUNS: set[str] = set()

# 「请在下个阶段边界停下」的请求（`POST /auto-runs/{id}/stop`）。
# 自动链是同步执行的，硬中断会留下半个事务 —— 所以停止做成**协作式**：跑着的那一轮
# 在每个阶段开头检查一次，干净地停在阶段边界。
STOP_REQUESTED: set[str] = set()

# 每个阶段按什么顺序抽干 job（与各 worker_tasks 的派发一一对应）。
# main_image 的三段子 job 的 job_type 并不互不相同（image_edit / matting / main_image），
# 所以只能按这个固定顺序找「当前活跃的那一个」，而不是靠 job_type 反推阶段。
_JOB_ORDER: dict[str, tuple[str, ...]] = {
    "recognition": ("recognition",),
    "main_image": ("image_edit", "matting", "main_image"),
    "script": ("script",),
    "voice_subtitle": ("voice", "subtitle"),
}

# 视频块：这三段的花费由**方案级**预估统一给出（关键帧 + i2v + 合成），
# 所以预算只在这块**入口**比对一次 —— 逐段相加会把同一笔钱数三次。
_VIDEO_BLOCK = ("keyframes", "segments", "render_compose")

# 只有这四段有自动驱动器（中间免费段）。视频段（关键帧 / 分段 / 合成）在人工闸口②之后，
# 必须走既有的 6 个付费入口 + 费用审批，不在自动链内自行触发。
_DRIVEN_STAGES = frozenset(_JOB_ORDER)

_GATE_BY_NAME = {gate.name: gate for gate in HUMAN_GATES}


def _queue_has_worker() -> bool:
    """队列里是否已经有 rq worker 在消费（有则推进器**不自己处理 job**）。

    只读探测：查 rq 的 worker 注册表（`rq:workers` 集合）。探测本身失败（例如 redis 不可用）
    一律**当作没有 worker** —— 退回"内联驱动"这条被测试覆盖的路径，而不是让自动链停摆。
    """
    try:
        connection = get_queue("pipeline-probe").connection
        return bool(connection.smembers("rq:workers"))
    except Exception:  # pragma: no cover - redis 不可用时的保守回退
        return False


def _build_status_rank() -> dict[str, int]:
    """pipeline status → 属于第几段。**派生自阶段目录**（不是另写一张表）。

    未在目录里声明的状态（assets_ready / failed / interrupted / 未知值）一律没有条目，
    取值时按 0 处理。
    """
    table: dict[str, int] = {}
    for spec in STAGES:
        for item in (spec.enter_status, spec.ready_status, spec.confirm_status, *spec.extra_statuses):
            if item:
                table[item] = max(table.get(item, 0), spec.order)
    return table


_STATUS_RANK = _build_status_rank()


class PipelineOrchestrationError(DomainError):
    """推进器自身的编排错误（阶段目录不一致、驱动器缺失等）。"""

    code = "PIPELINE_ORCHESTRATION_ERROR"
    http_status = 409
    retryable = False


class AutoRunDisabledError(DomainError):
    """自动链未启用（`AUTO_RUN_ENABLED=false`）。默认关闭是**安全默认**，不是故障。"""

    code = "AUTO_RUN_DISABLED"
    http_status = 403
    retryable = False


class PipelineConflictError(DomainError):
    """并发冲突：同项目已有自动链在跑、或指定的 run 已被替换。**抛出前不写任何东西**。"""

    code = "PIPELINE_CONFLICT"
    http_status = 409
    retryable = True


@dataclass(frozen=True)
class AdvanceResult:
    run_id: str
    auto_confirmed: list[str]      # 本轮由**系统**自动放行的阶段（同步写进 auto_confirmed_stages）
    stopped_at: str | None         # 停在哪里（阶段名或闸口名）
    stopped_reason: str | None     # human_gate | not_ready | unsupported | budget | stopped | failed:<action>
    required_action: str | None = None   # 停下后**需要人做什么**（如 budget → require_human）
    auto_run: bool = True


@dataclass(frozen=True)
class RecoveryDecision:
    error_code: str
    error_class: str
    action: str
    stage: str | None


class PipelineOrchestrator:
    """唯一的推进器。所有方法都**只调用既有入口**，绝不自己写 status。"""

    def __init__(self) -> None:
        validate_catalog()
        self._projects = ProjectPublicService()
        self._pipeline = PipelinePublicService()
        self._repository = PipelineRepository()
        self._outbox = OutboxPublicService()
        self._jobs = JobPublicService()
        self._recognition = RecognitionService()
        self._main_images = MainImagePublicService()
        self._scripts = ScriptPublicService()
        self._video_plans = VideoPlanPublicService()
        self._voices = VoicePublicService()
        self._subtitles = SubtitlePublicService()
        self._clock = SystemClock()
        # 最近一次推进是否因为「等外部 worker」而停下（决定停止原因怎么写）
        self._waited_external = False
        # 最近一次推进是否撞上「永久性失败」（决定停止原因：交人工，而不是重试）
        self._blocked_permanent: str | None = None
        # 本轮已自动重跑过的阶段（每个阶段最多重跑一次，防止无限重试烧钱）
        self._retried_stages: set[str] = set()

    # ------------------------------------------------------------------ S8
    def advance_gates(self, session: Session, project_id: str, *, run_id: str | None = None) -> AdvanceResult:
        """S8：把「已就绪、且不是人工闸口」的阶段依次自动确认。

        **只放行已经就绪的阶段**；遇到人工闸口（内容规划 / 视频方案+费用 / 交付门）立即停下，
        绝不代按。每次自动放行都追加 `auto_confirmed_stages` 并落 outbox `GateAutoConfirmed`。
        """
        run = self._require_run(session, project_id, run_id)
        start = run.stage or STAGE_NAMES[0]
        return self._walk(session, project_id, run, start_stage=start, drive=False, budget_cny=None)

    # ------------------------------------------------------------------ S9
    def resume_from_stage(self, session: Session, project_id: str, from_stage: str, *,
                          run_id: str | None = None, budget_cny: float | None = None) -> AdvanceResult:
        """S9：一键编排 + 断点续跑 —— 从 `from_stage` 起把中间段自动跑完。

        触发动作走各模块既有的 `request`，落地走既有的 `process_job`（与 worker 同一批函数），
        因此 `idempotency_key` 与 `find_active` 天然防重复计费：第二遍跑同一条链不会重新调用
        供应商，只会重放「已就绪 → 自动确认」这一步。
        """
        get_stage(from_stage)  # 未知阶段：明确报错，不静默从头跑
        settings = get_settings()
        if not settings.auto_run_enabled:
            raise AutoRunDisabledError("自动链未启用（AUTO_RUN_ENABLED=false），需显式开启后才能一键跑")
        budget = settings.auto_run_budget_cny if budget_cny is None else budget_cny
        run = self._require_run(session, project_id, run_id)
        self._acquire(run)
        STOP_REQUESTED.discard(run.id)
        self._retried_stages.clear()
        try:
            run = self._pipeline.mark_auto_run(session, project_id, stage=from_stage)
            session.commit()
            result = self._walk(session, project_id, run, start_stage=from_stage, drive=True, budget_cny=budget)
        finally:
            RUNNING_RUNS.discard(run.id)
            STOP_REQUESTED.discard(run.id)
        # 记断点：停下时 `stage` 指向「下次该从哪里继续」（闸口名也是合法阶段锚点）
        breakpoint_stage = result.stopped_at or stages_from(from_stage)[-1].name
        self._pipeline.mark_auto_run(session, project_id, stage=breakpoint_stage)
        session.commit()
        return result

    # ----------------------------------------------------------------- S10
    def recover_from_failure(self, session: Session, project_id: str, error: Exception, *,
                             stage: str | None = None) -> RecoveryDecision:
        """S10：按**错误类别**决定动作，而不是一律终止。

        分类的权威来源是 `platform.errors.ERROR_POLICY`（错误码 → 分类/动作）。**未登记的码**
        才回落到该阶段的默认动作（`StageSpec.default_recover_action`）。
        `error_class` **不落库**（待拍板第 6 项）：只进日志与 outbox payload。
        """
        code = getattr(error, "code", "INTERNAL_ERROR")
        error_class, action = resolve_error_policy(code)
        spec = STAGE_BY_NAME.get(stage) if stage else None
        if code not in ERROR_POLICY and spec is not None:
            # 新码 / 未登记码：用阶段默认动作，比全局默认更贴合这一段失败的真实后果
            action = spec.default_recover_action
        decision = RecoveryDecision(error_code=code, error_class=error_class, action=action, stage=stage)
        self._outbox.enqueue(
            session,
            event_name="PipelineFailureClassified",
            aggregate_type="pipeline_run",
            aggregate_id=f"{project_id}:{stage or '-'}",
            occurred_at=self._clock.now(),
            payload={
                "project_id": project_id,
                "stage": stage,
                "error_code": code,
                "error_class": error_class,
                "action": action,
            },
        )
        session.commit()
        return decision

    def detect_orphans(self, session: Session) -> list[str]:
        """S10：把「DB 说在跑、本进程却没在跑」的自动 run 标成 `interrupted`。

        进程注册表 + DB 非终态交叉判定。返回被标记的 run id（供 API / 运维查看）。
        """
        orphans: list[str] = []
        for run in self._repository.list_in_flight(session):
            if run.id in RUNNING_RUNS:
                continue
            self._pipeline.mark_interrupted(session, run.project_id)
            self._outbox.enqueue(
                session,
                event_name="AutoRunInterrupted",
                aggregate_type="pipeline_run",
                aggregate_id=run.id,
                occurred_at=self._clock.now(),
                payload={"project_id": run.project_id, "stage": run.stage},
            )
            orphans.append(run.id)
        if orphans:
            session.commit()
        return orphans

    # ------------------------------------------------------------- 内部：走链
    def _walk(self, session: Session, project_id: str, run: PipelineRun, *,
              start_stage: str, drive: bool, budget_cny: float | None = None) -> AdvanceResult:
        confirmed: list[str] = []
        stopped_at: str | None = None
        stopped_reason: str | None = None
        required_action: str | None = None
        for spec in stages_from(start_stage):
            if run.id in STOP_REQUESTED:
                stopped_at, stopped_reason = spec.name, "stopped"
                break
            if spec.human_gate:
                gate = _GATE_BY_NAME.get(spec.name)
                if gate is not None and self._gate_passed(session, project_id, gate):
                    continue  # 闸口已由人放行 → 继续往下（但不代按）
                stopped_at, stopped_reason = spec.name, "human_gate"
                break

            if drive and budget_cny is not None and spec.name in _VIDEO_BLOCK:
                cost = self._video_block_cost(session, project_id)
                if cost > budget_cny:
                    self._record_budget_stop(session, project_id, run, spec.name, cost, budget_cny)
                    stopped_at, stopped_reason, required_action = spec.name, "budget", "require_human"
                    break

            if drive:
                try:
                    if not self._drive_stage(session, project_id, spec):
                        if spec.name not in _DRIVEN_STAGES:
                            reason = "unsupported"
                        elif self._waited_external:
                            reason = "external_worker"
                        elif self._blocked_permanent:
                            reason = "failed:require_human"
                            required_action = "require_human"
                        else:
                            reason = "not_ready"
                        stopped_at, stopped_reason = spec.name, reason
                        break
                except DomainError as exc:
                    decision = self.recover_from_failure(session, project_id, exc, stage=spec.name)
                    logger.warning(
                        "auto run stage failed",
                        extra={"project_id": project_id, "stage": spec.name,
                               "error_code": decision.error_code, "action": decision.action},
                    )
                    stopped_at, stopped_reason = spec.name, f"failed:{decision.action}"
                    break
            elif not self._stage_done(session, project_id, spec):
                stopped_at, stopped_reason = spec.name, "not_ready"
                break

            if self._confirm_stage(session, project_id, spec):
                self._record_auto_confirm(session, project_id, run, spec.name)
                confirmed.append(spec.name)

            gate = human_gate_after(spec.name)
            if gate is not None and not self._gate_passed(session, project_id, gate):
                stopped_at, stopped_reason = gate.name, "human_gate"
                break
        return AdvanceResult(
            run_id=run.id, auto_confirmed=confirmed, stopped_at=stopped_at,
            stopped_reason=stopped_reason, required_action=required_action,
        )

    def _gate_passed(self, session: Session, project_id: str, gate) -> bool:
        """闸口是不是已经被人放行了（放行 ≠ 推进器代按）。"""
        if gate is None:
            return False
        if gate.name == "content_plan":
            status = self._pipeline.get_or_create(session, project_id).status
            return _STATUS_RANK.get(status, 0) > get_stage(gate.after_stage).order
        # 闸口②（费用审批）与闸口③（交付门）都不由推进器代按：前者要 cost_approvals 记录，
        # 后者要 gate_acks。一律返回 False → 自动链停在这里等人。
        return False

    # --------------------------------------------------------- 内部：驱动器
    def _drive_stage(self, session: Session, project_id: str, spec: StageSpec) -> bool:
        """把一段的产出做到就绪。返回是否就绪（False = 卡住 / 没有驱动器）。"""
        self._blocked_permanent = None
        if spec.name not in _DRIVEN_STAGES:
            return False
        if self._stage_done(session, project_id, spec):
            return True
        for _ in range(MAX_STAGE_STEPS):
            if self._stage_done(session, project_id, spec):
                return True
            if not self._step_stage(session, project_id, spec):
                break
        return self._stage_done(session, project_id, spec)

    def _step_stage(self, session: Session, project_id: str, spec: StageSpec) -> bool:
        """推进一步（触发一次请求，或落地一个活跃 job）。返回是否真的推进了。

        **三种产物状态各有处置**（这是"断点续跑"能覆盖真实失败的关键）：
        - 产物不存在 → 触发；
        - 产物存在但**失败**且错误码是 `transient/retry` → **重跑一次**（否则"失败即报废"，
          用户只能换项目重来）；
        - 产物存在但失败且错误码是**永久性**（例如供应商未配置）→ **不重跑**，交人工
          （真实付费链路上盲目重试 = 白花钱）。
        """
        if spec.name == "recognition":
            run, _candidates = self._recognition.latest(session, project_id)
            if run is None:
                self._recognition.request(session, project_id)
                return True
            if self._needs_retry(run.status == RECOGNITION_FAILED, run.error_code, spec.name):
                self._recognition.request(session, project_id)
                return True
            return self._drain_one(session, project_id, "recognition")

        if spec.name == "main_image":
            view = self._main_images.latest(session, project_id)
            if view is None:
                self._main_images.request(session, project_id)
                return True
            if self._needs_retry(view.version.status == MAIN_IMAGE_FAILED, view.version.error_code, spec.name):
                self._main_images.request(session, project_id)
                return True
            return self._drain_one(session, project_id, "main_image")

        if spec.name == "script":
            version = self._scripts.latest(session, project_id).version
            if version is None:
                project = self._projects.get_project(session, project_id=project_id)
                self._scripts.request(session, project_id=project_id, **_auto_script_inputs(project))
                return True
            if self._needs_retry(version.status == SCRIPT_FAILED, version.error_code, spec.name):
                project = self._projects.get_project(session, project_id=project_id)
                self._scripts.request(session, project_id=project_id, **_auto_script_inputs(project))
                return True
            return self._drain_one(session, project_id, "script")

        if spec.name == "voice_subtitle":
            voice = self._voices.latest(session, project_id).run
            if voice is None:
                self._request_voice(session, project_id)
                return True
            if self._needs_retry(voice.status == VOICE_FAILED, voice.error_code, spec.name):
                self._request_voice(session, project_id)
                return True
            return self._drain_one(session, project_id, "voice_subtitle")

        return False

    def _request_voice(self, session: Session, project_id: str) -> None:
        self._voices.request(
            session,
            project_id=project_id,
            enabled=True,
            subtitle_enabled=True,
            voice_id=get_settings().auto_run_voice_id,
            language=AUTO_VOICE_LANGUAGE,
            speed=AUTO_VOICE_SPEED,
        )

    def _needs_retry(self, failed: bool, error_code: str | None, stage: str) -> bool:
        """产物失败了要不要自动重跑？

        两条硬规则（都是钱相关的）：
        1. **只有 `ERROR_POLICY` 判为 `transient/retry` 才重跑** —— 永久性失败（供应商未配置、参数非法…）
           重跑只会再失败一次，在真实付费链路上就是白花钱；
        2. **每个阶段最多自动重跑一次**（`self._retried_stages`）—— 否则一旦 `request` 没能真的产出新产物
           （冲突、上游拒绝…），`_drive_stage` 的循环会把重试打到步数上限（实测：12 次付费尝试）。
           重试过仍失败 → 停手交人工。
        """
        if not failed:
            return False
        error_class, action = resolve_error_policy(error_code or "")
        if error_class == "transient" and action == "retry" and stage not in self._retried_stages:
            self._retried_stages.add(stage)
            logger.info("auto run retrying failed stage", extra={"stage": stage, "error_code": error_code})
            return True
        # 永久性失败，或「已经重试过一次还是失败」→ 都交人工，不再自动花钱
        self._blocked_permanent = error_code or "UNKNOWN"
        return False

    def _drain_one(self, session: Session, project_id: str, stage: str) -> bool:
        """按固定顺序找到该阶段「当前活跃的那个 job」并落地它。

        **两条路，按环境自动选**：
        - 队列里**没有** worker（开发 / 测试 / 单进程）→ 就地同步处理（与 rq worker 调同一批函数）；
        - 队列里**有** worker（真实部署）→ **绝不处理**，只等它跑完。
          否则两个进程会抢同一个 job 并**各调一次供应商**（实测：阿里去背被重复付费调用一次）。

        `self._waited_external` 记录"这次是因为等外部 worker 而停下"，供 `_walk` 给出如实的停止原因。
        """
        self._waited_external = False
        for job_type in _JOB_ORDER[stage]:
            job = self._jobs.find_active(session, project_id, job_type)
            if job is None:
                continue
            if _queue_has_worker():
                # 已被 worker 领走（或马上会被领走）→ 等它到终态，绝不重复处理
                if not self._wait_for_external_job(session, job.id):
                    self._waited_external = True
                return True
            if job_type == "recognition":
                self._recognition.process_job(session, job.id)
            elif job_type == "image_edit":
                self._main_images.process_image_edit_job(session, job.id)
            elif job_type == "matting":
                self._main_images.process_matting_job(session, job.id)
            elif job_type == "main_image":
                self._main_images.process_finalize_job(session, job.id)
            elif job_type == "script":
                self._scripts.process_job(session, job.id)
            elif job_type == "voice":
                self._voices.process_job(session, job.id)
            elif job_type == "subtitle":
                self._subtitles.process_job(session, job.id)
            else:  # pragma: no cover - _JOB_ORDER 是封闭集合
                raise PipelineOrchestrationError(f"未知 job_type：{job_type}")
            return True
        return False

    def _wait_for_external_job(self, session: Session, job_id: str) -> bool:
        """等外部 worker 把该 job 跑到终态。返回是否**在超时前**到达终态。

        每轮 `expire_all()` 让会话丢掉陈旧的身份映射，才能看到 worker 在**另一个会话**里提交的状态。
        """
        deadline = time.monotonic() + EXTERNAL_WORKER_WAIT_SECONDS
        while time.monotonic() < deadline:
            session.expire_all()
            job = self._jobs.get(session, job_id)
            if job is None or job.status in {"succeeded", "failed"}:
                return True
            time.sleep(EXTERNAL_WORKER_POLL_SECONDS)
        logger.warning(
            "auto run waited for external worker and timed out",
            extra={"job_id": job_id, "waited_seconds": EXTERNAL_WORKER_WAIT_SECONDS},
        )
        return False

    def _stage_done(self, session: Session, project_id: str, spec: StageSpec) -> bool:
        """该阶段的产出是否已经就绪**或已确认**（已确认也算完成，续跑不得再触发一次）。"""
        if spec.name == "recognition":
            run, _candidates = self._recognition.latest(session, project_id)
            return run is not None and run.status in {RECOGNITION_READY, RECOGNITION_CONFIRMED}
        if spec.name == "main_image":
            view = self._main_images.latest(session, project_id)
            return view is not None and view.version.status in {MAIN_IMAGE_READY, MAIN_IMAGE_CONFIRMED}
        if spec.name == "script":
            version = self._scripts.latest(session, project_id).version
            return version is not None and version.status in {SCRIPT_READY, SCRIPT_CONFIRMED}
        if spec.name == "voice_subtitle":
            subtitle = self._subtitles.latest(session, project_id)
            return subtitle is not None and subtitle.status in {SUBTITLE_READY, SUBTITLE_CONFIRMED}
        return False

    # --------------------------------------------------------- 内部：自动确认
    def _confirm_stage(self, session: Session, project_id: str, spec: StageSpec) -> bool:
        """代按这一段的确认。返回是否真的按了（False = 还没就绪 / 已确认 / 不归系统按）。"""
        if spec.name == "recognition":
            run, candidates = self._recognition.latest(session, project_id)
            if run is None or run.status != RECOGNITION_READY or not candidates:
                return False
            # 自动链取**置信度最高**的候选；识别不出唯一主体时仍会走到这里，
            # 但仍保留人工复核入口（闸口①之前不产生任何付费动作）。
            chosen = max(candidates, key=lambda item: (item.confidence, item.created_at))
            self._recognition.confirm(session, project_id, run.id, chosen.id)
            return True
        if spec.name == "main_image":
            view = self._main_images.latest(session, project_id)
            if view is None or view.version.status != MAIN_IMAGE_READY:
                return False
            self._main_images.confirm(session, project_id)
            return True
        if spec.name == "script":
            version = self._scripts.latest(session, project_id).version
            if version is None or version.status != SCRIPT_READY:
                return False
            # 自动链可以代按「文案已确认」，但不会替人 ack 审稿闸。
            # 付费视频入口仍要 apply/ack；这里若强制闸门，免费/mock 链会停在文案。
            self._scripts.confirm(session, project_id, enforce_review_gate=False)
            return True
        if spec.name == "voice_subtitle":
            subtitle = self._subtitles.latest(session, project_id)
            if subtitle is None or subtitle.status != SUBTITLE_READY:
                return False
            # 与 `modules/audio_subtitle/api.py` 的 /confirm 是同一组三步调用（该文件的逻辑
            # 没有可复用的 public 入口，本切片清单也不含它，故按同一顺序复刻）。
            self._voices.confirm(session, project_id)
            self._subtitles.confirm(session, project_id)
            self._pipeline.mark_audio_subtitle_confirmed(session, project_id)
            session.commit()
            return True
        return False

    # --------------------------------------------------------- 内部：成本护栏
    def _video_block_cost(self, session: Session, project_id: str) -> float:
        """视频块（关键帧 / 分段 / 合成）在当前配置下的预估总花费（元）。

        用**方案级**预估（`estimate_video_generation` 已把关键帧 + i2v + 合成算在一起），
        免费 / mock 或还没有方案时为 0。
        """
        view = self._video_plans.latest(session, project_id)
        if view.plan is None:
            return 0.0
        estimate = self._video_plans.estimate(session, project_id=project_id, plan_id=view.plan.id)
        return estimate.estimated_known_cost if estimate.is_paid else 0.0

    def _record_budget_stop(self, session: Session, project_id: str, run: PipelineRun,
                            stage: str, cost: float, budget: float) -> None:
        self._outbox.enqueue(
            session,
            event_name="AutoRunBudgetStopped",
            aggregate_type="pipeline_run",
            aggregate_id=run.id,
            occurred_at=self._clock.now(),
            payload={
                "project_id": project_id,
                "stage": stage,
                "estimated_cny": cost,
                "budget_cny": budget,
                "action": "require_human",
            },
        )
        session.commit()

    def _record_auto_confirm(self, session: Session, project_id: str, run: PipelineRun, stage: str) -> None:
        self._pipeline.mark_auto_gate_confirmed(session, project_id, stage)
        self._outbox.enqueue(
            session,
            event_name="GateAutoConfirmed",
            aggregate_type="pipeline_run",
            aggregate_id=run.id,
            occurred_at=self._clock.now(),
            payload={"project_id": project_id, "stage": stage, "auto": True},
        )
        session.commit()

    # --------------------------------------------------------------- 内部：锁
    def _require_run(self, session: Session, project_id: str, run_id: str | None) -> PipelineRun:
        self._projects.get_project(session, project_id=project_id)  # 不存在 → 404
        run = self._pipeline.get_or_create(session, project_id)
        if run_id is not None and run.id != run_id:
            raise PipelineConflictError("流水线运行不存在或已被替换")
        return run

    def request_stop(self, run_id: str) -> bool:
        """请求停止一轮自动链。返回**当时是否真的在跑**（False = 没有可停的）。

        只有真正在跑的那一轮才登记 —— 否则请求会一直挂在集合里（泄漏）。
        """
        in_flight = run_id in RUNNING_RUNS
        if in_flight:
            STOP_REQUESTED.add(run_id)
        return in_flight

    def is_in_flight(self, run_id: str) -> bool:
        return run_id in RUNNING_RUNS

    def _acquire(self, run: PipelineRun) -> None:
        if run.id in RUNNING_RUNS:
            raise PipelineConflictError("该项目已有一条自动链在运行")
        RUNNING_RUNS.add(run.id)


def _auto_script_inputs(project) -> dict:
    """自动链生成文案所需的显式输入（人工路径由前端表单提供）。

    从 `project.product_name / product_note` 派生，仅作为**自动链的默认值**；各字段仍满足
    `script.content.normalize_input` 的长度约束，不绕过校验。
    """
    name = project.product_name
    note = (project.product_note or "").strip()
    if len(note) >= 2:
        pain_point = note
        selling_points = [note]
    else:
        # 兜底**不能假设品类形态**：曾经写死「{name}用起来不太顺手」，落到饮料/食品上就成了
        # 「用起来不太顺手的饮料」（2026-10-15 用户实测）。这里改成品类无关的中性表达，
        # 真正的痛点交给文案模型按识别出的品类（facts）自行落地。
        pain_point = f"想买{name}的人，挑起来容易纠结"
        selling_points = [f"{name} 的主要优点"]
    return {
        "pain_point": pain_point[:80],
        "selling_points": [item[:80] for item in selling_points[:5]],
        "usage_scenario": f"日常场景使用{name}"[:100],
        "offer": None,
    }