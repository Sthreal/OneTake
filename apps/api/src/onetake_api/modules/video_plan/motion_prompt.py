"""i2v 运动提示词引擎（Phase 2）。

为什么单独一层：i2v 模型的构图与主体来自**首帧**，文本提示词的职责只是**指导运动**。
过去的做法是把关键帧阶段的静态场景描述直接发过去（"环境+光线+风格"），结果运镜不可控、
主体不动、跨镜漂移。这里把提示词压成四段：

    ① 运镜  ② 主体微动作  ③ 商品保真约束（仅商品可见时）  ④ 稳定性收尾

硬性纪律：**不在 i2v 提示词里重述商品外观**——首帧已经承载了外观信息，重述会让模型
去"重画"商品，直接导致标签漂移与身份丢失。

另外提供「症状 → 单变量补丁」：一次只改一个变量，便于定位到底是什么修好了问题。
"""
from __future__ import annotations

import re

from onetake_api.integrations.product_scene.product_constraints import INTEGRATED_NEGATIVE_TERMS
from onetake_api.modules.content_plan.domain import ContentScene
from onetake_api.integrations.product_scene.keyframe_static_guard import static_warning
from onetake_api.integrations.product_scene.physical_actions import (
    SHAPE_MATERIAL_CONSTRAINTS,
    SHAPE_PHYSICAL_ACTIONS,
    resolve_shape_from_prompt,
)
from onetake_api.modules.content_plan.prompt_schema import CAMERA_MOVES, DEFAULT_CAMERA_MOVE, camera_move_phrase

# ---- ① 运镜强度档（枚举优于自由文本，便于模型稳定遵循）----
MOTION_INTENSITIES: dict[str, str] = {
    "subtle": "幅度很小、速度缓慢",
    "normal": "幅度自然、匀速平稳",
    "strong": "幅度明显、节奏更快",
}
DEFAULT_INTENSITY = "normal"

# ---- ② 主体微动作池（按镜头意图给默认，避免“画面全静止”）----
#
# S7 提交 2：每个意图从「一句固定文案」变成「一池**等价措辞**」，按 seed 轮换。三条硬约定：
#   * **首条 = S7 之前的原文案** —— 于是 `seed=None`（默认路径）逐字零行为变更，既有断言全部成立；
#   * 池内措辞必须**语义等价**（只换说法，不新增场景/商品描述），否则提示词会随时间漂移；
#   * 轮换**由 seed 决定**（`seed % len(pool)`）：同 seed 恒定 ⇒ 一条生成链完全可复现。
SUBJECT_MICRO_ACTIONS: dict[str, tuple[str, ...]] = {
    "pain_point": (
        "环境轻微变化（光影流动、尘埃浮动），营造真实空间感",
        "光影与空气感有极轻微流动，画面保持真实的空间层次",
        "背景里的光与尘埃缓慢浮动，空间感自然",
    ),
    "product_reveal": (
        "灯光由弱渐亮扫过主体，画面有轻微呼吸感",
        "光线缓慢扫过主体，亮度有极轻微起伏",
        "主体上的光由暗到亮柔和掠过，画面轻微呼吸",
    ),
    "usage_scenario": (
        "环境自然运动（树叶摇动、窗帘摆动、水波微动）",
        "环境有自然微动，如枝叶轻摇、水面微漾",
        "周围环境保持轻微自然运动（风、水波、布料摆动）",
    ),
    "cta": (
        "光晕轻微起伏，画面稳定收尾",
        "画面在轻微光晕起伏中稳定结束",
        "结尾画面稳定，光晕极轻微起伏",
    ),
}
DEFAULT_MICRO_ACTION = "主体有极轻微的位移与光影变化，画面保持自然"

# ---- ④ 稳定性收尾（廉价但有效地对抗闪烁与形变）----
STABILITY_CLAUSE = "画面稳定，无闪烁、无跳变、无撕裂、无鬼影；不新增文字、水印、多余主体或重复主体。"
CHAIN_CLAUSE = "镜头结束时画面自然过渡到下一镜的构图与光线，衔接处不出现跳变。"

PRODUCT_FIDELITY_CLAUSE = "保持商品的标签、LOGO、印刷文字、配色与结构不变，不得变形、漂移或重画商品。"

