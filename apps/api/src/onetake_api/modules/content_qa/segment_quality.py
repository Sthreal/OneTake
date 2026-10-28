"""逐镜 VLM 评分的领域与编排（批次 5）。

**为什么逐镜**：整片打分只能得到"这条不行"，逐镜才能定位到"第 3 镜商品变形"——后者才可执行（重生成那一镜）。

**费用纪律**：这是**付费调用**（Qwen-VL 按次），所以：
1. 默认关闭（`SEGMENT_QUALITY_ENABLED=false`），要显式打开；
2. 费用进 `estimate.py`（缺单价就如实进 `missing_price_config`，不按 0 算）；
3. 走 `/cost-approval` 闸（与其它付费入口同一道闸，无绕行）。

**落库方式**：报告写对象存储侧车 `projects/<pid>/quality/segment-scores.json`
（不新增数据表、不改既有契约；交付门按需读取，读不到就跳过这一条）。
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime

from onetake_api.integrations.object_storage.dependencies import get_object_storage
from onetake_api.integrations.qwen_vl_quality.adapter import (
    SEGMENT_QUALITY_DIMENSIONS,
    SEGMENT_QUALITY_WEIGHTS,
)

REPORT_KEY_TEMPLATE = "projects/{project_id}/quality/segment-scores.json"
LOW_SCORE_THRESHOLD = 70        # 低于它 → 交付门给 warn（**不阻断**，交人看）


@dataclass(frozen=True)
class SegmentScore:
    segment_id: str
    order_index: int
    scene_id: str
    scores: dict[str, int]
    overall: int
    issues: list[str] = field(default_factory=list)
    evidence_seconds: list[float] = field(default_factory=list)


@dataclass(frozen=True)
class SegmentQualityReport:
    project_id: str
    plan_id: str
    provider: str
    model: str
    calls: int
    created_at: str
    segments: list[SegmentScore]
    # DashScope 的真实用量汇总（tokens）：用来校准单价（空 dict = 模型没返回用量）
    usage: dict[str, int] = field(default_factory=dict)

    @property
    def low_scores(self) -> list[SegmentScore]:
        return [item for item in self.segments if item.overall < LOW_SCORE_THRESHOLD]

    @property
    def issues(self) -> list[str]:
        return [
            f"第 {item.order_index} 镜（{item.overall} 分）：" + "；".join(item.issues)
            for item in self.segments if item.issues
        ]

    def to_dict(self) -> dict:
        return {
            "project_id": self.project_id, "plan_id": self.plan_id, "provider": self.provider,
            "model": self.model, "calls": self.calls, "created_at": self.created_at,
            "low_score_threshold": LOW_SCORE_THRESHOLD,
            "usage": dict(self.usage),
            "segments": [asdict(item) for item in self.segments],
        }

    @classmethod
    def from_dict(cls, payload: dict) -> "SegmentQualityReport":
        return cls(
            project_id=str(payload.get("project_id") or ""),
            plan_id=str(payload.get("plan_id") or ""),
            provider=str(payload.get("provider") or ""),
            model=str(payload.get("model") or ""),
            calls=int(payload.get("calls") or 0),
            created_at=str(payload.get("created_at") or ""),
            segments=[SegmentScore(**item) for item in payload.get("segments", [])],
            usage={str(k): int(v) for k, v in dict(payload.get("usage") or {}).items() if isinstance(v, (int, float))},
        )


def overall_score(scores: dict[str, int]) -> int:
    """按 `SEGMENT_QUALITY_WEIGHTS` 加权平均（缺的维度按 0 计并**如实**反映在分数里）。"""
    total_weight = sum(SEGMENT_QUALITY_WEIGHTS.values())
    if total_weight <= 0:
        return 0
    weighted = sum(SEGMENT_QUALITY_WEIGHTS[dimension] * int(scores.get(dimension, 0)) for dimension in SEGMENT_QUALITY_WEIGHTS)
    return int(round(weighted / total_weight))


def missing_dimensions(scores: dict[str, int]) -> list[str]:
    return [dimension for dimension in SEGMENT_QUALITY_DIMENSIONS if dimension not in scores]


def write_report(storage, report: SegmentQualityReport) -> str:
    """写侧车 JSON（同一项目覆盖上一次：只保留**最近一次**评分，避免报告越堆越多）。"""
    key = REPORT_KEY_TEMPLATE.format(project_id=report.project_id)
    storage.put_bytes(
        object_key=key,
        content=json.dumps(report.to_dict(), ensure_ascii=False, indent=1).encode("utf-8"),
        mime_type="application/json",
    )
    return key


def read_report(project_id: str, *, storage=None) -> SegmentQualityReport | None:
    """读最近一次评分；读不到/解析失败一律返回 None（**不影响**交付门结论）。"""
    backend = storage or get_object_storage()
    key = REPORT_KEY_TEMPLATE.format(project_id=project_id)
    try:
        payload = json.loads(b"".join(backend.read_object(object_key=key)).decode("utf-8"))
    except Exception:  # noqa: BLE001
        return None
    try:
        return SegmentQualityReport.from_dict(payload)
    except (TypeError, ValueError):
        return None


def build_report(
    *, project_id: str, plan_id: str, provider: str, model: str, calls: int,
    segments: list[tuple[str, int, str, dict[str, int], list[str], list[float]]],
    usage: dict[str, int] | None = None,
) -> SegmentQualityReport:
    """把适配器返回的原始结果归一成报告（含加权总分）。"""
    scores = [
        SegmentScore(
            segment_id=segment_id, order_index=order_index, scene_id=scene_id,
            scores=dict(raw_scores), overall=overall_score(raw_scores),
            issues=list(issues), evidence_seconds=list(evidence),
        )
        for segment_id, order_index, scene_id, raw_scores, issues, evidence in segments
    ]
    scores.sort(key=lambda item: item.order_index)
    return SegmentQualityReport(
        project_id=project_id, plan_id=plan_id, provider=provider, model=model, calls=calls,
        created_at=datetime.now(UTC).isoformat(), segments=scores, usage=dict(usage or {}),
    )