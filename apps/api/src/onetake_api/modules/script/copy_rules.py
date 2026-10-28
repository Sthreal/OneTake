"""口播文案硬规则（切片 A）：禁套话开场、前 3 秒钩子、双 CTA。

这些规则在 `normalize_generated` 里执行，失败抛 `ScriptCopyRuleError`
（code 仍是 `SCRIPT_GENERATION_ERROR`，自动链可以重试生成）。
审稿闸门（切片 C）不在这里：本模块只提供可测的校验，以及生成/审稿 prompt 共用的契约句。

双 CTA 按已拍板的 P4A：不放宽 45–72 字，`usage_scenario` 末尾轻提，`cta` 做末句行动号召。
画面钩子仍由 `hook_library` 负责，这里不改写用户口播。
"""
from __future__ import annotations

from dataclasses import dataclass

# 生成与审稿 prompt 共用，避免两处口径漂移。
COPY_RULE_PROMPT = (
    "hook 禁止以套话开场（例如「大家好」「今天给大家介绍」「各位观众」「亲爱的朋友们」「欢迎来到」）。"
    "前 3 秒钩子必须能停住拇指：hook 去掉标点至少 8 个字，并且带疑问或冲突"
    "（问号或叹号，或「还在」「为什么」「别再」「难道」「竟然」这类词）。"
    "双 CTA 必须放进全文 45–72 字里：usage_scenario 用很轻的一句收在末尾（例如「顺手看看」），"
    "cta 单独做明确的行动号召（例如看看、链接、下单、带走），不要再写一整段广告。"
)

# 只匹配开场，不惩罚后文里偶然出现的「大家好」。长的放前面，由匹配函数再按长度排序。
OPENING_CLICHES: tuple[str, ...] = (
    "今天来给大家介绍",
    "今天给大家介绍",
    "给大家介绍一下",
    "首先感谢大家",
    "各位朋友大家好",
    "哈喽大家好",
    "亲爱的朋友们",
    "今天来给大家",
    "今天给大家",
    "给大家介绍",
    "各位小伙伴",
    "小伙伴们好",
    "各位观众",
    "各位朋友",
    "欢迎收看",
    "欢迎来到",
    "首先感谢",
    "我是你们的",
    "大家好",
    "各位好",
)

MIN_HOOK_SPOKEN_CHARS = 8

# 单字「别」「停」会误伤「特别」「不停」，所以只用完整的疑问/冲突片段。
HOOK_THUMBSTOP_MARKERS: tuple[str, ...] = (
    "？",
    "?",
    "！",
    "!",
    "还在",
    "为什么",
    "为何",
    "凭什么",
    "别再",
    "竟然",
    "居然",
    "难道",
    "千万别",
    "先别",
    "错在",
    "你以为",
    "谁懂",
    "怎么会",
    "怎么还",
)

# 末句行动号召：子串匹配。不用单字「买」，避免「购买力」这类误伤。
CTA_ACTION_MARKERS: tuple[str, ...] = (
    "看看",
    "了解",
    "下单",
    "点击",
    "带走",
    "入手",
    "去看",
    "现在就",
    "来试",
    "试试",
    "点这里",
    "点下方",
    "小黄车",
    "链接",
    "搜索",
    "搜一下",
    "关注",
    "收藏",
    "拍下",
    "选它",
    "买它",
    "去拍",
    "来拿",
)

# 场景句末尾的轻提。匹配时按长度优先，让「顺手看看」不会被收成「看看」。
LIGHT_CTA_TAILS: tuple[str, ...] = (
    "顺手看看",
    "去看看",
    "看一下",
    "了解一下",
    "留意一下",
    "记得看",
    "搜一下",
    "值得试",
    "可以试",
    "看看",
    "留意",
    "带上",
)

_LEADING_NOISE = " \t\r\n\"'“”‘’「」『』【】[]()（）:：,，.。!！?？、~～—"


@dataclass(frozen=True)
class CopyRuleViolation:
    rule: str
    dimension: str
    message: str


