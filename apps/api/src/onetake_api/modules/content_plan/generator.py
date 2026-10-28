from __future__ import annotations

from dataclasses import replace

from onetake_api.modules.content_plan.domain import ContentScene, ContentVariant
from onetake_api.modules.content_plan.hook_library import pick_hook
from onetake_api.modules.content_plan.product_shapes import infer_product_shape, shape_hint

# 6 档风格（批次 2：原 3 档不动，新增 3 档）。
# ⚠️ 刻意**不引** comparison / unboxing：它们命中本仓 `compliance/platform_rules.py::AI_REVIEW_STYLES`
# （抖音禁止 AI 生成的对比/测评内容），引进来等于给自己造一个必然触发的合规警告。
STYLES = {
    "clean": ("干净展示", "浅色影棚和简洁光线，突出商品细节"),
    "story": ("生活故事", "自然生活场景和真实光线，突出使用感"),
    "trend": ("动态短视频", "高饱和广告色彩、短促节奏和清晰推进"),
    "scene": ("场景安利", "真实生活场景里的自然使用，光线柔和，重点在场景氛围而不是商品特写"),
    "pain_point": ("痛点种草", "先呈现问题所在的空间与状态，再让解决方式自然出现，避免夸张表演"),
    "product_pov": ("商品拟人第一人称", "以商品为主视角的镜头运动（贴近、环绕、起身），仿佛商品自己在看使用场景"),
}
# 第 2 镜必须在这一秒数结束前入画（切片 A）。开场镜仍可 absent 铺垫，所以它必须更短。
PRODUCT_IN_FRAME_DEADLINE_SECONDS = 3.0
# 短版（约 14 秒）也强制（P5A）：第 3 镜给出还没做完的下一步。只约束画面，不改写用户口播。
USAGE_RETENTION_CUE = "中段留一个还没完成的下一步（盖子即将旋开或手停在半空），让人想继续看"

BEATS = [
    {
        "purpose": "hook",
        "visual_goal": "pain_point",
        "shot_type": "lifestyle_scene",
        "start": 0.0,
        "end": 1.0,
        "subject_action": "办公室桌面和空杯环境，冷色光线，表达工作后的疲惫感，镜头缓慢推近",
        "camera_move": "slow_push_in",
        "product_mode": "absent",
        "transition": "cut_in",
    },
    {
        "purpose": "selling_point",
        "visual_goal": "product_reveal",
        "shot_type": "product_reveal",
        "start": 1.0,
        "end": PRODUCT_IN_FRAME_DEADLINE_SECONDS,
        "subject_action": "背景灯光渐亮，展示台显形，空间自然变化，镜头缓慢推近",
        "camera_move": "push_in",
        "product_mode": "overlay",
        "transition": "fade",
    },
    {
        # 开场两镜合计压进 3 秒后，多出来的时长放在使用镜（7 秒）。
        # 分段生成会按单次上限拆开，总秒数仍是 14，不改运动提示词。
        "purpose": "usage_scenario",
        "visual_goal": "usage_scenario",
        "shot_type": "usage_scene",
        "start": 3.0,
        "end": 10.0,
        "subject_action": "展示无人物户外运动环境，树叶和光线轻微运动，镜头稳定推进",
        "camera_move": "tracking",
        "product_mode": "overlay",
        "transition": "fade",
    },
    {
        "purpose": "cta",
        "visual_goal": "cta",
        "shot_type": "cta_closeup",
        "start": 10.0,
        "end": 14.0,
        "subject_action": "影棚灯光柔和变化，中央平台保持稳定，镜头缓慢推近",
        "camera_move": "slow_push_in",
        "product_mode": "closeup",
        "transition": "fade_out",
    },
]


# 空镜的英文检索词表（批次 4a）：只表达**场景**，不含任何商品/品类词 ——
# 因为空镜的定位是"痛点/氛围铺垫"，一旦把品类写进去，换商品就得改表。
# 键是 `visual_goal`（与 BEATS 的取值域一致），值交给 Wikimedia Commons 检索。
ABSENT_STOCK_QUERIES = {
    "pain_point": "morning desk workspace light",
    "usage_scenario": "outdoor walking morning light",
    "cta": "studio soft light background",
    "product_reveal": "studio soft light background",
}


def default_stock_query(visual_goal: str) -> str:
    """空镜检索词的**兜底映射**（LLM 路径没给 `stock_query` 时也能用同一套口径）。"""
    return ABSENT_STOCK_QUERIES.get((visual_goal or "").strip().lower(), "")


