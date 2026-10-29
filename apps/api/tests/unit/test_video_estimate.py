from types import SimpleNamespace

from onetake_api.config import Settings
from onetake_api.modules.video_plan.estimate import estimate_video_generation


def _plan(*, mode: str = "product", template_id: str | None = "dynamic", duration_seconds: float = 18.0):
    return SimpleNamespace(id="vid_test", mode=mode, template_id=template_id, duration_seconds=duration_seconds)


def test_dynamic_real_estimate_counts_wan_clips_and_missing_prices() -> None:
    settings = Settings(
        mock_providers=False,
        product_scene_enabled=True,
        image_edit_provider="real",
        wan_i2v_provider="real",
        composition_provider="shotstack",
        wan_i2v_max_seconds=5,
        wan_i2v_price_per_second=0.15,
        qwen_image_edit_price_per_call=None,
        shotstack_render_price=None,
        video_estimate_minutes_per_clip=1.0,
        video_estimate_overhead_minutes=0.5,
    )

    estimate = estimate_video_generation(_plan(duration_seconds=18), settings)

    # 4 镜里使用镜是 7 秒，按 5 秒上限拆成两次，所以是 5 次调用、仍共 14 秒。
    assert estimate.wan_clip_count == 5
    assert estimate.wan_generated_seconds == 14
    assert estimate.estimated_wan_cost == 2.1
    assert estimate.qwen_image_edit_calls == 0
    assert estimate.shotstack_renders == 1
    assert estimate.requires_confirmation is True
    # Phase 1 起关键帧生成是可计费步骤：未配置单价时必须如实报"待核算"，
    # 而不是静默按 0 成本处理。
    assert estimate.keyframe_calls == 4
    assert estimate.keyframe_images == 4 * settings.keyframe_candidates
    assert estimate.path == "segmented"
    assert estimate.composition == "shotstack"
    assert estimate.missing_price_config == ["QWEN_IMAGE_PRICE_PER_CALL", "SHOTSTACK_RENDER_PRICE"]


def test_keyframe_cost_is_not_counted_when_pixel_path_disabled() -> None:
    settings = Settings(
        mock_providers=False,
        product_scene_enabled=True,
        image_edit_provider="real",
        wan_i2v_provider="real",
        composition_provider="shotstack",
        keyframe_mode="erase_background",
        qwen_image_price_per_call=0.05,
    )
    estimate = estimate_video_generation(_plan(), settings)
    assert estimate.keyframe_calls == 0
    assert estimate.keyframe_images == 0


def test_keyframe_price_configured_is_reflected() -> None:
    settings = Settings(
        mock_providers=False,
        product_scene_enabled=True,
        image_edit_provider="real",
        wan_i2v_provider="real",
        composition_provider="shotstack",
        keyframe_mode="integrated",
        keyframe_candidates=2,
        qwen_image_price_per_call=0.05,
        shotstack_render_price=1.0,
    )
    estimate = estimate_video_generation(_plan(), settings)
    assert estimate.keyframe_calls == 4
    assert estimate.keyframe_images == 8
    assert "QWEN_IMAGE_PRICE_PER_CALL" not in estimate.missing_price_config
    # 只"知道单价"不够 —— 必须**并入总额**。曾经这里只检查单价、不累加，
    # 于是费用审批闸批的是一个**少于实际**的金额（本次实测漏算 4×0.5=2 元）。
    assert estimate.estimated_known_cost == round(2.1 + 4 * 0.05 + 1.0, 2)
    assert any("关键帧" in note for note in estimate.price_notes), estimate.price_notes


def test_mock_estimate_does_not_require_confirmation() -> None:
    settings = Settings(mock_providers=True, wan_i2v_provider="mock", composition_provider="mock")
    estimate = estimate_video_generation(_plan(), settings)
    assert estimate.is_paid is False
    assert estimate.requires_confirmation is False
    assert estimate.wan_clip_count == 0
    assert estimate.estimated_known_cost == 0.0


