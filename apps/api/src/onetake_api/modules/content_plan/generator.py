from __future__ import annotations

from dataclasses import replace

from onetake_api.modules.content_plan.domain import ContentScene, ContentVariant

STYLES = {
    "clean": ("干净展示", "浅色影棚和简洁光线，突出商品细节"),
    "story": ("生活故事", "自然生活场景和真实光线，突出使用感"),
    "trend": ("动态短视频", "高饱和广告色彩、短促节奏和清晰推进"),
}
BEATS = [
    {
        "purpose": "hook",
        "visual_goal": "pain_point",
        "shot_type": "lifestyle_scene",
        "start": 0.0,
        "end": 3.0,
        "subject_action": "办公室桌面和空杯环境，冷色光线，表达工作后的疲惫感，镜头缓慢推近",
        "camera_move": "slow_push_in",
        "product_mode": "absent",
        "transition": "cut_in",
    },
    {
        "purpose": "selling_point",
        "visual_goal": "product_reveal",
        "shot_type": "product_reveal",
        "start": 3.0,
        "end": 6.0,
        "subject_action": "背景灯光渐亮，展示台显形，空间自然变化，镜头缓慢推近",
        "camera_move": "push_in",
        "product_mode": "overlay",
        "transition": "fade",
    },
    {
        "purpose": "usage_scenario",
        "visual_goal": "usage_scenario",
        "shot_type": "usage_scene",
        "start": 6.0,
        "end": 13.0,
        "subject_action": "展示无人物户外运动环境，树叶和光线轻微运动，镜头稳定推进",
        "camera_move": "tracking",
        "product_mode": "overlay",
        "transition": "fade",
    },
    {
        "purpose": "cta",
        "visual_goal": "cta",
        "shot_type": "cta_closeup",
        "start": 13.0,
        "end": 18.0,
        "subject_action": "影棚灯光柔和变化，中央平台保持稳定，镜头缓慢推近",
        "camera_move": "slow_push_in",
        "product_mode": "closeup",
        "transition": "fade_out",
    },
]


def generate_rule_variants(*, segments: list[dict]) -> list[ContentVariant]:
    if not segments:
        raise ValueError("字幕段落为空")
    ordered = sorted(segments, key=lambda item: float(item["start"]))
    variants: list[ContentVariant] = []
    for style, (name, style_prompt) in STYLES.items():
        allocated = _allocate_segments(ordered)
        scenes: list[ContentScene] = []
        for index, beat in enumerate(BEATS):
            scene_segments = allocated[index]
            prompt = (
                f"场景目标：{beat['visual_goal']}。"
                f"{beat['subject_action']}。镜头：{beat['camera_move']}。{style_prompt}。"
            )
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
                subject_action=beat["subject_action"],
                camera_move=beat["camera_move"],
                product_mode=beat["product_mode"],
                transition=beat["transition"],
            ))
        variants.append(ContentVariant(f"var_{style}", name, style, scenes))
    return variants


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