def generate_rule_variants(
    *, segments: list[dict], product_name: str = "", product_note: str = "", seed: int | None = None
) -> list[ContentVariant]:
    """按 6 档风格生成变体（批次 2：风格 3 → 6、空镜改用**钩子库**、按商品形态给倾向）。

    - `product_name` / `product_note` 只用于**确定性推断商品形态**（判不出来就不给倾向）；
    - `seed` 只影响"同一档风格里挑哪条钩子"（`None` → 稳定取第一条，保证可复现）。
    """
    if not segments:
        raise ValueError("字幕段落为空")
    ordered = sorted(segments, key=lambda item: float(item["start"]))
    shape = infer_product_shape(product_name, product_note)
    visual_hint, copy_hint = shape_hint(shape)
    variants: list[ContentVariant] = []
    for style, (name, style_prompt) in STYLES.items():
        allocated = _allocate_segments(ordered)
        hook = pick_hook(style=style, shape=shape, seed=seed)
        scenes: list[ContentScene] = []
        for index, beat in enumerate(BEATS):
            scene_segments = allocated[index]
            absent = beat["product_mode"] == "absent"
            subject_action = beat["subject_action"]
            stock_query = ""
            if absent:
                # 空镜：开场画面由**钩子库**决定（stop / prove / bridge 三段），
                # 并顺手给出该场景的英文检索词（供免 Key 素材用）。
                subject_action = hook.instruction
                stock_query = hook.stock_query if beat["visual_goal"] == "pain_point" else ""
            if beat["purpose"] == "usage_scenario" and USAGE_RETENTION_CUE not in subject_action:
                subject_action = f"{subject_action}。{USAGE_RETENTION_CUE}"
            prompt = (
                f"场景目标：{beat['visual_goal']}。"
                f"{subject_action}。镜头：{beat['camera_move']}。{style_prompt}。"
            )
            if not absent and (visual_hint or copy_hint):
                # 商品形态倾向只加在**有商品入画**的镜头上（空镜里没有商品，加了会误导生成）
                if visual_hint:
                    prompt += f"（商品形态：{visual_hint}）"
                if copy_hint:
                    prompt += f"（表达倾向：{copy_hint}）"
            scenes.append(ContentScene(
                scene_id=f"scene_{index + 1}",
                order=index + 1,
                purpose=beat["purpose"],
                script_excerpt="".join(str(item.get("text", "")) for item in scene_segments),
                start_seconds=beat["start"],
                end_seconds=beat["end"],
                shot_type=beat["shot_type"],
                prompt=prompt,
                overlay_product=beat["product_mode"] != "absent",
                product_position="center",
                background_style=style,
                template_id=style,
                subtitle_segment_ids=[int(item.get("index", index + 1)) for item in scene_segments],
                qa_rules=["product_visible", "script_fidelity", "subtitle_alignment", "no_extra_text", "narrative_structure"],
                visual_goal=beat["visual_goal"],
                # ⚠️ `subject_action` 必须**不含「商品」二字**（既有断言要求：场景描述不提商品）
                subject_action=subject_action,
                camera_move=beat["camera_move"],
                product_mode=beat["product_mode"],
                transition=beat["transition"],
                stock_query=stock_query,
            ))
        if not second_shot_product_in_frame(scenes):
            raise ValueError("第 2 镜必须在 3 秒内入画，且 product_mode 不能是 absent")
        variants.append(ContentVariant(f"var_{style}", name, style, scenes))
    return variants


def second_shot_product_in_frame(scenes, *, deadline: float = PRODUCT_IN_FRAME_DEADLINE_SECONDS) -> bool:
    """第 2 镜结束时间 ≤ deadline，且商品已经入画（不是 absent 铺垫）。"""
    if len(scenes) < 2:
        return False
    shot = scenes[1]
    return float(shot.end_seconds) <= deadline and shot.product_mode != "absent"


def _allocate_segments(segments: list[dict]) -> list[list[dict]]:
    buckets: list[list[dict]] = [[] for _ in BEATS]
    for segment in segments:
        start = float(segment["start"])
        end = float(segment["end"])
        midpoint = (start + end) / 2
        best_index = 0
        best_overlap = -1.0
        for index, beat in enumerate(BEATS):
            overlap = max(0.0, min(end, beat["end"]) - max(start, beat["start"]))
            if overlap > best_overlap:
                best_index = index
                best_overlap = overlap
        if best_overlap <= 0:
            best_index = min(range(len(BEATS)), key=lambda index: abs(midpoint - (BEATS[index]["start"] + BEATS[index]["end"]) / 2))
        buckets[best_index].append(segment)
    return buckets
