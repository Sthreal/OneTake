"""把已落库的交付门报告翻成「修复动作计划」（S6 6d）。

**只做翻译，不做执行**：`content_qa/repair_plan.py` 的映射表/端点表一个字不改，这里只负责
把 `plans.gate_report`（`asdict(GateReportView)` 落库的 JSON）与分段窗口喂进去，输出可直接展示的视图。
本模块**不新增写路径**：每个动作是否要花、要不要执行，仍由人点（付费动作不得静默触发）。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from onetake_api.modules.content_qa.domain import RepairAction
from onetake_api.modules.content_qa.repair_plan import SceneWindow, SegmentWindow, plan_repairs


@dataclass(frozen=True)
class _CheckView:
    """`GateCheckView` 的只读镜像（只取 repair_plan 协议需要的字段）。"""

    id: str
    level: str
    label: str
    message: str = ""
    at_seconds: list[float] = field(default_factory=list)


@dataclass(frozen=True)
class _ReportView:
    project_id: str
    checks: list[_CheckView]


def _check_from_dict(raw: dict[str, Any]) -> _CheckView:
    at_seconds = raw.get("at_seconds") or []
    return _CheckView(
        id=str(raw.get("id", "")),
        level=str(raw.get("level", "ok")),
        label=str(raw.get("label", raw.get("id", ""))),
        message=str(raw.get("message", "")),
        at_seconds=[float(value) for value in at_seconds if isinstance(value, (int, float))],
    )


def build_repair_actions(
    *, project_id: str, gate_report: dict[str, Any] | None, segments: list[SegmentWindow]
) -> list[RepairAction]:
    """交付门报告 → 动作计划；没有报告（或没有 warn/fail）时返回空列表（不编动作）。"""
    checks = [
        _check_from_dict(raw)
        for raw in (gate_report or {}).get("checks", []) or []
        if isinstance(raw, dict)
    ]
    if not checks:
        return []
    # 本仓"分段 ↔ 分镜"是 1:1（`_materialize` 按 scene.order 逐镜建段），
    # 所以分镜窗口直接由分段派生 —— 少一层依赖，也不会与分段口径漂移。
    scenes = [
        SceneWindow(scene_id=item.scene_id, start_seconds=item.start_seconds, end_seconds=item.end_seconds)
        for item in segments
        if item.scene_id
    ]
    return plan_repairs(_ReportView(project_id=project_id, checks=checks), segments=segments, scenes=scenes)