# ---- 0 开场：首帧锚定（S7 提交 3）----
# 它是**首帧约束**而不是商品约束：i2v/kf2v 最常见的失真是“重新构图”（导致商品变形、
# 主体位移）。它只声明“从给定首帧继续”，**不引入任何场景/商品描述**，
# 因此不与 §6.1「禁止复述场景」冲突；`product_mode=absent` 的镜头同样需要它。
OPENING_ANCHOR_CLAUSE = "画面从给定首帧的构图与光线开始，不重新构图、不移动主体位置。"


# ---- S5：真实感三档（`plans.motion_realism`）----
REALISM_AUTO = "auto"
REALISM_CONSTRAINTS = "constraints"
REALISM_OFF = "off"
REALISM_TIERS = (REALISM_AUTO, REALISM_CONSTRAINTS, REALISM_OFF)
# **默认 off** = 本片之前的历史输出逐字不变；新项目由建方案时写 auto（见迁移 0024）
DEFAULT_REALISM = REALISM_OFF

# ---- S5 #1：相机冲突 lint（自由文本运镜的护栏）----
# 出处：ClipForge `motion-prompt.ts::hasCameraConflict` —— "固定镜头" + "环绕" 这类**自相矛盾**
# 的指令会让模型给出犹豫、抖动的运镜。**有时序词就不是冲突**（"推近后固定"是合法表达）。
STATIC_CAMERA_RE = re.compile(r"固定|静止|锁定|不动|fixed|static|locked", re.IGNORECASE)
MOVING_CAMERA_RE = re.compile(
    r"环绕|环拍|推近|推进|拉远|拉近|横移|平移|摇镜|摇臂|甩镜|跟随|跟拍|升降|俯冲"
    r"|orbit|push[-\s]?in|pull[-\s]?back|dolly|pan|tilt|track|crane|zoom|whip",
    re.IGNORECASE,
)
SEQUENCE_RE = re.compile(
    r"先|后|然后|随后|接着|再|最后|结尾|开场|开头|then|after|before|finally|ending|start",
    re.IGNORECASE,
)


def has_camera_conflict(camera: str) -> bool:
    """固定 + 移动且**没有时序词** ⇒ 自相矛盾（模型会给出犹豫/抖动的运镜）。"""
    text = camera or ""
    return bool(
        STATIC_CAMERA_RE.search(text) and MOVING_CAMERA_RE.search(text) and not SEQUENCE_RE.search(text)
    )


def resolve_camera_phrase(scene: ContentScene) -> str:
    """运镜短语：枚举键走既有表（逐字不变）；**自由文本**原样采用，自相矛盾时回退。

    改动前：只有 `CAMERA_MOVES` 里的键才被认，写自由文本会被当成"未知运镜"**静默回退成固定镜头**
    （等于"写了运镜没生效"）。S5 口径：**开放逐镜自由文本运镜**，护栏就是上面的冲突 lint。
    """
    raw = (scene.camera_move or "").strip()
    if not raw or raw in CAMERA_MOVES:
        return camera_move_phrase(raw)
    if has_camera_conflict(raw):
        return f"{camera_move_phrase(DEFAULT_CAMERA_MOVE)}（原自由文本运镜自相矛盾，已回退）"
    return raw


# ---- S5 #4 / #5 / #6 / #7：#auto 档叠加的"真实感层"（全部按 seed 轮换，可复现）----
_PERSON_KEYWORDS = ("人", "手", "模特", "主播", "身着", "试穿", "试戴", "上身")
_MATERIAL_SHOT_GOALS = frozenset({"product_reveal", "usage_scenario"})
_MATERIAL_SHOT_TYPES = frozenset({"product_reveal", "usage_scene", "demo"})

EMOTION_LINES: tuple[str, ...] = (
    "人物情绪分三拍：先有触发（视线或身体微微一滞），再由身体动作先行（前倾、抬手），最后才是克制的面部反应",
    "人物反应遵循先身体后表情：肩背的方向变化在前，面部表情浅而克制，不做夸张表演",
)
BEHAVIOR_BEATS: tuple[str, ...] = (
    "手部有小幅自然动作",
    "视线有自然的短暂转移",
    "呼吸与身体重心有极轻的起伏",
    "头发或衣角随动作轻微摆动",
)
LIVING_BACKGROUNDS: tuple[str, ...] = (
    "背景保持轻微活体感：空气流动、光影缓慢移动，避免背景像贴图一样死板",
    "背景有自然细微的变化（光线缓移、轻微空气感），主体之外不出现新物体",
)
FABRIC_HAIR_LAG = "人物的头发与衣物有自然的惯性滞后，动作停下后仍有极短暂余动"
SOUND_DIRECTION = "音效：只保留与画面贴合的环境音与动作音效，无人声说话；环境底噪保持同一空间的连续感。"


