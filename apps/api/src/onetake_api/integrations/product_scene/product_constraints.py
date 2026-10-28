"""商品保真约束的单一真源（Phase 1）。

关键帧生成 prompt、VLM 校验清单、症状返修补丁三处共用本模块的文案与术语，
避免"三处各写一份约束"导致的漂移（总体方案 §5.1）。

术语约定：
- 「保真约束」= 要求模型必须做到的事（正向）
- 「禁止项」= 要求模型不能出现的事（负向 / negative_prompt）
"""
from __future__ import annotations

# ---- 正向保真约束（integrated 路径：商品必须进画面）----
FIDELITY_RULES: tuple[str, ...] = (
    "商品外观、结构、配色必须与参考图完全一致",
    "包装上的文字、LOGO、图案必须清晰可辨且不得改动",
    "不得重绘商品、不得变形、不得增删部件、不得改变材质",
    "商品必须在画面中清晰可见，不被遮挡、不被裁切",
)

# ---- 反向禁止项（negative_prompt）----
INTEGRATED_NEGATIVE_TERMS: tuple[str, ...] = (
    "商品变形",
    "包装文字模糊",
    "标签文字错误",
    "LOGO 错误",
    "多余的同类商品",
    "重复主体",
    "乱码文字",
    "水印",
    "人物",
    "手部",
    "卡通",
    "插画",
    "低质量",
    "画面闪烁",
)

# ---- 场景描述中不允许出现的"主体/道具"词（防止场景抢占商品位）----
# 说明：沿用产品既有的屏蔽词口径，保证 erase 路径与 integrated 路径判定一致。
FORBIDDEN_SUBJECT_TERMS: tuple[str, ...] = (
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
    "道具",
    "植物",
)


def fidelity_block() -> str:
    """拼成一段可直接放进 prompt 的保真约束文本。"""
    return "；".join(FIDELITY_RULES) + "。"


def integrated_negative_prompt(extra: str | None = None) -> str:
    terms = list(INTEGRATED_NEGATIVE_TERMS)
    if extra:
        cleaned = extra.strip()
        if cleaned:
            terms.append(cleaned)
    return ", ".join(terms)


def scene_prompt_is_safe(prompt: str) -> bool:
    """场景描述里若出现主体/道具类词，视为会与商品抢位，判为不可用。"""
    lowered = (prompt or "").lower()
    return not any(term in lowered for term in FORBIDDEN_SUBJECT_TERMS)


# ---- QA 校验清单（keyframe_qa 与前端展示共用同一套 id/文案）----
QA_CHECK_LABELS: dict[str, str] = {
    "product_present": "商品已入画",
    "product_fidelity": "商品与主图一致",
    "text_intact": "包装文字未变形",
    "no_extra_subject": "无多余商品或主体",
    "no_garbled_text": "无乱码文字或水印",
}