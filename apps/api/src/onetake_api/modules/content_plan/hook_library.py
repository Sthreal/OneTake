"""钩子库（批次 2）：把「开场怎么写」从一条写死文案升级为**可选的结构化钩子**。

数据结构照参考实现的 schema：`stop`（0-1 秒停拇指）/ `prove`（1-3 秒与我有关）/
`bridge`（3-7 秒桥接产品）+ `arousal`(high|mid) + `shapes?`（适用商品形态）+ `avoidWhen?` + `example`。

**一处刻意的口径差异（必须读懂再用）**：参考实现的钩子是**文案**钩子；One Take 的规则路径**不改写用户文案**
（文案来自用户已确认的字幕/TTS），所以这里的钩子落在**画面指令**上：三段分别对应
「开场用什么画面抓注意力 / 用什么空间让观众觉得与我有关 / 用什么动作把产品带出来」，
并顺带给出该场景的**英文检索词**（供免 Key 素材用）。文案层的钩子仍由脚本层负责（`qwen_vl_script` 的 `hook` 字段）。

`avoid_when` 不是装饰：它是**给人看的说明**（同时也是 `pick_hook` 的排除依据，由调用方显式传入 `exclude_ids`）。
"""
from __future__ import annotations

from dataclasses import dataclass, field

AROUSAL_HIGH = "high"
AROUSAL_MID = "mid"


@dataclass(frozen=True)
class HookPattern:
    hook_id: str
    stop: str
    prove: str
    bridge: str
    arousal: str
    stock_query: str
    example: str
    shapes: tuple[str, ...] = ()
    avoid_when: tuple[str, ...] = field(default_factory=tuple)

    @property
    def instruction(self) -> str:
        """三段结构合成一句画面指令（进 `subject_action`）。"""
        return f"{self.stop}；{self.prove}；{self.bridge}"


HOOK_PATTERNS: tuple[HookPattern, ...] = (
    HookPattern(
        hook_id="h1_desk_fatigue",
        stop="开场 0-1 秒用冷色近景压住节奏：桌面上散着上一轮的残留物，镜头几乎贴着桌面",
        prove="1-3 秒把镜头拉开到日常空间（办公桌/通勤/睡前），让观众认出这就是自己每天的场景",
        bridge="3-7 秒给一个动作因果的暗示：人伸手或视线移向画面外的下一步动作",
        arousal=AROUSAL_HIGH,
        stock_query="morning desk workspace light",
        example="纸杯被推到桌角，镜头缓慢推近",
        avoid_when=("没有任何日常场景可借",),
    ),
    HookPattern(
        hook_id="h2_sudden_detail",
        stop="开场 0-1 秒用极近的材质特写加轻微手抖感，制造停下来看一眼的冲动",
        prove="1-3 秒退到中景，露出使用者的手与桌面的空间关系",
        bridge="3-7 秒让主体在画面里被拿起或旋开这一动作带出",
        arousal=AROUSAL_HIGH,
        stock_query="close up hands morning table",
        example="指尖掠过台面，光线扫过材质",
    ),
    HookPattern(
        hook_id="h3_scene_promise",
        stop="开场 0-1 秒先给结果场景：光线通透的窗边台面，氛围先到位",
        prove="1-3 秒保持同一空间，加入自然的轻微运动（树叶、窗帘、蒸汽）",
        bridge="3-7 秒用一个固定的展示位，让主体有清晰的出场位置",
        arousal=AROUSAL_MID,
        stock_query="sunlit window table morning",
        example="窗边光斑缓慢移动",
    ),
    HookPattern(
        hook_id="h4_before_after_space",
        stop="开场 0-1 秒用改变前后的空间对比：凌乱的一侧先入画",
        prove="1-3 秒镜头横移到整齐的一侧，让观众自己看出差别",
        bridge="3-7 秒把整齐那一侧的展示位留出来给主体",
        arousal=AROUSAL_MID,
        stock_query="tidy desk organizer detail",
        example="镜头从左到右扫过两种桌面状态",
        avoid_when=("同一条片子里已经用过强对比的手法",),
    ),
    HookPattern(
        hook_id="h5_outdoor_light",
        stop="开场 0-1 秒用户外自然光的逆光轮廓抓住眼球",
        prove="1-3 秒跟拍一小段行走或停留，让场景动起来",
        bridge="3-7 秒停在某个自然展示点（石台/木桌），主体随后出场",
        arousal=AROUSAL_MID,
        stock_query="outdoor walking morning light",
        example="逆光下的树叶与脚步",
        shapes=("apparel", "electronics"),
    ),
    HookPattern(
        hook_id="h6_clean_studio",
        stop="开场 0-1 秒用干净的浅色影棚背景加一件孤立的主体剪影",
        prove="1-3 秒灯光渐亮，把空间关系交代清楚",
        bridge="3-7 秒让展示台显形，为主体留出固定机位",
        arousal=AROUSAL_MID,
        stock_query="studio soft light background",
        example="灯光由暗到亮的极简台面",
    ),
)
HOOK_IDS: tuple[str, ...] = tuple(pattern.hook_id for pattern in HOOK_PATTERNS)
# 强节奏风格偏 high 唤起，克制风格偏 mid
_STYLE_AROUSAL = {
    "trend": AROUSAL_HIGH,
    "pain_point": AROUSAL_HIGH,
    "product_pov": AROUSAL_HIGH,
    "clean": AROUSAL_MID,
    "story": AROUSAL_MID,
    "scene": AROUSAL_MID,
}
# 从「钩子名」到给人看的写法：种子固定 → 结果固定（同一条片子可复现）
def pick_hook(
    *, style: str, shape: str | None = None, seed: int | None = None, exclude_ids: tuple[str, ...] = ()
) -> HookPattern:
    """按「风格唤起 → 形态适用 → seed 稳定取模」挑一条钩子；全都不可用则退到第一条。

    形态不匹配的条目在给了 `shape` 时优先排除，但**不会排除到空**（保证任何情况下都有钩子可选）；
    `avoid_when` 的排除由调用方通过 `exclude_ids` 显式传入（这里不做语义猜测）。
    """

    def _usable(pattern: HookPattern) -> bool:
        return pattern.hook_id not in exclude_ids

    preferred = _STYLE_AROUSAL.get(style, AROUSAL_MID)
    candidates = [item for item in HOOK_PATTERNS if _usable(item) and item.arousal == preferred]
    if shape:
        matched = [item for item in candidates if item.shapes and shape in item.shapes]
        if matched:
            candidates = matched
        else:
            candidates = [item for item in candidates if not item.shapes] or candidates
    if not candidates:
        candidates = [item for item in HOOK_PATTERNS if _usable(item)] or list(HOOK_PATTERNS)
    index = 0 if seed is None else seed % len(candidates)
    return candidates[index]