"""平台规则检查（Phase 5）：抖音 2026-07 AI 电商内容规则。

三条被编码的规则：
1. **AI 生成的对比/测评类内容被平台禁止** —— 我们的"对比测评 / 开箱测评"风格正踩这条线
2. **数字人禁五类目**：医疗、金融、美容功效、保健品功效、教育培训效果
3. **AI 角色不得声称个人使用体验**（"亲测有效"属于伪造使用结果红线）

风格与类目判断全部来自用户已确认的输入，不做猜测；命中即 warn，由交付门决定是否阻断。

**口径变更（2026-10-14，档案 M4-04）—— 两条规则不再被 `has_ai_person` 门控**

原先规则 2 与规则 3 被一个 `has_ai_person` 参数门控（只有 avatar 档位才会检查）。avatar
档位下线后，系统**确实无法知道**画面里有没有人（「有人与否」交给 Prompt 表达），但这两条
规则的价值与"当前是哪个档位"无关，所以拆开各自独立判定：

- `personal_testimony` 是**纯文案规则**（文案出现"亲测/自用/实测…"即命中），去掉条件**恒判定**
  —— 比原来更严格，也更准确（不再用"画面有人"这个与文案无关的理由去门控它）。
- `digital_human_category` 确实依赖"画面有人"，在系统无法判定时**保守放行到人工确认**：
  去掉条件恒判定，并把 warn 文案改为「…若本片不含人物，请确认后放行」，**让 warn 本身成为
  人工确认入口**（与 `gate.py`「抽帧拼图是人看一眼再交付的唯一入口」同一思路）。

**为什么不能一刀切为恒 False**：这两条 warn 都会**阻断下载直到被 ack**（见 `gate.py`），
恒 False 等于把两条平台合规检查静默关掉且无人察觉。
"""
from __future__ import annotations

from onetake_api.modules.compliance.domain import PlatformWarning

AI_REVIEW_STYLES = {"comparison", "unboxing", "对比测评", "开箱测评"}

DIGITAL_HUMAN_BANNED_CATEGORIES: dict[str, tuple[str, ...]] = {
    "医疗": ("医疗", "治疗", "处方", "药", "械"),
    "金融": ("金融", "理财", "贷款", "保险", "投资"),
    "美容功效": ("祛斑", "美白", "抗皱", "紧致", "丰胸"),
    "保健品功效": ("保健", "增强免疫", "降三高", "壮阳"),
    "教育培训效果": ("提分", "包过", "保offer", "保录取"),
}

PERSONAL_TESTIMONY_MARKERS = ("亲测", "自用", "实测", "我用过", "我买过", "我一直在用")


def evaluate(
    *,
    style: str | None,
    product_text: str,
    copy_text: str,
) -> list[PlatformWarning]:
    """跑三条平台规则。**签名里没有 `has_ai_person`** —— 见模块说明的口径变更。"""
    warnings: list[PlatformWarning] = []
    normalized_style = (style or "").strip()
    if normalized_style in AI_REVIEW_STYLES:
        warnings.append(PlatformWarning(
            id="ai_review_style",
            message="该风格属于 AI 生成的对比/测评内容，抖音明确禁止，存在下架风险",
        ))

    # 规则 2：数字人禁五类目 —— 恒判定（文案里命中类目关键词即提示，由人确认后放行）
    haystack = product_text or ""
    for category, keywords in DIGITAL_HUMAN_BANNED_CATEGORIES.items():
        if any(keyword in haystack for keyword in keywords):
            warnings.append(PlatformWarning(
                id="digital_human_category",
                message=f"「{category}」类目禁止使用 AI 人物。若本片不含人物，请确认后放行",
            ))
            break

    # 规则 3：个人使用体验声称 —— 恒判定的纯文案规则
    if any(marker in (copy_text or "") for marker in PERSONAL_TESTIMONY_MARKERS):
        warnings.append(PlatformWarning(
            id="personal_testimony",
            message="AI 角色声称个人使用体验（如「亲测有效」）属于伪造使用结果，请改为推荐式表述",
        ))
    return warnings