def test_avatar_mode_has_no_dedicated_estimate_after_downgrade() -> None:
    """M4-04：avatar 档位下线后**不得再有** S2V 专属估算路径。

    这里**刻意**直接构造 mode="avatar" 的计划（绕过请求层契约），用来证明域层也没有残留分支：
    即使被硬塞进来，也不会走出片估算，也不会再报已删除的 WAN_S2V_PRICE_PER_SECOND 缺价。
    """
    settings = Settings(
        mock_providers=False,
        wan_i2v_provider="mock",
        composition_provider="local",
    )
    estimate = estimate_video_generation(_plan(mode="avatar", template_id=None, duration_seconds=12.1), settings)
    assert estimate.wan_clip_count == 0
    assert estimate.wan_generated_seconds == 0
    assert estimate.estimated_wan_cost == 0.0
    assert estimate.is_paid is False
    assert "WAN_S2V_PRICE_PER_SECOND" not in estimate.missing_price_config


def test_avatar_mode_never_reports_s2v_missing_price() -> None:
    """S2V 单价配置已删除，估算结果里也不再可能出现这条缺价。"""
    settings = Settings(
        mock_providers=False,
        wan_i2v_provider="real",
        wan_i2v_model="wan2.6-i2v",
        composition_provider="local",
        dashscope_api_key="configured",
    )
    estimate = estimate_video_generation(_plan(mode="avatar", template_id=None, duration_seconds=18), settings)
    assert estimate.wan_clip_count == 0
    assert estimate.estimated_wan_cost == 0.0
    assert "WAN_S2V_PRICE_PER_SECOND" not in estimate.missing_price_config


def test_all_product_templates_use_real_scene_segmentation() -> None:
    settings = Settings(
        mock_providers=False,
        product_scene_enabled=True,
        image_edit_provider="real",
        wan_i2v_provider="real",
        composition_provider="shotstack",
        wan_i2v_max_seconds=5,
        wan_i2v_price_per_second=0.15,
        shotstack_render_price=None,
    )

    for template_id in ("clean", "dynamic", "lifestyle"):
        estimate = estimate_video_generation(_plan(template_id=template_id, duration_seconds=18), settings)
        assert estimate.wan_clip_count == 5
        assert estimate.wan_generated_seconds == 14
        assert estimate.estimated_wan_cost == 2.1


def test_keyframe_cost_is_included_in_the_approved_amount() -> None:
    """回归（费用审批的钱口径）：关键帧是付费步骤，必须进 `estimated_known_cost`。

    为什么单独锁一条：费用审批闸（`require_cost_approval`）拿这个数**当批钱依据**，
    少报就等于让"先看预估再批准"这条硬约束失效。用户的真实配置形状：
    分段路径 + `keyframe_mode=integrated` + Qwen 关键帧 0.5 元/次 + Wan i2v 0.5 元/秒 + 本地合成（0 元）。
    修复前它算出 9 元（漏掉 4 次关键帧共 2 元），修复后是 11 元。
    """
    settings = Settings(
        mock_providers=False,
        wan_i2v_provider="real",
        composition_provider="local",
        keyframe_mode="integrated",
        keyframe_candidates=2,
        qwen_image_price_per_call=0.5,
        wan_i2v_price_per_second=0.5,
        wan_i2v_max_seconds=5,
    )

    estimate = estimate_video_generation(_plan(duration_seconds=20), settings)

    assert estimate.keyframe_calls == 4
    keyframe_cost = estimate.keyframe_calls * 0.5           # 2.0
    video_cost = estimate.wan_generated_seconds * 0.5       # 14 秒 → 7.0
    assert estimate.estimated_known_cost == round(keyframe_cost + video_cost, 2)
    # 合成走本地 → 不产生 shotstack 费用，也不该报缺价
    assert estimate.shotstack_renders == 0
    assert estimate.missing_price_config == []
    assert estimate.estimated_cost_max == estimate.estimated_known_cost