def detect_person_shot(scene: ContentScene) -> bool:
    """画面里有没有人（S5 的**启发式**，来自场景文本的关键词匹配）。

    如实登记：本仓 `ContentScene` 没有"有没有人"的显式字段（那是 ClipForge 的 `personShot`），
    因此这里用关键词近似，**判不出来时按"没有人"处理**（宁可少加层，也不给纯商品镜加人物层）。
    """
    haystack = "".join(
        [str(scene.subject_action or ""), str(scene.prompt or ""), str(scene.visual_goal or "")]
    )
    return any(keyword in haystack for keyword in _PERSON_KEYWORDS)


def _is_material_shot(scene: ContentScene) -> bool:
    """演示/商品镜：值得加"材质反馈"的镜头（对应 ClipForge 的 `PHYSICAL_ACTION_TYPES`）。"""
    return (
        str(scene.visual_goal or "").strip() in _MATERIAL_SHOT_GOALS
        or str(scene.shot_type or "").strip() in _MATERIAL_SHOT_TYPES
    )


def _pick(pool: tuple[str, ...], seed: int | None) -> str:
    """`seed=None`（或非正整数）取首条 —— 与 `_micro_action` 同一套可复现契约。"""
    if isinstance(seed, int) and not isinstance(seed, bool) and seed > 0:
        return pool[seed % len(pool)]
    return pool[0]


def pick_emotion_line(seed: int | None = None) -> str:
    return _pick(EMOTION_LINES, seed)


def pick_living_background(seed: int | None = None) -> str:
    return _pick(LIVING_BACKGROUNDS, seed)


def pick_behavior_beats(seed: int | None = None, *, count: int = 2) -> list[str]:
    """按 seed 取 `count` 条**互不相同**的行为节拍（ClipForge 的 `pickBehaviorBeats` 同法）。"""
    pool = list(BEHAVIOR_BEATS)
    start = (seed % len(pool)) if isinstance(seed, int) and not isinstance(seed, bool) and seed > 0 else 0
    return [pool[(start + offset) % len(pool)] for offset in range(min(count, len(pool)))]


# ---- S5 #9：opener 前置（相机身份短语放最前，token 权重最高）----
# 默认**关**（拍板：先 A/B）—— `build_motion_prompt(opener=...)` 才生效；没有配置项、没有隐式开关。
OPENER_HANDHELD = "以手持手机随手拍的日常视角"
OPENER_TRIPOD = "以固定机位的商业棚拍视角"


def build_motion_prompt(
    scene: ContentScene,
    *,
    intensity: str = DEFAULT_INTENSITY,
    product_visible: bool | None = None,
    chain_to_next: bool = False,
    seed: int | None = None,
    realism: str = DEFAULT_REALISM,
    look: object | None = None,
    person_shot: bool | None = None,
    opener: str | None = None,
) -> str:
    """四段式运动提示词；只描述运动，不重述场景与商品外观。

    `realism` 三档决定叠加多少"真实感层"，**`off` 档输出与本片实施前逐字一致**：

    | 档位 | 叠加什么 |
    |---|---|
    | `off` | 骨架：开场锚定 / 运镜 / 画面动态 / 商品保真 / 稳定收尾 / 链式 |
    | `constraints` | +【光线（Look 锁光，#10）】+【形态材质约束（#8）】 |
    | `auto` | +【物理反馈（#3）】【情绪三拍（#4）】【行为节拍（#5）】【活背景 + 布料头发惯性（#6）】【音效方向（#7）】 |
    """
    visible = _product_visible(scene) if product_visible is None else product_visible
    level = MOTION_INTENSITIES.get(intensity, MOTION_INTENSITIES[DEFAULT_INTENSITY])
    person = detect_person_shot(scene) if person_shot is None else person_shot
    tier = realism if realism in REALISM_TIERS else DEFAULT_REALISM

    sections: list[str] = []
    if opener:
        sections.append(opener)
    sections.append(OPENING_ANCHOR_CLAUSE)
    sections.append(f"运镜：{resolve_camera_phrase(scene)}（{level}）。")
    sections.append(f"画面动态：{_micro_action(scene, seed=seed)}。")

    if tier != REALISM_OFF:
        shape = resolve_shape_from_prompt(scene.prompt)
        look_prompt = str(getattr(look, "prompt", "") or "").strip()
        if look_prompt:
            # Look 的原文来自 `style_profiles`（不带句号），这里补一个，避免与下一段黏成一句
            sections.append(f"光线：{look_prompt.rstrip('。')}。")
        if shape is not None:
            sections.append(f"材质约束：{SHAPE_MATERIAL_CONSTRAINTS[shape]}。")
        if tier == REALISM_AUTO:
            if shape is not None and visible and _is_material_shot(scene):
                sections.append(f"物理反馈：{SHAPE_PHYSICAL_ACTIONS[shape]}。")
            if person:
                sections.append(f"{pick_emotion_line(seed)}。")
                sections.append(f"{'；'.join(pick_behavior_beats(seed))}。")
                sections.append(f"{FABRIC_HAIR_LAG}。")
            if person or visible:
                sections.append(f"{pick_living_background(seed)}。")

    if visible:
        sections.append(f"商品保真：{PRODUCT_FIDELITY_CLAUSE}")
    if tier == REALISM_AUTO:
        sections.append(SOUND_DIRECTION)
    sections.append(STABILITY_CLAUSE)
    if chain_to_next:
        sections.append(CHAIN_CLAUSE)
    return "".join(sections)


