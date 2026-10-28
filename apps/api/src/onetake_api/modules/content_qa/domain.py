from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol

from onetake_api.modules.content_plan.domain import ContentPlan

STATUS_PASSED = "passed"
STATUS_FAILED = "failed"

# 检查项分级（Phase 5）：保留 passed 布尔以兼容既有前端，同时给出更细的分级
LEVEL_OK = "ok"
LEVEL_WARN = "warn"
LEVEL_FAIL = "fail"


@dataclass(frozen=True)
class QaCheck:
    check_id: str
    label: str
    passed: bool
    weight: int
    message: str
    critical: bool
    # 向后兼容：老报告没有这两个字段，读取时用默认值
    level: str = LEVEL_OK
    at_seconds: list[float] = field(default_factory=list)


@dataclass(frozen=True)
class QaResult:
    passed: bool
    score: int
    checks: list[QaCheck]
    critical_failures: list[str]
    signals: object | None = None


@dataclass(frozen=True)
class QaRequest:
    plan: ContentPlan
    metadata: object
    size_bytes: int
    expected_audio: bool
    subtitle_embedded: bool
    product_layered: bool
    video_bytes: bytes
    product_image_bytes: bytes | None = None


@dataclass(frozen=True)
class SemanticQaResult:
    passed: bool
    score: int
    checks: list[QaCheck]
    issues: list[str]


@dataclass(frozen=True)
class ContentQaReport:
    id: str
    project_id: str
    plan_id: str
    video_plan_id: str
    status: str
    score: int
    passed: bool
    checks: list[QaCheck]
    critical_failures: list[str]
    provider: str
    model: str
    created_at: datetime
    rule_score: int | None = None
    semantic_score: int | None = None
    semantic_checks: list[QaCheck] = field(default_factory=list)
    semantic_issues: list[str] = field(default_factory=list)
    # 客观信号（黑帧/静音/冻结/响度/时长），直接以 JSON 形态落库
    signals: dict | None = None


@dataclass(frozen=True)
class RepairAction:
    """一条「质检不过 → 下一步做什么」的动作（S11）。

    `action` 的取值域是**封闭的 7 个**（见 `repair_plan.REPAIR_ACTIONS`）；
    `execute_endpoint` 指向**既有端点**（`human_ack` 指向只读的交付门视图，因为它没有自动执行端点）。
    """

    check_id: str
    label: str
    severity: str            # warn | fail
    action: str
    reason: str
    target_ref: str | None = None      # 分段 id / 分镜 id（需要定位的动作才有）
    estimated_cny: float | None = None
    execute_endpoint: str | None = None


class ContentQaPort(Protocol):
    provider_name: str
    model_name: str

    def evaluate(self, request: QaRequest) -> QaResult:
        ...
