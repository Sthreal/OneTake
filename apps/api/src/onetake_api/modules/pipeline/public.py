from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from typing import Any, Mapping

from sqlalchemy.orm import Session

from onetake_api.modules.pipeline.cost_approval_repository import CostApprovalRepository
from onetake_api.modules.pipeline.domain import (
    STATUS_ASSETS_READY,
    STATUS_FAILED,
    STATUS_INTERRUPTED,
    STATUS_IMAGE_EDITING,
    STATUS_MAIN_IMAGE_CONFIRMED,
    STATUS_MAIN_IMAGE_QUEUED,
    STATUS_MAIN_IMAGE_READY,
    STATUS_MATTING,
    STATUS_RECOGNITION_CONFIRMED,
    STATUS_RECOGNITION_READY,
    STATUS_RECOGNIZING,
    STATUS_SCRIPT_CONFIRMED,
    STATUS_SCRIPT_GENERATING,
    STATUS_SCRIPT_QUEUED,
    STATUS_SCRIPT_READY,
    STATUS_VOICE_GENERATING,
    STATUS_AUDIO_SUBTITLE_CONFIRMED,
    STATUS_CONTENT_PLAN_CONFIRMED,
    STATUS_CONTENT_PLAN_READY,
    STATUS_CONTENT_QA_FAILED,
    STATUS_CONTENT_QA_PASSED,
    STATUS_COMPLETED,
    STATUS_RENDERING,
    STATUS_SUBTITLE_GENERATING,
    STATUS_SUBTITLE_QUEUED,
    STATUS_SUBTITLE_READY,
    STATUS_VIDEO_GENERATING,
    STATUS_VIDEO_PLAN_READY,
    STATUS_VIDEO_READY,
    STATUS_VOICE_QUEUED,
    STATUS_VOICE_READY,
    CostApproval,
    PipelineRun,
)
from onetake_api.modules.pipeline.repository import PipelineRepository
from onetake_api.platform.clock import SystemClock
from onetake_api.platform.errors import DomainError
from onetake_api.platform.ids import new_id


class CostApprovalRequiredError(DomainError):
    """付费动作缺少匹配的费用审批（S8 硬约束）。**409 且不进入供应商调用**。"""

    code = "COST_APPROVAL_REQUIRED"
    http_status = 409
    retryable = False


