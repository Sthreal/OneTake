"""按**商品形态**给的材质约束与物理反馈短语（S5 #3 / #8）。

**为什么按形态而不是品类**：本仓的商品输入是一张图 —— 「瓶子 / 穿戴 / 电子 / 小物」看一眼就能判，
「美妆 / 食品 / 家居」只能猜，猜错会毁掉整条脚本（见 `content_plan/product_shapes.py` 的拍板记录）。
ClipForge 用 `ProductCategory`（品类），我们用 `ProductShape`（形态）——**同一个意图，换了更可靠的键**。

**形态从哪来**：规则路径会把形态的 `visual_hint` 写进 `ContentScene.prompt`
（形如 `（商品形态：<visual_hint>）`）；本模块用**同一份 `PRODUCT_SHAPES` 反向匹配**取回形态键，
因此不会与生成侧漂移。取不到就**不加**（不猜）—— LLM 路径或无法识别形态的商品即属此类，
这是本层的已知边界，已登记。

两类内容的区别（沿用 ClipForge 的划分意图）：
- `SHAPE_MATERIAL_CONSTRAINTS`：**约束**（不许改变什么）—— 任何形态已知的商品镜都能加；
- `SHAPE_PHYSICAL_ACTIONS`：**动作**（可演出什么材质反馈）—— 只加在演示/商品镜上。
"""
from __future__ import annotations

from onetake_api.modules.content_plan.product_shapes import PRODUCT_SHAPES

SHAPE_MATERIAL_CONSTRAINTS: dict[str, str] = {
    "bottle_liquid": "瓶身与液面是画面的主体：液面有轻微的晃动与反光流动，瓶身形状、标签与印刷文字保持不变",
    "small_item": "小物件保持微距级细节：表面质感与边缘高光清晰自然，外形与印刷图案保持不变",
    "apparel": "布料有垂坠与自然褶皱的动态，材质纹理清晰，版型与图案保持不变",
    "electronics": "产品几何线条与指示灯细节保持稳定，屏幕与镜面有自然反光，外形与标识保持不变",
}

SHAPE_PHYSICAL_ACTIONS: dict[str, str] = {
    "bottle_liquid": "可有一滴液体沿瓶壁缓慢滑落、或液面轻微晃动，体现真实材质反馈",
    "small_item": "物件被轻微带动后有细微位移或一道光扫过表面，体现真实材质反馈",
    "apparel": "布料被轻微带动后有回弹与褶皱的自然变化，体现真实材质反馈",
    "electronics": "指示灯有缓慢的呼吸式变化、表面有细微反光移动，体现真实材质反馈",
}


def resolve_shape_from_prompt(prompt: str | None) -> str | None:
    """从场景提示词里取回商品形态键；取不到返回 `None`（**不猜**）。

    反向匹配用的是 `PRODUCT_SHAPES` 里的 `visual_hint` 原文 —— 与写入侧同源，因此不会漂移。
    """
    text = prompt or ""
    if not text:
        return None
    for key, shape in PRODUCT_SHAPES.items():
        if shape.visual_hint and shape.visual_hint in text:
            return key
    return None
