"""S6 6d 单测：交付门报告 → 修复动作计划（只翻译，不执行）。"""
from __future__ import annotations

from onetake_api.modules.content_qa.repair_plan import SegmentWindow
from onetake_api.modules.video_plan.repair_view import build_repair_actions


def _window(segment_id: str, start: float, end: float, scene_id: str) -> SegmentWindow:
    return SegmentWindow(segment_id=segment_id, start_seconds=start, end_seconds=end, scene_id=scene_id)


def _report(*checks: dict) -> dict:
    return {"status": "warn", "checks": list(checks)}


def test_no_report_or_no_problem_yields_no_actions() -> None:
    assert build_repair_actions(project_id="p", gate_report=None, segments=[]) == []
    assert build_repair_actions(project_id="p", gate_report={"checks": []}, segments=[]) == []
    assert build_repair_actions(
        project_id="p", gate_report=_report({"id": "x", "level": "ok"}), segments=[]
    ) == []


def test_segment_targeted_check_resolves_to_the_segment_window() -> None:
    report = _report({
        "id": "segment_quality", "level": "warn", "label": "逐镜评分",
        "message": "第 2 段偏低", "at_seconds": [6.5],
    })
    actions = build_repair_actions(
        project_id="p", gate_report=report,
        segments=[_window("seg_1", 0.0, 5.0, "scene_1"), _window("seg_2", 5.0, 10.0, "scene_2")],
    )
    assert len(actions) == 1
    assert actions[0].action == "retake_segment"
    assert actions[0].target_ref == "seg_2"
    assert actions[0].execute_endpoint.endswith("/video/segments/seg_2/retake")


def test_whole_film_check_maps_to_recompose_without_a_target() -> None:
    actions = build_repair_actions(
        project_id="prj_x",
        gate_report=_report({"id": "silence", "level": "warn", "label": "静音", "message": "1 段静音"}),
        segments=[],
    )
    assert actions[0].action == "recompose"
    assert actions[0].target_ref is None
    assert actions[0].execute_endpoint.endswith("/compose")


def test_unmapped_check_falls_back_to_human_ack() -> None:
    actions = build_repair_actions(
        project_id="p",
        gate_report=_report({"id": "some-brand-new-check", "level": "fail", "label": "新检查", "message": "x"}),
        segments=[],
    )
    assert actions[0].action == "human_ack"