def cost_payload_hash(payload: Mapping[str, Any]) -> str:
    """把「方案 + 当次预估」折成一个稳定指纹，用于绑定审批。

    * 键序无关（`sort_keys`）→ 同一份预估永远同一个 hash，不会被构造顺序影响；
    * 任何**影响金额**的字段变化都会改变 hash → 旧审批自动失效（防「用 5 元的预估
      批了 50 元的方案」）。
    """
    canonical = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class PipelinePublicService:
    def __init__(self) -> None:
        self._repository = PipelineRepository()
        self._clock = SystemClock()

    def get_or_create(self, session: Session, project_id: str) -> PipelineRun:
        run = self._repository.get(session, project_id)
        if run:
            return run
        now = self._clock.now()
        run = PipelineRun(new_id("run"), project_id, STATUS_ASSETS_READY, 1, 1, now, now)
        self._repository.add(session, run)
        session.flush()
        return run

    def _transition(self, session: Session, project_id: str, status: str, step: int) -> PipelineRun:
        current = self.get_or_create(session, project_id)
        updated = replace(
            current,
            status=status,
            current_step=step,
            state_version=current.state_version + 1,
            updated_at=self._clock.now(),
        )
        self._repository.update(session, updated)
        session.flush()
        return updated

    def mark_assets_ready(self, session: Session, project_id: str) -> PipelineRun:
        return self._transition(session, project_id, STATUS_ASSETS_READY, 1)

    def mark_recognizing(self, session: Session, project_id: str) -> PipelineRun:
        return self._transition(session, project_id, STATUS_RECOGNIZING, 2)

    def mark_recognition_ready(self, session: Session, project_id: str) -> PipelineRun:
        return self._transition(session, project_id, STATUS_RECOGNITION_READY, 2)

    def mark_recognition_confirmed(self, session: Session, project_id: str) -> PipelineRun:
        return self._transition(session, project_id, STATUS_RECOGNITION_CONFIRMED, 2)

    def mark_failed(self, session: Session, project_id: str) -> PipelineRun:
        return self._transition(session, project_id, STATUS_FAILED, 2)

    def mark_main_image_failed(self, session: Session, project_id: str) -> PipelineRun:
        return self._transition(session, project_id, STATUS_FAILED, 3)

    def mark_main_image_queued(self, session: Session, project_id: str) -> PipelineRun:
        return self._transition(session, project_id, STATUS_MAIN_IMAGE_QUEUED, 3)

    def mark_image_editing(self, session: Session, project_id: str) -> PipelineRun:
        return self._transition(session, project_id, STATUS_IMAGE_EDITING, 3)

    def mark_matting(self, session: Session, project_id: str) -> PipelineRun:
        return self._transition(session, project_id, STATUS_MATTING, 3)

    def mark_main_image_ready(self, session: Session, project_id: str) -> PipelineRun:
        return self._transition(session, project_id, STATUS_MAIN_IMAGE_READY, 3)

    def mark_main_image_confirmed(self, session: Session, project_id: str) -> PipelineRun:
        return self._transition(session, project_id, STATUS_MAIN_IMAGE_CONFIRMED, 3)

    def mark_script_queued(self, session: Session, project_id: str) -> PipelineRun:
        return self._transition(session, project_id, STATUS_SCRIPT_QUEUED, 3)

    def mark_script_generating(self, session: Session, project_id: str) -> PipelineRun:
        return self._transition(session, project_id, STATUS_SCRIPT_GENERATING, 3)

    def mark_script_ready(self, session: Session, project_id: str) -> PipelineRun:
        return self._transition(session, project_id, STATUS_SCRIPT_READY, 3)

    def mark_script_confirmed(self, session: Session, project_id: str) -> PipelineRun:
        return self._transition(session, project_id, STATUS_SCRIPT_CONFIRMED, 4)

    def mark_script_failed(self, session: Session, project_id: str) -> PipelineRun:
        return self._transition(session, project_id, STATUS_FAILED, 3)

    def mark_voice_queued(self, session: Session, project_id: str) -> PipelineRun:
        return self._transition(session, project_id, STATUS_VOICE_QUEUED, 4)

    def mark_voice_generating(self, session: Session, project_id: str) -> PipelineRun:
        return self._transition(session, project_id, STATUS_VOICE_GENERATING, 4)

    def mark_voice_ready(self, session: Session, project_id: str) -> PipelineRun:
        return self._transition(session, project_id, STATUS_VOICE_READY, 4)

    def mark_voice_failed(self, session: Session, project_id: str) -> PipelineRun:
        return self._transition(session, project_id, STATUS_FAILED, 4)

    def mark_subtitle_queued(self, session: Session, project_id: str) -> PipelineRun:
        return self._transition(session, project_id, STATUS_SUBTITLE_QUEUED, 4)

    def mark_subtitle_generating(self, session: Session, project_id: str) -> PipelineRun:
        return self._transition(session, project_id, STATUS_SUBTITLE_GENERATING, 4)

    def mark_subtitle_ready(self, session: Session, project_id: str) -> PipelineRun:
        return self._transition(session, project_id, STATUS_SUBTITLE_READY, 4)

    def mark_subtitle_failed(self, session: Session, project_id: str) -> PipelineRun:
        return self._transition(session, project_id, STATUS_FAILED, 4)

    def mark_audio_subtitle_confirmed(self, session: Session, project_id: str) -> PipelineRun:
        return self._transition(session, project_id, STATUS_AUDIO_SUBTITLE_CONFIRMED, 4)

    def mark_video_plan_ready(self, session: Session, project_id: str) -> PipelineRun:
        return self._transition(session, project_id, STATUS_VIDEO_PLAN_READY, 4)

    def mark_video_generating(self, session: Session, project_id: str) -> PipelineRun:
        return self._transition(session, project_id, STATUS_VIDEO_GENERATING, 4)

    def mark_video_ready(self, session: Session, project_id: str) -> PipelineRun:
        return self._transition(session, project_id, STATUS_VIDEO_READY, 4)

    def mark_rendering(self, session: Session, project_id: str) -> PipelineRun:
        return self._transition(session, project_id, STATUS_RENDERING, 4)

    def mark_completed(self, session: Session, project_id: str) -> PipelineRun:
        return self._transition(session, project_id, STATUS_COMPLETED, 4)

    def mark_video_failed(self, session: Session, project_id: str) -> PipelineRun:
        return self._transition(session, project_id, STATUS_FAILED, 4)

    def mark_content_plan_ready(self, session: Session, project_id: str) -> PipelineRun:
        return self._transition(session, project_id, STATUS_CONTENT_PLAN_READY, 4)

    def mark_content_plan_confirmed(self, session: Session, project_id: str) -> PipelineRun:
        return self._transition(session, project_id, STATUS_CONTENT_PLAN_CONFIRMED, 4)

    def mark_content_qa_passed(self, session: Session, project_id: str) -> PipelineRun:
        return self._transition(session, project_id, STATUS_CONTENT_QA_PASSED, 4)

    def mark_content_qa_failed(self, session: Session, project_id: str) -> PipelineRun:
        return self._transition(session, project_id, STATUS_CONTENT_QA_FAILED, 4)

    # ---- S8/S9/S10：自动链的断点、审计与「被打断」终态 ----
    # 手写在这里（不走 `_transition`）是因为它们不改变 status 语义：`stage`/`auto_run`/
    # `auto_confirmed_stages` 是**附加在状态机旁边的编排元数据**，与 status 正交。

    def mark_auto_run(self, session: Session, project_id: str, *, stage: str | None = None) -> PipelineRun:
        """标记「这一轮是自动链在跑」，并记下断点阶段（S9 续跑用）。"""
        current = self.get_or_create(session, project_id)
        updated = replace(
            current,
            auto_run=True,
            stage=stage if stage is not None else current.stage,
            state_version=current.state_version + 1,
            updated_at=self._clock.now(),
        )
        self._repository.update(session, updated)
        session.flush()
        return updated

    def mark_auto_gate_confirmed(self, session: Session, project_id: str, stage: str) -> PipelineRun:
        """记录一次**系统自动放行**的闸口。**人工确认不写这里** —— 只有这样，
        `auto_confirmed_stages` 才能用来回答「这一段是机器放行的吗」。"""
        current = self.get_or_create(session, project_id)
        stages = list(current.auto_confirmed_stages)
        if stage not in stages:
            stages.append(stage)
        updated = replace(
            current,
            auto_confirmed_stages=stages,
            state_version=current.state_version + 1,
            updated_at=self._clock.now(),
        )
        self._repository.update(session, updated)
        session.flush()
        return updated

    def mark_interrupted(self, session: Session, project_id: str) -> PipelineRun:
        """自动链中途随进程一起死掉 → 标成 `interrupted`（不是 `failed`，也不是永久 running）。"""
        return self._transition(session, project_id, STATUS_INTERRUPTED, self.get_or_create(session, project_id).current_step)

    # ---- S8：费用审批（付费动作的唯一闸口）----
    # 放在**入口**而非推进器内部：人工点击、自动链、MCP 都走同一道闸，不存在绕行路径。

    def require_cost_approval(self, session: Session, *, project_id: str, plan_id: str,
                              estimated_cny: float, payload_hash: str) -> CostApproval:
        """没有匹配 `(project_id, plan_id, payload_hash)` 的审批记录 → 抛 409，**不进入付费动作**。"""
        approval = CostApprovalRepository().find(
            session, project_id=project_id, plan_id=plan_id, payload_hash=payload_hash
        )
        if approval is None:
            raise CostApprovalRequiredError(
                f"该操作预计产生 {estimated_cny:.2f} 元费用，需先提交费用审批（改过方案后需重新审批）"
            )
        return approval

    def approve_cost(self, session: Session, *, project_id: str, plan_id: str, estimated_cny: float,
                     payload_hash: str, approved_by: str) -> CostApproval:
        """登记一次「批准花钱」。同一份预估重复批准是幂等的（返回既有记录，不重复落行）。"""
        repository = CostApprovalRepository()
        existing = repository.find(session, project_id=project_id, plan_id=plan_id, payload_hash=payload_hash)
        if existing is not None:
            return existing
        approval = CostApproval(
            id=new_id("cap"),
            project_id=project_id,
            plan_id=plan_id,
            estimated_cny=estimated_cny,
            payload_hash=payload_hash,
            approved_by=approved_by,
            approved_at=self._clock.now(),
        )
        repository.add(session, approval)
        session.flush()
        return approval

    def list_cost_approvals(self, session: Session, project_id: str) -> list[CostApproval]:
        return CostApprovalRepository().list_for_project(session, project_id)
