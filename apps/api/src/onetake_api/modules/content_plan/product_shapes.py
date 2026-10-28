"""商品形态模板（批次 2）：**按形态、不按品类**。

为什么按形态（拍板第 3 项）：One Take 的输入是**一张商品图**——「瓶子 / 穿戴 / 电子 / 小物」
看一眼就能判；而「美妆 / 食品 / 家居」这类**品类只能猜**，猜错会毁掉整条脚本。
所以形态决定画面与话术倾向；只有商品名/备注**明确可推断**品类时才额外叠加一句品类向的表达。

推断是**确定性关键词**匹配（零成本、可测），不认识就返回 `None`（不硬猜）。
"""
from __future__ import annotations

from dataclasses import dataclass

SHAPE_BOTTLE = "bottle_liquid"
SHAPE_SMALL_ITEM = "small_item"
SHAPE_APPAREL = "apparel"
SHAPE_ELECTRONICS = "electronics"


@dataclass(frozen=True)
class ProductShape:
    key: str
    label: str
    visual_hint: str        # 画面倾向（进场景 prompt）
    copy_hint: str          # 话术倾向（进场景 prompt，**不动用户文案**）


PRODUCT_SHAPES: dict[str, ProductShape] = {
    SHAPE_BOTTLE: ProductShape(
        SHAPE_BOTTLE, "瓶罐液体",
        "瓶身与液面是画面的主体，注意高光与液面反光，可用倾倒/倒出的动作暗示使用",
        "强调口感/质地/成分这类可感知的表达，避免空泛形容词",
    ),
    SHAPE_SMALL_ITEM: ProductShape(
        SHAPE_SMALL_ITEM, "单件小物",
        "小体积物件要紧靠镜头，用微距般的贴近展示细节与工艺",
        "强调细节、便携与随身带的使用感",
    ),
    SHAPE_APPAREL: ProductShape(
        SHAPE_APPAREL, "服饰穿戴",
        "需要有被穿上/被使用的空间关系（衣架、台面、镜头高度），体现材质垂坠与褶皱",
        "强调版型、材质与上身后的状态；不承诺身材/效果",
    ),
    SHAPE_ELECTRONICS: ProductShape(
        SHAPE_ELECTRONICS, "电子产品",
        "以正面/侧面的几何线条与指示灯细节为主，避免杂乱线缆",
        "强调交互动作（拿取、连接、亮起）与使用场景，不写性能参数",
    ),
}

_SHAPE_KEYWORDS: dict[str, tuple[str, ...]] = {
    SHAPE_BOTTLE: ("水", "汁", "奶", "油", "酒", "饮", "喷雾", "精华", "乳液", "洗发", "沐浴", "瓶", "罐"),
    SHAPE_APPAREL: ("衣", "裤", "裙", "袜", "鞋", "帽", "围巾", "内衣", "外套", "卫衣", "睡衣"),
    SHAPE_ELECTRONICS: ("耳机", "充电", "键盘", "鼠标", "音箱", "相机", "手表", "手机", "电脑", "数据线", "电源"),
    SHAPE_SMALL_ITEM: ("口红", "唇", "粉饼", "眼影", "香水", "手串", "项链", "戒指", "耳饰", "笔", "杯子", "杯"),
}


def infer_product_shape(*texts: str | None) -> str | None:
    """从商品名/备注里推断形态；判不出来返回 `None`（宁可不给倾向，也不硬猜）。"""
    haystack = " ".join(item for item in texts if item)
    if not haystack.strip():
        return None
    for shape, keywords in _SHAPE_KEYWORDS.items():
        if any(keyword in haystack for keyword in keywords):
            return shape
    return None


def shape_hint(shape: str | None) -> tuple[str, str]:
    """返回 (画面倾向, 话术倾向)；形态未知时给空串（不编）。"""
    if not shape or shape not in PRODUCT_SHAPES:
        return "", ""
    item = PRODUCT_SHAPES[shape]
    return item.visual_hint, item.copy_hint