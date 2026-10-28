"""Phase 3 单测：整片编排（分组、提示词、参考图截断）、flatten、r2v 估算口径。"""
from __future__ import annotations

from io import BytesIO
from types import SimpleNamespace

from PIL import Image

from onetake_api.config import Settings
from onetake_api.integrations.media.image_utils import flatten_for_reference
from onetake_api.modules.content_plan.domain import ContentScene
from onetake_api.modules.video_plan.estimate import estimate_video_generation
from onetake_api.modules.video_plan.one_shot import (
    MAX_MEDIA_ITEMS,
    group_beat_durations,
    keyframe_refs_for_call,
    plan_one_shot_calls,
)


def _scene(order: int, *, start: float, end: float, excerpt: str = "", action: str = "展示") -> ContentScene:
    return ContentScene(
        scene_id=f"scene_{order}", order=order, purpose="展示", script_excerpt=excerpt,
        start_seconds=start, end_seconds=end, shot_type="medium", prompt="",
        overlay_product=True, product_position="center", background_style="clean", template_id="clean",
        subtitle_segment_ids=[order], qa_rules=[], visual_goal="product_reveal", subject_action=action,
        camera_move="push_in", product_mode="integrated", transition="fade",
    )


def test_group_beat_durations_splits_at_limit() -> None:
    """18 秒按 15 秒上限 → 两组；且**每组至少 2 镜**。

    2026-10-15 实测：原分组是 [3,3,7]=13 + [5]=5，结果第二次调用只带 first_frame，
    被供应商拒绝（原话「Only first frame provided is not allowed」）—— 跑 6 分钟、钱白花。
    现在把边界后移成 [3,3]=6 + [7,5]=12，两侧都不超上限、每次都有 ≥2 张参考图。
    """
    groups = group_beat_durations([3.0, 3.0, 4.0, 4.0], max_seconds=15)
    assert [sum(group) for group in groups] == [14.0]
    assert all(len(group) >= 2 for group in groups), "任何一组都不许只剩 1 镜（供应商会拒）"


def test_plan_one_shot_calls_keeps_scene_order_and_ids() -> None:
    scenes = [_scene(1, start=0, end=3), _scene(2, start=3, end=6), _scene(3, start=6, end=10), _scene(4, start=10, end=14)]
    calls = plan_one_shot_calls(scenes, max_seconds=15)
    assert len(calls) == 1
    # 短版（3/3/4/4 = 14s）→ 一次调用装得下，零拼接缝；且 4 张参考图 ≥ 供应商下限
    assert calls[0].scene_ids == ["scene_1", "scene_2", "scene_3", "scene_4"]
    assert calls[0].duration_seconds == 14.0
    
    
    assert [call.order for call in calls] == [1]


def test_one_shot_prompt_has_timecodes_dialogue_and_reference_numbers() -> None:
    """提示词格式：2026-10-15 按**阿里官方约定**重写（图 1 带空格）+ 借 ClipForge 的四条意图。

    阿里文档（wan-video-to-video-api-reference）：中文提示词用「图 1、图 2」指代参考图片，
    **字母与数字间要有空格**；只有一张参考图时写「参考图片」。
    ClipForge 意图：逐镜时间码 + 运镜 + 镜头职能 + 无台词显式说明。
    """
    scenes = [_scene(1, start=0, end=3, excerpt="第一句台词", action="开场"), _scene(2, start=3, end=8, excerpt="第二句台词")]
    call = plan_one_shot_calls(scenes, max_seconds=15)[0]
    prompt = call.prompt
    assert "[0-3 秒]" in prompt and "[3-8 秒]" in prompt          # 时间码段落
    assert "图 1" in prompt and "图 2" in prompt                    # 官方写法：字母数字间有空格
    assert "画面以图 1为基准" in prompt                              # 每镜显式引用自己的关键帧
    assert "第一句台词" in prompt and "第二句台词" in prompt
    assert "逐字说出" in prompt                                     # 台词要求逐字（阿里无括号语法，用自然语言）
    assert "运镜：" in prompt                                       # 借 ClipForge：不许丢运镜
    # 借 ClipForge 的镜头职能标签：已知类型映射成中文标签，未知类型回落成 purpose 原文
    assert "（展示" in prompt or "（分镜" in prompt or "开场钩子" in prompt
    # 无台词镜要显式说明（不留空让模型自己编）
    quiet = plan_one_shot_calls([_scene(1, start=0, end=4, excerpt="")], max_seconds=15)[0].prompt
    assert "无台词" in quiet and "环境音" in quiet
    # 单张参考图时用官方简化写法
    assert "参考图片" in quiet
    # 统一收尾约束
    assert "不得变形" in prompt
    assert "不新增文字、字幕、水印" in prompt


