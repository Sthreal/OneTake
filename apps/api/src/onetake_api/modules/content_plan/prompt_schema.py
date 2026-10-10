from __future__ import annotations

from dataclasses import dataclass

from onetake_api.integrations.product_scene.style_profiles import StyleProfile, get_style_profile
from onetake_api.modules.content_plan.domain import ContentScene

PROMPT_SCHEMA_VERSION = "v1"
BACKGROUND_NEGATIVE_PROMPT = "商品, 产品, 包装, Logo, 文字, 水印, 火柴人, 人体轮廓, 重复主体, 多重商品, 变形, 卡通, 插画, 低质量, 闪烁, 漂移"

ENVIRONMENTS = {
    "pain_point": "办公室桌面、空杯、纸张、冷色光线和安静压抑的空间",
    "product_reveal": "浅色影棚、简洁展示台、干净背景和柔和渐变光",
    "usage_scenario": "户外公园、长椅、绿植和自然通透的环境",
    "cta": "橙色影棚、中央平台、柔和光晕和干净收尾空间",
}
LIGHTING = {
    "pain_point": "冷色调、轻微阴影、稳定曝光",
    "product_reveal": "暖色主光、柔和边缘光、灯光渐亮",
    "usage_scenario": "自然日光、树叶轻微移动、明亮通透",
    "cta": "暖橙主光、柔和聚光、稳定高光",
}
AUDIO_CUES = {
    "pain_point": "低频环境音",
    "product_reveal": "轻快转场音",
    "usage_scenario": "自然环境声",
    "cta": "收尾提示音",
}
CAMERA_MOVES = {
    "slow_push_in": "镜头缓慢推近，主体逐渐放大",
    "push_in": "镜头稳定推近",
    "fast_push_in": "镜头快速推近，强调节奏",
    "slow_pull_out": "镜头缓慢拉远，交代环境",
    "pull_out": "镜头稳定拉远",
    "slow_pan_left": "镜头缓慢左摇",
    "slow_pan_right": "镜头缓慢右摇",
    "pan_left": "镜头向左平移",
    "pan_right": "镜头向右平移",
    "tilt_up": "镜头缓慢上摇",
    "tilt_down": "镜头缓慢下摇",
    "handheld_follow": "手持跟拍，轻微自然晃动",
    "tracking": "镜头轻微跟随主体",
    "orbit": "镜头环绕主体缓慢移动",
    "static": "固定镜头，画面稳定",
}
DEFAULT_CAMERA_MOVE = "static"


def camera_move_phrase(move: str | None) -> str:
    """把分镜的运镜标识解析为统一提示词；未知值回退到固定镜头并保留原始标识。"""
    key = (move or "").strip()
    if key in CAMERA_MOVES:
        return CAMERA_MOVES[key]
    if key and key != DEFAULT_CAMERA_MOVE:
        return f"{CAMERA_MOVES[DEFAULT_CAMERA_MOVE]}（未知运镜 {key} 已回退）"
    return CAMERA_MOVES[DEFAULT_CAMERA_MOVE]


@dataclass(frozen=True)
class PromptSchema:
    version: str
    goal: str
    duration_seconds: float
    subject_action: str
    environment: str
    camera: str
    lighting: str
    product_mode: str
    transition: str
    fidelity_guard: str
    negative_constraints: str
    audio_cue: str
    style_id: str
    style_name: str
    style_prompt: str


def from_scene(scene: ContentScene, style_profile: StyleProfile | None = None) -> PromptSchema:
    goal = scene.visual_goal or "product_reveal"
    style = style_profile or get_style_profile(None)
    return PromptSchema(
        version=PROMPT_SCHEMA_VERSION,
        goal=goal,
        duration_seconds=max(0.0, scene.end_seconds - scene.start_seconds),
        subject_action=scene.subject_action,
        environment=ENVIRONMENTS.get(goal, ENVIRONMENTS["product_reveal"]),
        camera=camera_move_phrase(scene.camera_move),
        lighting=LIGHTING.get(goal, LIGHTING["product_reveal"]),
        product_mode=scene.product_mode,
        transition=scene.transition,
        fidelity_guard="商品图层必须使用原始透明商品图，保持文字、Logo、颜色和结构不变",
        negative_constraints=BACKGROUND_NEGATIVE_PROMPT,
        audio_cue=AUDIO_CUES.get(goal, "轻微环境音"),
        style_id=style.style_id,
        style_name=style.name,
        style_prompt=style.prompt,
    )


def build_background_prompt(scene: ContentScene, style_profile: StyleProfile | None = None) -> str:
    schema = from_scene(scene, style_profile)
    return (
        f"时长：{schema.duration_seconds:.1f}秒。"
        f"环境：{schema.environment}。动作：{schema.subject_action}。"
        f"镜头：{schema.camera}。光线：{schema.lighting}。"
        f"全局风格：{schema.style_prompt}。"
        "只生成背景，不出现额外主体、文字或水印。"
    )


def build_background_negative_prompt(scene: ContentScene, style_profile: StyleProfile | None = None) -> str:
    schema = from_scene(scene, style_profile)
    style = style_profile or get_style_profile(None)
    return f"{schema.negative_constraints}, {style.negative_prompt}"
