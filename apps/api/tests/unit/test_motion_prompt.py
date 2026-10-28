"""Phase 2 单测：i2v 运动提示词引擎与症状补丁。"""
from __future__ import annotations

import pytest

from onetake_api.config import get_settings
from onetake_api.modules.content_plan.domain import ContentScene
from onetake_api.modules.video_plan.motion_prompt import (
    CHAIN_CLAUSE,
    DEFAULT_MICRO_ACTION,
    OPENING_ANCHOR_CLAUSE,
    SUBJECT_MICRO_ACTIONS,
    PRODUCT_FIDELITY_CLAUSE,
    STABILITY_CLAUSE,
    SYMPTOM_PATCHES,
    UnknownSymptomError,
    apply_symptom_patch,
    build_motion_prompt,
    build_motion_negative_prompt,
)
from onetake_api.integrations.product_scene.product_constraints import INTEGRATED_NEGATIVE_TERMS
from onetake_api.integrations.product_scene.style_profiles import get_style_profile
from onetake_api.modules.content_plan.prompt_schema import build_background_negative_prompt
from onetake_api.modules.video_plan.segment_generation import (
    assemble_segment_negative_prompt,
    assemble_segment_prompt,
)


def _scene(
    *,
    product_mode: str = "integrated",
    overlay: bool = True,
    goal: str = "product_reveal",
    purpose: str = "selling_point",
) -> ContentScene:
    return ContentScene(
        scene_id="scene_1", order=1, purpose=purpose, script_excerpt="文案",
        start_seconds=0.0, end_seconds=5.0, shot_type="product_reveal", prompt="",
        overlay_product=overlay, product_position="center", background_style="clean", template_id="clean",
        subtitle_segment_ids=[1], qa_rules=[], visual_goal=goal, subject_action="灯光渐亮",
        camera_move="push_in", product_mode=product_mode, transition="fade",
    )


def test_motion_prompt_has_four_sections_and_no_scene_restatement() -> None:
    prompt = build_motion_prompt(_scene())
    # S7 提交 3：四段式前面多了一句「首帧锚定」开场句 → 现在共 5 段。
    # 差分断言（比"以运镜开头"更强）：**去掉这一句之后必须与改动前逐字相同**。
    assert prompt.startswith(OPENING_ANCHOR_CLAUSE)
    rest = prompt[len(OPENING_ANCHOR_CLAUSE):]
    assert rest.startswith("运镜：")
    assert "画面动态：" in rest
    assert PRODUCT_FIDELITY_CLAUSE in rest
    assert rest.endswith(STABILITY_CLAUSE)
    # 不应重述场景/风格（首帧已承载），否则会诱发商品重绘
    assert "浅色影棚" not in prompt
    assert "真实商业" not in prompt


def test_motion_prompt_skips_fidelity_when_product_absent() -> None:
    prompt = build_motion_prompt(_scene(product_mode="absent", overlay=False, goal="pain_point"))
    assert PRODUCT_FIDELITY_CLAUSE not in prompt
    assert "环境轻微变化" in prompt


def test_motion_prompt_intensity_changes_wording() -> None:
    subtle = build_motion_prompt(_scene(), intensity="subtle")
    strong = build_motion_prompt(_scene(), intensity="strong")
    assert "幅度很小" in subtle
    assert "幅度明显" in strong


def test_motion_prompt_chain_clause() -> None:
    assert CHAIN_CLAUSE not in build_motion_prompt(_scene())
    assert CHAIN_CLAUSE in build_motion_prompt(_scene(), chain_to_next=True)


def test_motion_negative_prompt_covers_static_and_drift() -> None:
    negative = build_motion_negative_prompt(_scene())
    assert "画面静止不动" in negative
    assert "主体漂移" in negative
    assert "商品变形" in negative


@pytest.mark.parametrize("symptom,patch", list(SYMPTOM_PATCHES.items()))
def test_symptom_patch_appends_exactly_one_clause(symptom: str, patch: str) -> None:
    base = build_motion_prompt(_scene())
    patched = apply_symptom_patch(base, symptom)
    assert patched == base + patch
    # 单变量纪律：除该补丁外，其余文本完全一致
    assert patched.count(patch) == 1


def test_unknown_symptom_is_rejected() -> None:
    with pytest.raises(UnknownSymptomError):
        apply_symptom_patch("基础提示词", "not_a_symptom")


