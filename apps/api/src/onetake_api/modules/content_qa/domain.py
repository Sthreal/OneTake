from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol

from onetake_api.modules.content_plan.domain import ContentPlan

STATUS_PASSED = "passed"
STATUS_FAILED = "failed"


@dataclass(frozen=True)
class QaCheck:
    check_id: str
    label: str
    passed: bool
    weight: int
    message: str
    critical: bool


@dataclass(frozen=True)
class QaResult:
    passed: bool
    score: int
    checks: list[QaCheck]
    critical_failures: list[str]


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


class ContentQaPort(Protocol):
    provider_name: str
    model_name: str

    def evaluate(self, request: QaRequest) -> QaResult:
        ...