def test_keyframe_refs_are_truncated_to_media_limit() -> None:
    scenes = [_scene(index, start=index, end=index + 1) for index in range(1, 8)]
    call = plan_one_shot_calls(scenes, max_seconds=99)[0]
    keyframes = {f"scene_{index}": f"img{index}".encode() for index in range(1, 8)}
    refs = keyframe_refs_for_call(call, keyframes)
    assert len(refs) == MAX_MEDIA_ITEMS
    assert refs[0] == b"img1"


def test_flatten_for_reference_drops_alpha() -> None:
    image = Image.new("RGBA", (64, 64), (255, 0, 0, 128))
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    flattened = flatten_for_reference(buffer.getvalue())
    with Image.open(BytesIO(flattened)) as result:
        assert result.mode == "RGB"
        assert result.getpixel((32, 32)) == (255, 127, 127)


def _one_shot_settings(**overrides) -> Settings:
    base = {
        "mock_providers": False,
        "product_scene_enabled": True,
        "image_edit_provider": "real",
        "wan_i2v_provider": "real",
        "composition_provider": "shotstack",
        "generation_path_default": "one_shot",
        "wan_r2v_max_seconds": 15,
        "wan_r2v_price_per_second": 0.2,
        "wan_i2v_price_per_second": 0.15,
        "shotstack_render_price": 1.0,
    }
    base.update(overrides)
    return Settings(**base)


def test_one_shot_estimate_counts_r2v_calls_not_i2v_clips() -> None:
    plan = SimpleNamespace(id="vid_film", mode="product", template_id="clean", duration_seconds=18.0, path="one_shot")
    estimate = estimate_video_generation(plan, _one_shot_settings())
    assert estimate.r2v_calls == 1
    assert estimate.r2v_seconds == 14
    assert estimate.i2v_clips == 0
    assert estimate.wan_clip_count == 0
    assert estimate.estimated_wan_cost == 2.8  # 18 秒 × 0.2
    assert estimate.path == "one_shot"


def test_one_shot_estimate_flags_missing_r2v_price() -> None:
    plan = SimpleNamespace(id="vid_film", mode="product", template_id="clean", duration_seconds=18.0, path="one_shot")
    estimate = estimate_video_generation(plan, _one_shot_settings(wan_r2v_price_per_second=None))
    assert "WAN_R2V_PRICE_PER_SECOND" in estimate.missing_price_config
    assert estimate.r2v_calls == 1


def test_segmented_estimate_keeps_i2v_metrics() -> None:
    plan = SimpleNamespace(id="vid_seg", mode="product", template_id="clean", duration_seconds=18.0, path="segmented")
    estimate = estimate_video_generation(plan, _one_shot_settings())
    # 使用镜 7 秒会按上限拆成两次，分段调用数是 5；整段秒数仍由各镜相加。
    assert estimate.i2v_clips == 5
    assert estimate.r2v_calls == 0