def test_segmented_estimate_attributes_kf2v_and_i2v_prices() -> None:
    """预估按**真实归属**计价：带尾帧的调用走 kf2v，没有尾帧的走 i2v。

    拆开的镜只有最后一次能带尾帧，所以 7 秒使用镜的前半段记 i2v。
    改动前把所有秒数都按 i2v 单价算 —— 既高估（kf2v 更便宜），
    又因此掩盖了"超上限的镜被钳成 5 秒"的缺陷。
    """
    settings = Settings(
        mock_providers=False,
        wan_i2v_provider="real",
        composition_provider="local",
        dashscope_api_key="test-key",
        wan_kf2v_model="wan2.2-kf2v-flash",
        video_kf2v_enabled=True,
        keyframe_mode="integrated",
        keyframe_candidates=2,
        qwen_image_price_per_call=0.5,
        wan_i2v_price_per_second=0.5,
        wan_kf2v_price_per_second=0.48,
        wan_i2v_max_seconds=5,
    )

    estimate = estimate_video_generation(_plan(duration_seconds=20), settings)

    # 短版 4 镜 1/2/7/4（14s）。7 秒镜拆成 4+3，只有这一镜的最后一次能用尾帧。
    # 调用计划：1(kf2v) + 2(kf2v) + 4(i2v) + 3(kf2v) + 4(i2v)
    assert (estimate.kf2v_clips, estimate.i2v_clips) == (3, 2)
    assert estimate.wan_clip_count == 5
    assert estimate.wan_generated_seconds == 14
    assert estimate.estimated_wan_cost == round(6 * 0.48 + 8 * 0.5, 2)
    assert estimate.estimated_known_cost == round(estimate.estimated_wan_cost + 4 * 0.5, 2)
    assert any("kf2v" in note for note in estimate.price_notes), estimate.price_notes


def test_segmented_estimate_falls_back_to_i2v_without_kf2v_config() -> None:
    """没有 Key/模型（kf2v 不可用）时不能假装会用 kf2v —— 全部按 i2v 计价，且不报 kf2v 缺价。"""
    settings = Settings(
        mock_providers=False,
        wan_i2v_provider="real",
        composition_provider="local",
        dashscope_api_key="",          # ← 没有 Key → kf2v 不可用
        wan_kf2v_model="wan2.2-kf2v-flash",
        video_kf2v_enabled=True,
        keyframe_mode="integrated",
        wan_i2v_price_per_second=0.5,
        wan_kf2v_price_per_second=None,
        wan_i2v_max_seconds=5,
    )

    estimate = estimate_video_generation(_plan(duration_seconds=20), settings)

    assert estimate.kf2v_clips == 0
    assert estimate.i2v_clips == 5
    assert estimate.estimated_wan_cost == round(14 * 0.5, 2)
    assert "WAN_KF2V_PRICE_PER_SECOND" not in estimate.missing_price_config


def test_stock_enabled_subtracts_absent_shot_from_segmented_estimate() -> None:
    """批次 4a：空镜由免 Key 素材填充 → 那一次 i2v/kf2v 调用**必须**从预估里扣掉。

    费用审批闸拿 `estimated_known_cost` 批钱：多报会挡住用户，少报会让硬约束失效
    （本项目已因"预估漏项/错项"修过两次，所以这条要有单测钉住）。
    """
    base = {
        "mock_providers": False,
        "product_scene_enabled": True,
        "image_edit_provider": "real",
        "wan_i2v_provider": "real",
        "composition_provider": "local",
        "wan_i2v_max_seconds": 5,
        "wan_i2v_price_per_second": 0.15,
        "wan_kf2v_price_per_second": 0.48,
        "qwen_image_price_per_call": 0.5,
    }
    without_stock = estimate_video_generation(_plan(duration_seconds=18), Settings(**base))
    with_stock = estimate_video_generation(_plan(duration_seconds=18), Settings(**base, stock_enabled=True))

    # 空镜仍是第一镜，扣掉的秒数等于这一镜的时长。
    # 切片 A 把商品入画提前到第 2 镜结束（≤3s），铺垫镜因此短于原来的 3 秒。
    from onetake_api.modules.content_plan.generator import BEATS

    absent = BEATS[0]
    assert absent["product_mode"] == "absent"
    absent_seconds = int(round(absent["end"] - absent["start"]))
    assert absent["end"] <= 3.0
    assert with_stock.wan_generated_seconds == without_stock.wan_generated_seconds - absent_seconds
    assert with_stock.estimated_wan_cost < without_stock.estimated_wan_cost
    assert any("0 成本素材" in note for note in with_stock.price_notes), with_stock.price_notes
    # 关键帧那一步照常跑（本刀不省），所以关键帧费用不变 —— 这是**如实**的口径
    assert with_stock.keyframe_calls == without_stock.keyframe_calls

