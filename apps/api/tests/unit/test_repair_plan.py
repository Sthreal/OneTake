"""修复动作计划的单元测试（S11 验收 1 / 2 / 3）。

**穷举而不是抽查**：check id 从**源码**里扫出来（`gate.py` 的 `GateCheckView(id=...)`、
`platform_rules.py` 的 `id=...`、`rules.py` 的 `QaCheck("...")`），这样才能在有人新增检查项时
立刻红掉，而不是等线上出现「报告说不过但没动作」。
"""
from __future__ import annotations

import pathlib
import re
from dataclasses import dataclass, field

import pytest

from onetake_api.modules.compliance import platform_rules
from onetake_api.modules.content_qa import rules
from onetake_api.modules.content_qa.repair_plan import (
    ACTION_ENDPOINT_TEMPLATES,
    CHECK_ACTIONS,
    DEFAULT_ACTIONS,
    HUMAN_ACTION,
    REPAIR_ACTIONS,
    RepairActionNotAllowedError,
    SceneWindow,
    SegmentWindow,
    check_actions,
    plan_repairs,
    resolve_scene_ref,
    resolve_segment_ref,
    validate_tables,
)
from onetake_api.modules.video_plan import gate


@dataclass
class _Check:
    id: str
    level: str
    label: str = "检查项"
    message: str = "不达标"
    at_seconds: list[float] = field(default_factory=list)


@dataclass
class _Report:
    project_id: str = "prj_x"
    checks: list[_Check] = field(default_factory=list)


def _source_check_ids() -> dict[str, set[str]]:
    """从三处源码里扫出现有的 check id。"""
    def scan(module, pattern: str) -> set[str]:
        text = pathlib.Path(module.__file__).read_text(encoding="utf-8")
        return set(re.findall(pattern, text))

    return {
        "gate": scan(gate, r'GateCheckView\(\s*id="([a-z_]+)"'),
        "platform": scan(platform_rules, r'id="([a-z_]+)"'),
        "qa": scan(rules, r'QaCheck\(\s*"([a-z_]+)"'),
    }


def test_every_existing_check_id_has_a_mapping() -> None:
    discovered = _source_check_ids()
    known = set().union(*discovered.values())
    assert len(discovered["qa"]) == 10, discovered["qa"]   # 客观质检 10 项
    assert len(discovered["gate"]) == 8, discovered["gate"]  # 交付门 8 项（1b 加 caption_safety、4a 加 stock_sources、5 加 segment_quality）
    assert len(known) >= 16
    missing = sorted(known - set(CHECK_ACTIONS))
    assert missing == [], f"这些 check 没有映射：{missing}"


def test_mapping_table_has_no_dead_rows() -> None:
    discovered = set().union(*_source_check_ids().values())
    dead = sorted(set(CHECK_ACTIONS) - discovered)
    assert dead == [], f"CHECK_ACTIONS 里有已不存在的 check id：{dead}"


def test_action_domain_is_closed() -> None:
    assert len(REPAIR_ACTIONS) == 7
    assert HUMAN_ACTION in REPAIR_ACTIONS
    validate_tables()

    # 构造一个非法动作 → 自检必须报错（白名单，不是黑名单）
    from onetake_api.modules.content_qa import repair_plan as module

    original = dict(module.CHECK_ACTIONS)
    try:
        module.CHECK_ACTIONS["silence"] = ("retake_everything",)
        with pytest.raises(RepairActionNotAllowedError):
            validate_tables()
    finally:
        module.CHECK_ACTIONS.clear()
        module.CHECK_ACTIONS.update(original)


def test_unmapped_check_falls_back_to_human_ack() -> None:
    assert check_actions("brand_new_check_id") == DEFAULT_ACTIONS
    actions = plan_repairs(_Report(checks=[_Check("brand_new_check_id", "fail")]))
    assert [item.action for item in actions] == [HUMAN_ACTION]


def test_ok_checks_produce_no_actions() -> None:
    assert plan_repairs(_Report(checks=[_Check("timeline", "ok")])) == []