def _copy_rule_error(message: str, *, rule: str, dimension: str):
    """继承 `ScriptGenerationError`，但类只建一次。

    不能在模块顶层导入 content：content 在校验时才导入本模块，顶层互引会成环。
    code 保持 `SCRIPT_GENERATION_ERROR`，生成失败仍按既有策略重试。
    """
    cached = getattr(_copy_rule_error, "_cls", None)
    if cached is None:
        from onetake_api.modules.script.content import ScriptGenerationError

        class ScriptCopyRuleError(ScriptGenerationError):
            def __init__(self, message: str, *, rule: str, dimension: str) -> None:
                super().__init__(message)
                self.rule = rule
                self.dimension = dimension

        cached = ScriptCopyRuleError
        _copy_rule_error._cls = cached
    return cached(message, rule=rule, dimension=dimension)


def opening_text(hook: str) -> str:
    return (hook or "").strip().lstrip(_LEADING_NOISE).strip()


def matched_opening_cliche(hook: str) -> str | None:
    text = opening_text(hook)
    for phrase in sorted(OPENING_CLICHES, key=len, reverse=True):
        if text.startswith(phrase):
            return phrase
    return None


def _spoken_len(text: str) -> int:
    from onetake_api.modules.script.content import spoken_character_count

    return spoken_character_count(text)


def _strip_trailing_punct(text: str) -> str:
    return (text or "").strip().rstrip(_LEADING_NOISE).strip()


def light_cta_tail(usage_scenario: str) -> str | None:
    spoken = _strip_trailing_punct(usage_scenario)
    for tail in sorted(LIGHT_CTA_TAILS, key=len, reverse=True):
        if spoken.endswith(tail):
            return tail
    return None


def cta_action_marker(cta: str) -> str | None:
    text = cta or ""
    for marker in sorted(CTA_ACTION_MARKERS, key=len, reverse=True):
        if marker in text:
            return marker
    return None


def find_copy_violations(*, hook: str, usage_scenario: str, cta: str) -> list[CopyRuleViolation]:
    """按固定顺序收集违规：套话 → 钩子停拇指 → 场景轻提 → 末句 CTA。"""
    violations: list[CopyRuleViolation] = []
    cliche = matched_opening_cliche(hook)
    if cliche:
        violations.append(CopyRuleViolation(
            rule="opening_cliche",
            dimension="freshness",
            message=f"hook 以套话「{cliche}」开场",
        ))

    spoken = _spoken_len(hook)
    marker = next((item for item in HOOK_THUMBSTOP_MARKERS if item in (hook or "")), None)
    if spoken < MIN_HOOK_SPOKEN_CHARS or marker is None:
        reasons: list[str] = []
        if spoken < MIN_HOOK_SPOKEN_CHARS:
            reasons.append(f"去掉标点只有 {spoken} 字，至少需要 {MIN_HOOK_SPOKEN_CHARS} 字")
        if marker is None:
            reasons.append("缺少疑问或冲突（问号/叹号，或「还在」「为什么」「别再」「难道」）")
        violations.append(CopyRuleViolation(
            rule="hook_thumbstop",
            dimension="structure",
            message="前 3 秒钩子停不住拇指：" + "；".join(reasons),
        ))

    if light_cta_tail(usage_scenario) is None:
        violations.append(CopyRuleViolation(
            rule="dual_cta_usage",
            dimension="structure",
            message="usage_scenario 末尾需要轻提行动（如「顺手看看」），并且全文仍须落在 45–72 字",
        ))
    if cta_action_marker(cta) is None:
        violations.append(CopyRuleViolation(
            rule="dual_cta_closing",
            dimension="structure",
            message="cta 必须是明确的行动号召（如看看、链接、下单、带走），作为口播末句",
        ))
    return violations


def enforce_copy_rules(*, hook: str, usage_scenario: str, cta: str) -> None:
    violations = find_copy_violations(hook=hook, usage_scenario=usage_scenario, cta=cta)
    if not violations:
        return
    summary = "；".join(f"[{item.rule}/{item.dimension}] {item.message}" for item in violations)
    first = violations[0]
    raise _copy_rule_error(summary, rule=first.rule, dimension=first.dimension)