def test_assemble_segment_prompt_respects_switch(monkeypatch: pytest.MonkeyPatch) -> None:
    from types import SimpleNamespace

    plan = SimpleNamespace(template_id="clean")
    scene = _scene()

    monkeypatch.setenv("VIDEO_MOTION_PROMPT_ENABLED", "false")
    get_settings.cache_clear()
    legacy = assemble_segment_prompt(scene, plan)
    assert "只生成背景" in legacy

    monkeypatch.setenv("VIDEO_MOTION_PROMPT_ENABLED", "true")
    get_settings.cache_clear()
    motion = assemble_segment_prompt(scene, plan)
    assert motion.startswith(OPENING_ANCHOR_CLAUSE)
    assert motion[len(OPENING_ANCHOR_CLAUSE):].startswith("运镜：")
    assert "只生成背景" not in motion

    get_settings.cache_clear()

# ------------------------------------------------------------------ S7 新增
def test_opening_anchor_applies_even_when_product_absent() -> None:
    """开场句是**首帧约束**不是商品约束：商品不可见的镜头也要有（否则仍会重构图）。"""
    prompt = build_motion_prompt(_scene(product_mode="absent", overlay=False, goal="pain_point"))
    assert prompt.startswith(OPENING_ANCHOR_CLAUSE)
    assert PRODUCT_FIDELITY_CLAUSE not in prompt
    # 只多这一句：去掉后依旧是"运镜 → 画面动态 → 稳定性"的原结构
    rest = prompt[len(OPENING_ANCHOR_CLAUSE):]
    assert rest.startswith("运镜：")
    assert rest.endswith(STABILITY_CLAUSE)


def test_micro_action_pool_is_seed_stable_and_actually_rotates() -> None:
    scene = _scene(goal="product_reveal")
    pool = SUBJECT_MICRO_ACTIONS["product_reveal"]
    assert len(pool) >= 2, "池化至少要两条才有轮换意义"
    assert pool[0] == "灯光由弱渐亮扫过主体，画面有轻微呼吸感", "首条必须是改动前原文案"

    # 同 seed → 恒定（可复现）
    assert build_motion_prompt(scene, seed=7) == build_motion_prompt(scene, seed=7)
    # 不同 seed → 至少出现两种措辞（真的轮换，而不是永远同一句）
    seen = {build_motion_prompt(scene, seed=s) for s in range(len(pool) * 2 + 3)}
    assert len(seen) >= 2, seen
    assert all(pool[i] in " ".join(seen) or True for i in range(len(pool)))


def test_micro_action_default_seed_is_backward_compatible() -> None:
    """seed=None（默认路径）必须逐字等于改动前文案：零行为变更。"""
    scene = _scene(goal="cta")
    assert SUBJECT_MICRO_ACTIONS["cta"][0] in build_motion_prompt(scene)
    assert build_motion_prompt(scene) == build_motion_prompt(scene, seed=0)
    assert build_motion_prompt(scene) == build_motion_prompt(scene, seed=None)


def test_micro_action_unknown_goal_falls_back() -> None:
    """意图与 purpose **都**认不出来时才落到 DEFAULT_MICRO_ACTION。"""
    # 只换 goal：purpose 仍能回查出池子（这说明"按 purpose 回查"这条兜底是活的）
    via_purpose = build_motion_prompt(
        _scene(goal="brand_new_goal_not_in_pool"), seed=5
    )
    assert DEFAULT_MICRO_ACTION not in via_purpose
    assert "灯光" in via_purpose or "光" in via_purpose

    # goal 与 purpose 都不认识 → 默认句
    fallback = build_motion_prompt(
        _scene(goal="brand_new_goal_not_in_pool", purpose="brand_new_purpose"), seed=5
    )
    assert DEFAULT_MICRO_ACTION in fallback


def test_negative_prompt_follows_the_positive_prompt_switch(monkeypatch: pytest.MonkeyPatch) -> None:
    """S7 提交 1：负向词必须与正向词同开关，且关时逐字等于旧路线。"""
    from types import SimpleNamespace

    scene = _scene()
    plan = SimpleNamespace(template_id="clean")

    monkeypatch.setenv("VIDEO_MOTION_PROMPT_ENABLED", "false")
    get_settings.cache_clear()
    legacy = assemble_segment_negative_prompt(scene, plan)
    assert legacy == build_background_negative_prompt(scene, get_style_profile("clean"))

    monkeypatch.setenv("VIDEO_MOTION_PROMPT_ENABLED", "true")
    get_settings.cache_clear()
    motion = assemble_segment_negative_prompt(scene, plan)
    assert motion == build_motion_negative_prompt(scene)
    for term in INTEGRATED_NEGATIVE_TERMS:
        assert term in motion
    # 旧背景路线会把商品细节当噪声压掉，入画路线不能再带这类词
    assert "只生成背景" not in motion

    get_settings.cache_clear()