def test_typical_scenarios() -> None:
    segments = [
        SegmentWindow(segment_id="seg_1", start_seconds=0.0, end_seconds=5.0),
        SegmentWindow(segment_id="seg_2", start_seconds=5.0, end_seconds=10.0),
    ]
    scenes = [
        SceneWindow(scene_id="scene_0", start_seconds=0.0, end_seconds=5.0),
        SceneWindow(scene_id="scene_1", start_seconds=5.0, end_seconds=10.0),
    ]
    report = _Report(
        checks=[
            _Check("silence", "warn", message="检测到静音", at_seconds=[6.0]),
            _Check("ad_words", "warn", message="命中违禁词"),
            _Check("freeze", "warn", message="画面冻结", at_seconds=[6.5]),
        ]
    )
    actions = {item.check_id: item for item in plan_repairs(report, segments=segments, scenes=scenes)}

    # 静音 → recompose / revoice（二者都可接受）
    assert actions["silence"].action in {"recompose", "revoice"}, actions["silence"]
    # 违禁词 → **只**能交人工（不可自动修复的必须交人工）
    assert actions["ad_words"].action == HUMAN_ACTION
    # 冻结 → 重拍该段，且能定位到具体 segment
    freeze = actions["freeze"]
    assert freeze.action == "retake_segment", freeze
    assert freeze.target_ref == "seg_2", freeze
    assert freeze.execute_endpoint.endswith("/video/segments/seg_2/retake"), freeze.execute_endpoint


def test_target_resolution_is_time_based() -> None:
    segments = [
        SegmentWindow(segment_id="seg_1", start_seconds=0.0, end_seconds=5.0),
        SegmentWindow(segment_id="seg_2", start_seconds=5.0, end_seconds=10.0),
    ]
    assert resolve_segment_ref([7.5], segments) == "seg_2"
    assert resolve_segment_ref([0.0], segments) == "seg_1"
    assert resolve_segment_ref([], segments) is None
    # 只有一个对象时直接取它（报告常常没有时间点）
    assert resolve_segment_ref([], segments[:1]) == "seg_1"
    assert resolve_scene_ref([6.0], [SceneWindow("scene_0", 0.0, 5.0), SceneWindow("scene_1", 5.0, 10.0)]) == "scene_1"


def test_unresolvable_target_downgrades_to_human() -> None:
    """定位不到具体分段时不猜：退回人工（动作取值域里没有「无目标的 retake」）。"""
    report = _Report(checks=[_Check("freeze", "warn", message="画面冻结", at_seconds=[])])
    segments = [
        SegmentWindow(segment_id="seg_1", start_seconds=0.0, end_seconds=5.0),
        SegmentWindow(segment_id="seg_2", start_seconds=5.0, end_seconds=10.0),
    ]
    action = plan_repairs(report, segments=segments)[0]
    assert action.action == HUMAN_ACTION, action
    assert action.target_ref is None
    assert "定位" in action.reason


def test_every_action_has_an_endpoint_template_pointing_at_existing_routes() -> None:
    existing = {
        "/api/v1/projects/{project_id}/video/segments/{target_ref}/retake": "retake_segment",
        "/api/v1/projects/{project_id}/video/segments/{target_ref}/candidates": "rebuild_segment",
        "/api/v1/projects/{project_id}/video/keyframes/{target_ref}/candidates": "regenerate_keyframe",
        "/api/v1/projects/{project_id}/compose": "recompose",
        "/api/v1/projects/{project_id}/voice": "revoice",
        "/api/v1/projects/{project_id}/subtitle": "resubtitle",
        "/api/v1/projects/{project_id}/video/gate": HUMAN_ACTION,
    }
    assert set(ACTION_ENDPOINT_TEMPLATES) == set(REPAIR_ACTIONS)
    for action, template in ACTION_ENDPOINT_TEMPLATES.items():
        assert existing[template] == action, action  # 模板必须逐字命中既有端点点