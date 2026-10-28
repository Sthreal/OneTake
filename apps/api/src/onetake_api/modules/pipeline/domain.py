from dataclasses import dataclass, field
from datetime import datetime

STATUS_ASSETS_READY = "assets_ready"
STATUS_RECOGNIZING = "recognizing"
STATUS_RECOGNITION_READY = "recognition_ready"
STATUS_RECOGNITION_CONFIRMED = "recognition_confirmed"
STATUS_MAIN_IMAGE_QUEUED = "main_image_queued"
STATUS_IMAGE_EDITING = "image_editing"
STATUS_MATTING = "matting"
STATUS_MAIN_IMAGE_READY = "main_image_ready"
STATUS_MAIN_IMAGE_CONFIRMED = "main_image_confirmed"
STATUS_SCRIPT_QUEUED = "script_queued"
STATUS_SCRIPT_GENERATING = "script_generating"
STATUS_SCRIPT_READY = "script_ready"
STATUS_SCRIPT_CONFIRMED = "script_confirmed"
STATUS_VOICE_QUEUED = "voice_queued"
STATUS_VOICE_GENERATING = "voice_generating"
STATUS_VOICE_READY = "voice_ready"
STATUS_SUBTITLE_QUEUED = "subtitle_queued"
STATUS_SUBTITLE_GENERATING = "subtitle_generating"
STATUS_SUBTITLE_READY = "subtitle_ready"
STATUS_AUDIO_SUBTITLE_CONFIRMED = "audio_subtitle_confirmed"
STATUS_CONTENT_PLAN_READY = "content_plan_ready"
STATUS_CONTENT_PLAN_CONFIRMED = "content_plan_confirmed"
STATUS_CONTENT_QA_PASSED = "content_qa_passed"
STATUS_CONTENT_QA_FAILED = "content_qa_failed"
STATUS_VIDEO_PLAN_READY = "video_plan_ready"
STATUS_VIDEO_GENERATING = "video_generating"
STATUS_VIDEO_READY = "video_ready"
STATUS_RENDERING = "rendering"
STATUS_COMPLETED = "completed"
STATUS_FAILED = "failed"
# S9/S10：自动链的「进程死了」终态。与 failed（业务失败）区分 —— 断点续跑要能看出
# 「是被中途打断、可以续跑」还是「真的失败了」。
STATUS_INTERRUPTED = "interrupted"


@dataclass(frozen=True)
class PipelineRun:
    id: str
    project_id: str
    status: str
    current_step: int
    state_version: int
    created_at: datetime
    updated_at: datetime
    # ---- S8/S9/S10：自动链的断点与审计（全部带默认值 → 既有构造点零改动）----
    # 断点续跑的锚点（阶段名）。老数据为空：续跑时按 current_step 兜底。
    stage: str | None = None
    # 这一轮是不是自动链跑的（人 / 机可区分）
    auto_run: bool = False
    # 被**系统**自动放行的闸口清单（审计用）。**人工确认不写这里** —— 只有它为空/缺失时，
    # 才能判断"这一段是机器放行的"。
    auto_confirmed_stages: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class CostApproval:
    """一次"批准花钱"的记录（S8 的硬约束落点）。

    **独立于** `gate_acks`：那个是交付门 ack，这个是"授权付费"，语义不同不能混表。
    `payload_hash` 把审批与"当时看到的那份预估"绑在一起 —— 改了方案 hash 就变，旧审批自动失效。
    """

    id: str
    project_id: str
    plan_id: str
    estimated_cny: float
    payload_hash: str
    approved_by: str
    approved_at: datetime
