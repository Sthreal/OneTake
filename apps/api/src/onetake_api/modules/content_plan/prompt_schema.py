from __future__ import annotations

from dataclasses import dataclass

from onetake_api.integrations.product_scene.product_constraints import fidelity_block, integrated_negative_prompt
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


FORBIDDEN_BACKGROUND_TERMS = (
    "true fruit milk",
    "杯子",
    "杯架",
    "瓶子",
    "玻璃杯",
    "餐具",
    "器皿",
    "托盘",
    "碗",
    "罐",
    "容器",
    "盒子",
    "包装",
    "物品",
    "物体",
    "道具",
    "发丝",
    "logo",
    "水印",
    "糖、防腐剂",
    "高果糖玉米糖浆",
    "人工色素",
)


def _clean_custom_prompt(prompt: str) -> str:
    cleaned = (prompt or "").strip()
    if not cleaned:
        return ""
    lowered = cleaned.lower()
    if any(term in lowered for term in FORBIDDEN_BACKGROUND_TERMS):
        return ""
    return cleaned


def build_background_prompt(scene: ContentScene, style_profile: StyleProfile | None = None) -> str:
    custom = _clean_custom_prompt(scene.prompt or "")
    if custom:
        return (
            f"{custom.rstrip('。')}。"
            # 运镜是分镜层字段：自定义文案只覆盖场景描述，不应吞掉镜头信息
            f"镜头：{camera_move_phrase(scene.camera_move)}。"
            "只生成背景，不出现商品、包装、Logo、文字、水印、杯子、瓶子、玻璃杯、餐具、容器、盒子、道具、人物、植物或其他主体；"
            "中央预留区域保持为空，只保留环境、光线和空间氛围。"
        )
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


# ==================== Phase 0 冻结契约：前端可选项 ====================
# 这些枚举是前端下拉框的唯一数据源；Phase 1 起 product_mode 支持 integrated（商品入画）。

TRANSITIONS: dict[str, str] = {
    "cut_in": "硬切进入",
    "fade": "淡入淡出",
    "fade_in": "淡入",
    "fade_out": "淡出",
    "wipe_left": "左滑转场",
    "none": "无转场",
}

PRODUCT_MODES: dict[str, str] = {
    "absent": "不出现商品",
    "overlay": "商品叠加展示",
    "closeup": "商品特写",
    "integrated": "商品融入场景（Phase 1 起）",
}


def list_camera_options() -> list[tuple[str, str]]:
    """运镜可选项：(标识, 中文说明)，顺序沿用 CAMERA_MOVES 定义顺序。"""
    return [(key, label) for key, label in CAMERA_MOVES.items()]


def list_transition_options() -> list[tuple[str, str]]:
    return [(key, label) for key, label in TRANSITIONS.items()]


def list_product_mode_options() -> list[tuple[str, str]]:
    return [(key, label) for key, label in PRODUCT_MODES.items()]

# ==================== Phase 1：关键帧「商品入画」提示词 ====================
# 与 build_background_prompt（空背景，erase 路径专用）刻意分开：
# 这里要求商品必须出现在画面里，并附上保真约束；校验方向也随之为"商品必须存在"。


# 「无人物」这类**写死**的话：一旦这次绑了出镜人，提示词里就必须改写，否则自相矛盾
# （场景说"无人物户外环境"、我们又要求"这个人手持商品"——模型只会折中成一张没有人的图）。
_NO_PERSON_PHRASES = ("无人物", "不含人物", "没有人", "无人出镜")


def person_aware_action(text: str) -> str:
    """把场景描述里的"无人物"改写掉（**只在这次有出镜人时调用**）。"""
    cleaned = str(text or "")
    for phrase in _NO_PERSON_PHRASES:
        cleaned = cleaned.replace(phrase, "出镜人入画")
    return cleaned


