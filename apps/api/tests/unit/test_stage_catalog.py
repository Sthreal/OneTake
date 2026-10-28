"""S8+S9+S10 提交 3 单测：阶段目录的取值域与查询语义（纯数据，零 I/O）。"""
from __future__ import annotations

import pytest

from onetake_api.modules.pipeline import stage_catalog as catalog


def test_catalog_passes_its_own_validation() -> None:
    catalog.validate_catalog()


def test_stage_names_and_order_are_the_agreed_nine() -> None:
    assert catalog.STAGE_NAMES == (
        "recognition", "main_image", "script", "voice_subtitle", "content_plan",
        "content_qa", "keyframes", "segments", "render_compose",
    )
    assert [spec.order for spec in catalog.STAGES] == list(range(1, 10))


def test_failure_semantics_and_recover_actions_are_closed_sets() -> None:
    """取值域封闭：新增语义必须先改这两个集合（推进器据此分支）。"""
    assert catalog.FAILURE_SEMANTICS == {"best_effort", "fatal"}
    assert catalog.STAGE_RECOVER_ACTIONS == {
        "retry", "retry_with_fallback", "skip_stage", "require_human", "abort",
    }
    for spec in catalog.STAGES:
        assert spec.failure_semantics in catalog.FAILURE_SEMANTICS
        assert spec.default_recover_action in catalog.STAGE_RECOVER_ACTIONS


def test_only_content_qa_is_best_effort_and_it_skips() -> None:
    """当前只有语义质检是"失败跳过"；其余都是 fatal（产不出东西就没法继续）。"""
    best_effort = [spec.name for spec in catalog.STAGES if spec.failure_semantics == "best_effort"]
    assert best_effort == ["content_qa"]
    assert catalog.get_stage("content_qa").default_recover_action == "skip_stage"


def test_every_fatal_stage_stops_for_a_human() -> None:
    """对齐 README:232：失败一律**停在待人工**，绝不判成功往下跑。"""
    for spec in catalog.STAGES:
        if spec.failure_semantics == "fatal":
            assert spec.default_recover_action == "require_human", spec.name


def test_only_content_plan_is_a_human_gate_stage() -> None:
    assert [spec.name for spec in catalog.STAGES if spec.human_gate] == ["content_plan"]


def test_the_three_human_gates_are_where_the_plan_says() -> None:
    assert catalog.HUMAN_GATE_NAMES == ("content_plan", "plan_and_cost", "delivery")
    assert catalog.human_gate_after("voice_subtitle").name == "content_plan"
    assert catalog.human_gate_after("keyframes").name == "plan_and_cost"
    assert catalog.human_gate_after("render_compose").name == "delivery"
    # 中间那些阶段之后**没有**闸口（否则自动段会被切碎）
    for name in ("recognition", "main_image", "script", "content_qa", "segments"):
        assert catalog.human_gate_after(name) is None


def test_stages_from_is_the_resume_slice() -> None:
    assert [spec.name for spec in catalog.stages_from("recognition")] == list(catalog.STAGE_NAMES)
    assert [spec.name for spec in catalog.stages_from("keyframes")] == ["keyframes", "segments", "render_compose"]
    assert [spec.name for spec in catalog.stages_from("render_compose")] == ["render_compose"]


def test_unknown_stage_raises_instead_of_silently_restarting() -> None:
    """断点续跑最怕"阶段名写错 → 静默从头跑"：必须明确报错。"""
    with pytest.raises(catalog.UnknownStageError):
        catalog.get_stage("nope")
    with pytest.raises(catalog.UnknownStageError):
        catalog.stages_from("nope")
    with pytest.raises(catalog.UnknownStageError):
        catalog.human_gate_after("nope")


def test_status_fields_reference_real_pipeline_statuses() -> None:
    """阶段表里的状态必须是真的 pipeline 状态常量（不写字面量 → 不会漂移）。"""
    from onetake_api.modules import pipeline

    statuses = {
        value for name, value in vars(pipeline.domain).items()
        if name.startswith("STATUS_") and isinstance(value, str)
    }
    for spec in catalog.STAGES:
        for value in (spec.enter_status, spec.ready_status, spec.confirm_status, *spec.extra_statuses):
            if value is not None:
                assert value in statuses, f"{spec.name} 引用了不存在的状态：{value}"


def test_every_stage_declares_a_paid_path() -> None:
    """静态口径：今天 9 段都有付费路径（合成在 shotstack 下也计费）。
    能不能跑由 estimate 的**金额**决定，不由这个标志决定 —— 见模块 docstring。"""
    assert len(catalog.paid_stages()) == 9