def keyframe_static_warning(scene: ContentScene) -> str | None:
    """S5 #11 的接入点：关键帧提示词含时序词时给人话告警（没命中返回 None）。

    ⚠️ 如实登记：**UI 展示属于 S4**（导演模式）；S5 只提供规则与这个可调用入口，
    调用方（生成侧日志 / 后续校验器）自行决定怎么用。
    """
    return static_warning(scene.prompt)


def build_motion_negative_prompt(scene: ContentScene, extra: str | None = None) -> str:
    terms = [*INTEGRATED_NEGATIVE_TERMS, "画面静止不动", "镜头抖动", "主体漂移"]
    if extra:
        cleaned = extra.strip()
        if cleaned:
            terms.append(cleaned)
    return ", ".join(terms)


# ---- 症状式单变量返修 ----
SYMPTOM_PATCHES: dict[str, str] = {
    "product_warped": "商品保持原样，标签与文字必须完全不变，不得重绘商品外形。",
    "text_blurry": "商品包装上的文字与 LOGO 必须保持锐利清晰，不出现涂抹或模糊。",
    "background_dead": "背景加入自然运动（光影流动、轻微空气感），但不要移动商品。",
    "light_wrong": "光线改为柔和自然光，避免硬边阴影与影棚感。",
    "blurry": "整体画面保持清晰锐利，不要出现拖影或运动模糊。",
    "object_drift": "所有物体位置保持稳定，不出现漂移、形变或闪动。",
}

SYMPTOM_LABELS: dict[str, str] = {
    "product_warped": "商品变形",
    "text_blurry": "文字模糊",
    "background_dead": "背景死板",
    "light_wrong": "光线不对",
    "blurry": "画面模糊",
    "object_drift": "物体漂移",
}


class UnknownSymptomError(ValueError):
    pass


def apply_symptom_patch(prompt: str, symptom: str) -> str:
    """把一条定向补丁追加到提示词末尾；未知症状直接报错，避免静默忽略。"""
    patch = SYMPTOM_PATCHES.get(symptom)
    if patch is None:
        raise UnknownSymptomError(f"未知症状：{symptom}")
    return f"{prompt}{patch}"


def _product_visible(scene: ContentScene) -> bool:
    mode = (scene.product_mode or "").strip()
    if mode in {"absent", "none"}:
        return False
    return bool(scene.overlay_product or mode)


def _micro_action_pool(scene: ContentScene) -> tuple[str, ...]:
    """镜头意图 → 微动作池。意图缺失时按 `purpose` 回查 BEATS 的 `visual_goal`。"""
    goal = (scene.visual_goal or "").strip()
    if goal in SUBJECT_MICRO_ACTIONS:
        return SUBJECT_MICRO_ACTIONS[goal]
    from onetake_api.modules.content_plan.generator import BEATS

    for beat in BEATS:
        if beat["purpose"] == scene.purpose:
            return SUBJECT_MICRO_ACTIONS.get(beat["visual_goal"], ())
    return ()


def _micro_action(scene: ContentScene, *, seed: int | None = None) -> str:
    """池里取一条：`seed=None`（或非正整数）取**首条**（= S7 之前的文案），否则 `seed % len(pool)`。"""
    pool = _micro_action_pool(scene)
    if not pool:
        return DEFAULT_MICRO_ACTION
    if isinstance(seed, int) and not isinstance(seed, bool) and seed > 0:
        return pool[seed % len(pool)]
    return pool[0]