def character_interaction_block(*, character_ref: int, product_ref: int) -> str:
    """人物 × 商品互动块。

    **编号必须与输入图顺序一致**（qwen-image-edit：中文提示词用「图 N」指代输入图，顺序与 images 一致）。
    这是本仓"人物和商品交互"的唯一来源：把人像当**第二张输入图**喂进去，并在提示词里要求手部真实接触商品。
    """
    return (
        f"出镜人：图 {character_ref} 是本次出镜的人（脸型、发型、肤色、服装配色以此为准，必须是同一个人）。"
        f"让图 {character_ref} 中的人物**手持**图 {product_ref} 中的商品：手部与商品真实接触，"
        "商品朝向镜头、不被手指遮挡，包装文字与 LOGO 清晰不变形。"
        "只出现这一个人：不要第二个人、不要换脸、不要拼接感。"
    )


def build_storyboard_grid_prompt(rows: int, cols: int, *, character_ref: int | None = None, product_ref: int = 1) -> str:
    """九宫格整图提示词（批次 3）。

    三条硬约束来自批次 0 的实测（以及参考实现的实战经验）：
    1. **整图必须是 9:16 竖版** → 每格自动也是 9:16，裁出来可直接当关键帧；
    2. 格与格之间**只留极细白缝**（裁切端按实测白缝定位，不靠固定内缩）；
    3. **格内不得出现任何文字/编号/水印/边框**（格会被裁出来当关键帧，任何文字都会污染画面）。
    """
    total = rows * cols
    lines = [
        f"一张 {rows}x{cols} 等分的分镜图（共 {total} 个格）；整图必须是 9:16 竖版，每格因此也是 9:16 竖构图。",
        "格与格之间只留一条极细的白色分隔缝（细到裁切时按实测缝位置内缩即可去掉），不要粗边框、不要外框。",
        f"{total} 个格是同一支带货视频的不同镜头：同一商品、同一空间、同一光线方向与色调，商品外观与包装配色在各格间保持一致。",
        "每格是一个独立镜头的画面，构图按竖屏设计；每格都是该镜动作即将开始前一瞬的定格。",
        "画面里不得出现任何文字、字幕、编号、数字、水印、边框装饰或分格线以外的线条。",
        f"商品实拍图见输入图 {product_ref}：各格中的商品外观、配色与包装必须与其完全一致，不得变形、重绘或改色。",
    ]
    if character_ref is not None:
        # 有出镜人：每格都要这个人**手持商品**，且各格是同一个人的不同镜头（否则四格会出现四张不同的脸）。
        lines.append(character_interaction_block(character_ref=character_ref, product_ref=product_ref))
        lines.append(
            f"{total} 个格里的出镜人必须是**同一个人**（五官、发型、服装配色一致），只是动作/机位不同。"
        )
    return "\n".join(lines)

def build_keyframe_prompt(
    scene: ContentScene,
    style_profile: StyleProfile | None = None,
    *,
    character_ref: int | None = None,
    product_ref: int = 1,
) -> str:
    """商品入画关键帧提示词：场景 + 构图 + 保真约束（有出镜人时再加人物×商品互动块）。"""
    schema = from_scene(scene, style_profile)
    parts = [
        f"时长：{schema.duration_seconds:.1f}秒。",
        f"场景：{schema.environment}。",
        f"光线：{schema.lighting}。",
        f"镜头：{schema.camera}。",
        f"全局风格：{schema.style_prompt}。",
        "把参考图中的商品原样放入画面中央偏下的位置，商品在画面中清晰可见、约占画面高度的 60%~75%。",
        f"保真要求：{fidelity_block()}",
        "只输出一张 9:16 竖版成图，不添加任何文字、字幕、水印或促销标签。",
    ]
    if character_ref is not None:
        parts.append(character_interaction_block(character_ref=character_ref, product_ref=product_ref))
    return "".join(parts)


def build_keyframe_negative_prompt(
    scene: ContentScene, style_profile: StyleProfile | None = None, *, with_character: bool = False
) -> str:
    style = style_profile or get_style_profile(None)
    base = integrated_negative_prompt(style.negative_prompt)
    if not with_character:
        return base
    # 有人时必须显式排除"第二个人的手/脸"这类最常见污染（否证也是提示词的一部分）
    return base + "、第二个人、换脸、多出来的手、多余的手指、拼贴感"