"""质检 → 修复闭环的动作计划（S11 提交 1+2）。

**只做翻译，不做执行**：把交付门/质检的每一条 `warn|fail` 翻译成「一个可执行的动作 + 目标 + 理由」，
动作**只指向既有端点**（`gate.py` 的判定语义一个字都不改，本模块也不新增任何写路径）。

**动作取值域封闭**（恰好 7 个，白名单不是黑名单）：

| 动作 | 打在什么上 | 执行端点（既有） |
|---|---|---|
| `retake_segment` | 单个分段 | `POST /video/segments/{id}/retake` |
| `rebuild_segment` | 单个分段 | `POST /video/segments/{id}/candidates` |
| `regenerate_keyframe` | 单个分镜 | `POST /video/keyframes/{scene}/candidates` |
| `recompose` | 整片 | `POST /compose` |
| `revoice` | 配音 | `POST /voice` |
| `resubtitle` | 字幕 | `POST /subtitle` |
| `human_ack` | 人工 | `GET /video/gate`（人看结论；**没有自动执行端点**） |

**未映射的 check 一律落到 `human_ack`** —— 宁可交人工，不猜动作。

**不做「一键全跑修复」**（待拍板第 2 项）：每个动作都可能付费，全跑等于绕过费用审批。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Protocol, Sequence

from onetake_api.modules.content_qa.domain import LEVEL_OK, RepairAction

# ---- 动作取值域（封闭）----
REPAIR_ACTIONS: tuple[str, ...] = (
    "retake_segment",
    "rebuild_segment",
    "regenerate_keyframe",
    "recompose",
    "revoice",
    "resubtitle",
    "human_ack",
)
HUMAN_ACTION = "human_ack"
AUTO_ACTIONS = frozenset(action for action in REPAIR_ACTIONS if action != HUMAN_ACTION)

# ---- check id → 允许的动作（按优先级；第一个即默认动作）----
# 覆盖面 = 交付门 6 项 + 平台规则 3 项 + 客观质检 10 项（见 tests/unit/test_repair_plan.py 的穷举断言）。
CHECK_ACTIONS: dict[str, tuple[str, ...]] = {
    # 交付门（gate.py）
    "quality_report": (HUMAN_ACTION,),      # 报告都没生成：先由人确认要重跑什么
    "ad_words": (HUMAN_ACTION,),            # 违禁词要改文案，不是重跑生成
    "aigc_label": ("recompose",),           # 标识没烧上：重合成即可
    "contact_sheet": (HUMAN_ACTION,),       # 抽帧拼图缺失：只能人工复核
    "gate_mode": (HUMAN_ACTION,),           # 门模式告警：配置问题，交人工
    # 1b 字幕安全区：缺字幕 → 重烧；贴边/带高异常 → 重合成；与标识碰撞/文案过长 → 交人工判断
    "caption_safety": ("resubtitle", "recompose", HUMAN_ACTION),
    # 4a 素材署名：把 CC 署名写进发布文案是人的事（没有自动端点）
    "stock_sources": (HUMAN_ACTION,),
    # 5 逐镜评分：哪一镜分低就重做那一镜（有分段目标），人也可以先看证据
    "segment_quality": ("retake_segment", "rebuild_segment", HUMAN_ACTION),
    # 平台规则（compliance/platform_rules.py）
    "ai_review_style": (HUMAN_ACTION,),
    "digital_human_category": (HUMAN_ACTION,),
    "personal_testimony": (HUMAN_ACTION,),
    # 客观质检（content_qa/rules.py）
    "timeline": (HUMAN_ACTION,),            # 时间轴不连续：要改分镜
    "product_layer": ("recompose", "regenerate_keyframe"),
    "audio": ("recompose",),                # 缺音轨：重合成带上音频
    "subtitle": ("resubtitle", "recompose"),
    "black_frames": ("retake_segment", "rebuild_segment"),
    "silence": ("recompose", "revoice"),
    "freeze": ("retake_segment",),
    "loudness": ("recompose",),
    "duration_drift": (HUMAN_ACTION,),      # 时长漂移多半要改分镜/文案
    "spec": (HUMAN_ACTION,),                # 规格不符：改模板，不是重跑
}

DEFAULT_ACTIONS: tuple[str, ...] = (HUMAN_ACTION,)

# ---- 动作 → 执行端点模板（**全部既有**；None = 交人工）----
ACTION_ENDPOINT_TEMPLATES: dict[str, str | None] = {
    "retake_segment": "/api/v1/projects/{project_id}/video/segments/{target_ref}/retake",
    "rebuild_segment": "/api/v1/projects/{project_id}/video/segments/{target_ref}/candidates",
    "regenerate_keyframe": "/api/v1/projects/{project_id}/video/keyframes/{target_ref}/candidates",
    "recompose": "/api/v1/projects/{project_id}/compose",
    "revoice": "/api/v1/projects/{project_id}/voice",
    "resubtitle": "/api/v1/projects/{project_id}/subtitle",
    HUMAN_ACTION: "/api/v1/projects/{project_id}/video/gate",
}

ACTION_LABELS: dict[str, str] = {
    "retake_segment": "重拍该分段（改一个变量）",
    "rebuild_segment": "重建该分段（重新出候选）",
    "regenerate_keyframe": "重建该分镜的关键帧",
    "recompose": "重新合成成片",
    "revoice": "重新生成配音",
    "resubtitle": "重新生成字幕",
    HUMAN_ACTION: "交人工判断",
}

# 需要定位到具体对象的动作 → 定位到哪一类
_TARGET_KIND: dict[str, str] = {
    "retake_segment": "segment",
    "rebuild_segment": "segment",
    "regenerate_keyframe": "scene",
}


@dataclass(frozen=True)
class SegmentWindow:
    """分段的定位窗口（时间 → 分段）。纯数据，避免本模块依赖分段的领域类型。"""

    segment_id: str
    start_seconds: float
    end_seconds: float
    scene_id: str | None = None


@dataclass(frozen=True)
class SceneWindow:
    scene_id: str
    start_seconds: float
    end_seconds: float


class _CheckLike(Protocol):
    id: str
    level: str
    label: str
    message: str
    at_seconds: list[float]


class _ReportLike(Protocol):
    project_id: str
    checks: list[Any]


class RepairActionNotAllowedError(ValueError):
    """动作不在封闭取值域内（映射表自检失败）。**导入时不检查**，由测试与调用方显式触发。"""


def validate_tables() -> None:
    """自检两张表：映射里的动作必须封闭，且每个动作都要有端点模板。

    导入时不执行（避免 import 副作用）；由 `tests/unit/test_repair_plan.py` 与调用方显式调用。
    """
    for check_id, actions in CHECK_ACTIONS.items():
        if not actions:
            raise RepairActionNotAllowedError(f"{check_id} 没有任何允许动作")
        for action in actions:
            if action not in REPAIR_ACTIONS:
                raise RepairActionNotAllowedError(f"{check_id} 映射了非法动作：{action}")
    for action in REPAIR_ACTIONS:
        if action not in ACTION_ENDPOINT_TEMPLATES:
            raise RepairActionNotAllowedError(f"动作 {action} 没有端点模板")
        if action not in ACTION_LABELS:
            raise RepairActionNotAllowedError(f"动作 {action} 没有中文标签")
    for action in ACTION_ENDPOINT_TEMPLATES:
        if action not in REPAIR_ACTIONS:
            raise RepairActionNotAllowedError(f"端点表里有非法动作：{action}")


def check_actions(check_id: str) -> tuple[str, ...]:
    """某个 check 允许的动作（按优先级）。**未映射 → 只允许 `human_ack`**。"""
    return CHECK_ACTIONS.get(check_id, DEFAULT_ACTIONS)


def resolve_segment_ref(at_seconds: Iterable[float], segments: Sequence[SegmentWindow]) -> str | None:
    """命中时间 → 具体分段 id。唯一分段时直接取它；否则取第一个落在窗口内的分段。"""
    windows = list(segments)
    if len(windows) == 1:
        return windows[0].segment_id
    for second in at_seconds or []:
        for window in windows:
            if window.start_seconds <= second <= window.end_seconds:
                return window.segment_id
    return None


def resolve_scene_ref(at_seconds: Iterable[float], scenes: Sequence[SceneWindow]) -> str | None:
    windows = list(scenes)
    if len(windows) == 1:
        return windows[0].scene_id
    for second in at_seconds or []:
        for window in windows:
            if window.start_seconds <= second <= window.end_seconds:
                return window.scene_id
    return None


def _endpoint_for(action: str, project_id: str, target_ref: str | None) -> str | None:
    template = ACTION_ENDPOINT_TEMPLATES.get(action)
    if template is None:
        return None
    return template.format(project_id=project_id, target_ref=target_ref or "")


def plan_repairs(
    report: _ReportLike,
    *,
    segments: Sequence[SegmentWindow] = (),
    scenes: Sequence[SceneWindow] = (),
    action_cost_cny: Mapping[str, float] | None = None,
) -> list[RepairAction]:
    """把一份交付门报告里所有 `warn|fail` 翻成动作计划。**纯函数**：不读库、不写库、不发请求。

    `action_cost_cny` 由调用方给出（例如视频类动作 = 方案级预估），本函数不引入任何计价逻辑。
    """
    costs: Mapping[str, float] = action_cost_cny or {}
    actions: list[RepairAction] = []
    for check in getattr(report, "checks", []) or []:
        level = getattr(check, "level", LEVEL_OK)
        if level == LEVEL_OK:
            continue
        actions.append(
            _action_for_check(
                check,
                project_id=getattr(report, "project_id", ""),
                segments=segments,
                scenes=scenes,
                costs=costs,
            )
        )
    return actions


def _action_for_check(
    check: _CheckLike,
    *,
    project_id: str,
    segments: Sequence[SegmentWindow],
    scenes: Sequence[SceneWindow],
    costs: Mapping[str, float],
) -> RepairAction:
    check_id = getattr(check, "id", "")
    label = getattr(check, "label", check_id)
    level = getattr(check, "level", "warn")
    at_seconds = list(getattr(check, "at_seconds", []) or [])
    candidates = check_actions(check_id)
    action = candidates[0]

    target_ref: str | None = None
    kind = _TARGET_KIND.get(action)
    if kind is not None:
        if kind == "segment":
            target_ref = resolve_segment_ref(at_seconds, segments)
        else:
            target_ref = resolve_scene_ref(at_seconds, scenes)
        if target_ref is None:
            # 定位不到具体对象 → 不猜，退回人工（动作取值域不允许「无目标的 retake」）
            return RepairAction(
                check_id=check_id,
                label=label,
                severity=level,
                action=HUMAN_ACTION,
                reason=f"{getattr(check, 'message', '')}（{ACTION_LABELS[action]}需要定位到具体对象，"
                       f"但报告没给出可用的时间/对象）",
                target_ref=None,
                estimated_cny=costs.get(HUMAN_ACTION, 0.0),
                execute_endpoint=_endpoint_for(HUMAN_ACTION, project_id, None),
            )

    return RepairAction(
        check_id=check_id,
        label=label,
        severity=level,
        action=action,
        reason=getattr(check, "message", ""),
        target_ref=target_ref,
        estimated_cny=costs.get(action, 0.0),
        execute_endpoint=_endpoint_for(action, project_id, target_ref),
    )