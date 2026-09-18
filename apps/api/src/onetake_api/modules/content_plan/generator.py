from __future__ import annotations

from onetake_api.modules.content_plan.domain import ContentScene, ContentVariant

PURPOSES = ["hook", "pain_point", "selling_point", "usage_scenario", "cta"]
STYLES = {
    "clean": ("干净展示", "白底或浅色背景，镜头稳定，突出商品细节"),
    "story": ("生活故事", "自然生活场景，轻微人物或环境互动，突出使用感"),
    "trend": ("动态短视频", "快速推进、轻微运镜和节奏切换，突出前 3 秒注意力"),
}
PROMPTS = {
    "hook": "商品在前 2 秒进入画面，用近景和清晰光线制造注意力，不生成新文字。",
    "pain_point": "用环境或人物反应表达痛点，商品保持原始外观并位于安全区。",
    "selling_point": "展示商品卖点对应的细节，镜头轻微运动，不改变包装、文字和颜色。",
    "usage_scenario": "展示商品在已确认使用场景中的自然状态，人物不得遮挡商品主体。",
    "cta": "收尾回到商品正面，保留行动引导字幕安全区，画面稳定不生成额外文字。",
    "story": "增加自然生活场景和轻微人物互动，保持商品外观与已确认事实不变。",
    "trend": "使用短促推进、节奏切换和轻微运镜，保持商品不被遮挡或变形。",
}


def generate_rule_variants(*, segments: list[dict]) -> list[ContentVariant]:
    if not segments:
        raise ValueError("字幕段落为空")
    ordered = sorted(segments, key=lambda item: float(item["start"]))
    variants: list[ContentVariant] = []
    for style, (name, style_prompt) in STYLES.items():
        scenes = []
        count = len(ordered)
        for index, segment in enumerate(ordered):
            if index == 0:
                purpose = "hook"
            elif index == count - 1:
                purpose = "cta"
            else:
                purpose = PURPOSES[min(index, len(PURPOSES) - 2)]
            prompt = f"{PROMPTS[purpose]} {style_prompt}"
            scenes.append(ContentScene(
                scene_id=f"scene_{index + 1}",
                order=index + 1,
                purpose=purpose,
                script_excerpt=str(segment.get("text", "")),
                start_seconds=float(segment["start"]),
                end_seconds=float(segment["end"]),
                shot_type="talking_head" if style == "story" and purpose != "hook" else "product_motion",
                prompt=prompt,
                overlay_product=True,
                product_position="center",
                background_style=style,
                template_id=style,
                subtitle_segment_ids=[int(segment.get("index", index + 1))],
                qa_rules=["product_visible", "script_fidelity", "subtitle_alignment", "no_extra_text"],
            ))
        variants.append(ContentVariant(f"var_{style}", name, style, scenes))
    return variants