def test_every_beat_purpose_has_a_chinese_label() -> None:
    """防再漏：BEATS 的每个 purpose 都要有中文标签，且 prompt 里不许残留内部英文枚举。

    2026-10-15 用户实测：usage_scenario 那一镜的标签漏了，prompt 里渲染成了内部英文枚举 ——
    这条测试将来在往 BEATS 加新 purpose 时会先红。
    """
    from onetake_api.modules.content_plan.generator import BEATS
    from onetake_api.modules.video_plan.one_shot import SHOT_TYPE_LABELS

    for beat in BEATS:
        assert beat["purpose"] in SHOT_TYPE_LABELS
    prompt = plan_one_shot_calls(
        [_scene(i + 1, start=beat["start"], end=beat["end"]) for i, beat in enumerate(BEATS)],
        max_seconds=15,
    )[0].prompt
    for beat in BEATS:
        assert beat["purpose"] not in prompt


def test_pause_marks_stripped_and_realism_toggle() -> None:
    """借 ClipForge 的两条：① 台词里的气口标记必须剥掉（否则模型会念出来）；

    ② "实拍质感"块默认开、可关（走强风格化模板时关掉，避免两种观感打架）。
    """
    from onetake_api.modules.video_plan.one_shot import strip_pause_marks

    scene = _scene(1, start=0, end=4, excerpt="第一句[pause]台词（停顿）继续")
    default_prompt = plan_one_shot_calls([scene], max_seconds=15)[0].prompt
    assert "[pause]" not in default_prompt and "（停顿）" not in default_prompt
    assert "第一句台词继续" in default_prompt
    assert "手机日常实拍" in default_prompt                      # #8 默认开
    quiet = plan_one_shot_calls([scene], max_seconds=15, realism=False)[0].prompt
    assert "手机日常实拍" not in quiet                            # #8 可关
    assert strip_pause_marks("[pause][停顿] 台词 (pause)") == "台词"


def test_character_sheet_reference_number_follows_the_media_order() -> None:
    """出镜人母版编号必须是"本组镜数 + 1"——因为 media 顺序是 [各镜关键帧..., 母版]。`n`n    2026-10-16 之后措辞改成硬要求（"图 N 是本次的出镜人…必须出镜并与商品互动"），编号口径不变。

    阿里官方约定：提示词里的"图 N"必须与 media 数组顺序一致、图和视频分别计数。
    这条测试把它钉死：将来谁调整参考图顺序，这里会先红。
    """
    two = plan_one_shot_calls(
        [_scene(1, start=0, end=3), _scene(2, start=3, end=6)], max_seconds=15, has_character=True,
    )[0]
    assert "图 3 是本次的出镜人" in two.prompt
    assert "图 2 是本次的出镜人" not in two.prompt

    four = plan_one_shot_calls(
        [_scene(index, start=index - 1, end=index) for index in range(1, 5)], max_seconds=15, has_character=True,
    )[0]
    assert "图 5 是本次的出镜人" in four.prompt


def test_without_a_character_no_identity_anchor_is_added() -> None:
    call = plan_one_shot_calls([_scene(1, start=0, end=3), _scene(2, start=3, end=6)], max_seconds=15)[0]
    assert "是本次的出镜人" not in call.prompt

def test_one_shot_prompt_requires_the_character_to_appear_and_interact() -> None:
    """2026-10-16：原提示词是条件句「画面中出现人物时…须与图 N 同一人」→ 等于允许人物不出镜。

    实测后果：整片只有商品在展示台上，"人物和商品交互"根本没发生。现在必须是**硬要求**，
    并且场景文本里的"无人物"要按实际情况改写（否则前后自相矛盾）。
    """
    from onetake_api.modules.video_plan.one_shot import build_one_shot_prompt

    scenes = [
        _scene(1, start=0.0, end=5.0, action="展示无人物户外运动环境"),
        _scene(2, start=5.0, end=10.0, action="展示"),
    ]
    prompt = build_one_shot_prompt(scenes, call_start=0.0, call_end=10.0, character_ref=3)
    assert "图 3" in prompt
    assert "必须出镜" in prompt
    assert "手持或试用" in prompt
    assert "无人物" not in prompt, "绑了出镜人就不能再对模型说'无人物'"

    plain = build_one_shot_prompt(scenes, call_start=0.0, call_end=10.0)
    assert "必须出镜" not in plain, "没绑出镜人时不得凭空要求人物出镜"