def _grid_settings(**overrides):
    base = dict(
        mock_providers=False,
        image_edit_provider="real",
        wan_i2v_provider="real",
        composition_provider="local",
        keyframe_candidates=2,
        qwen_image_price_per_call=0.5,
        wan_i2v_price_per_second=0.5,
        wan_kf2v_price_per_second=0.48,
        wan_i2v_max_seconds=5,
    )
    base.update(overrides)
    return Settings(**base)


def test_grid_keyframe_mode_counts_grid_call_and_worst_case_fallback() -> None:
    """`KEYFRAME_MODE=grid`：1 次调用出一整张网格（4 格），坏格过半会整片回退单帧 → 两者都要进预估。

    2026-10-15 实测缺陷：原先只在 `keyframe_mode == "integrated"` 时计关键帧费用，grid 档被算成
    **0 次 / ¥0**（自查脚本输出"关键帧 0 次 / 0 张"），而实际要花 1 次 qwen-image（¥0.5）；坏片回退后
    是 1+4 次（¥2.5）。费用审批闸就是拿 `estimated_known_cost` 批钱的 → 少报 = 硬约束失效
    （与 2026-10-14 漏算整笔关键帧是同一类缺陷）。
    """
    grid = estimate_video_generation(_plan(), _grid_settings(keyframe_mode="grid"))
    # 参照系：erase_background 走本地素材、不调供应商 → 它的总额就是"纯视频部分"
    video_only = estimate_video_generation(_plan(), _grid_settings(keyframe_mode="erase_background"))
    integrated = estimate_video_generation(_plan(), _grid_settings(keyframe_mode="integrated"))

    assert video_only.keyframe_calls == 0 and video_only.keyframe_images == 0
    assert grid.keyframe_calls == 1 and grid.keyframe_images == 4          # 1 次调用 / 4 格
    assert grid.estimated_known_cost == round(video_only.estimated_known_cost + 0.5, 2)
    # 最坏情况（坏格过半 → 4 镜各自回退单帧）只进"上限"，不进"已知费用"
    assert grid.estimated_cost_max == round(video_only.estimated_known_cost + 0.5 + 4 * 0.5, 2)
    assert any("九宫格档" in note for note in grid.price_notes), grid.price_notes

    # 回归：integrated 档口径不变（4 次 / 8 张，且没有回退 → 上限 = 已知）
    assert integrated.keyframe_calls == 4 and integrated.keyframe_images == 8
    assert integrated.estimated_cost_max == integrated.estimated_known_cost


def test_grid_keyframe_mode_scales_with_scene_count(monkeypatch) -> None:
    """分镜多于"每张网格的格数"时要按 ceil 计网格次数（目前 2×2 = 4 格/张）。"""
    from onetake_api.modules.video_plan import estimate as estimate_module

    beats = list(estimate_module.BEATS)
    extra_beats = [dict(beat, start=beat["start"] + 18.0, end=beat["end"] + 18.0) for beat in beats[:2]]
    monkeypatch.setattr(estimate_module, "BEATS", beats + extra_beats)   # 4 → 6 镜

    grid = estimate_video_generation(_plan(), _grid_settings(keyframe_mode="grid"))
    assert grid.keyframe_calls == 2                 # ceil(6 / 4)
    assert grid.keyframe_images == 8                # 2 张 × 4 格
    assert grid.estimated_cost_max == round(grid.estimated_known_cost + 6 * 0.5, 2)   # 最坏再 +6 次单帧
