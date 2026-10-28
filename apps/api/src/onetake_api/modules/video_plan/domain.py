from dataclasses import dataclass
from datetime import datetime

PLAN_READY = "plan_ready"
VIDEO_GENERATING = "video_generating"
VIDEO_READY = "video_ready"
RENDERING = "rendering"
COMPLETED = "completed"
FAILED = "failed"
PRODUCT_SCENE_TEMPLATES = frozenset({"clean", "dynamic", "lifestyle"})
BATCH_IDLE = "idle"
BATCH_RUNNING = "running"
BATCH_STOPPED = "stopped"
BATCH_DONE = "done"
BATCH_FAILED = "failed"
BATCH_INTERRUPTED = "interrupted"
PATH_SEGMENTED = "segmented"
PATH_ONE_SHOT = "one_shot"
GENERATION_PATHS = frozenset({PATH_SEGMENTED, PATH_ONE_SHOT})
# 提示词真实感档（S5，见迁移 0024）：auto 全开 / constraints 只加约束与光线 / off 什么都不加
MOTION_REALISM_AUTO = "auto"
MOTION_REALISM_CONSTRAINTS = "constraints"
MOTION_REALISM_OFF = "off"
MOTION_REALISM_TIERS = frozenset({MOTION_REALISM_AUTO, MOTION_REALISM_CONSTRAINTS, MOTION_REALISM_OFF})
# 接缝模式（S6，见迁移 0025）：pin 钉帧（默认）/ tail 续拍 / off 各镜独立
SEAM_PIN = "pin"
SEAM_TAIL = "tail"
SEAM_OFF = "off"
SEAM_MODES = frozenset({SEAM_PIN, SEAM_TAIL, SEAM_OFF})

# 视频形态只有一种：商品。数字人（avatar）档位已于 2026-10-14 下线（档案 M4-04）——
# 「画面里有人」交给 Prompt 表达，不再作为可枚举的档位；传 avatar 一律明确拒绝，不静默降级。
MODE_PRODUCT = "product"
MODES = frozenset({MODE_PRODUCT})


@dataclass(frozen=True)
class VideoPlan:
    id: str
    project_id: str
    mode: str
    template_id: str | None
    status: str
    duration_seconds: float
    width: int
    height: int
    fps: int
    voice_enabled: bool
    subtitle_enabled: bool
    main_image_object_key: str
    voice_object_key: str | None
    subtitle_object_key: str | None
    base_video_object_key: str | None
    final_object_key: str | None
    provider: str
    error_code: str | None
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None
    confirmed_at: datetime | None
    batch_status: str = BATCH_IDLE
    batch_stop_requested: bool = False
    # 生成路径：segmented（默认，逐镜关键帧 → 图生视频）| one_shot（多关键帧一次出片）
    path: str = PATH_SEGMENTED
    # **默认 off**：历史项目零行为变更；新项目由 `create_plan` 显式写 auto（口径 5）
    motion_realism: str = MOTION_REALISM_OFF
    # **默认 pin** = S6 之前的行为（钉帧：尾帧取下一镜关键帧）
    seam_mode: str = SEAM_PIN
    # 方案级「合成旋钮」（S4-④a）：**None = 跟全局配置**（迁移 0027 前全部为 None → 零变更）
    caption_style: str | None = None
    bgm_enabled: bool | None = None
    bgm_gain_db: float | None = None
    # 交付门结论（Phase 5）：pass|warn|fail + 逐条检查，随成片落库
    gate_report: dict | None = None
