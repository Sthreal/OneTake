"""字幕样式预设（批次 1a）：四档，字号一律按**帧宽比例**给出。

口径来源：参考实现 ClipForge 的 `src/lib/caption-presets.ts`（四档同名 `standard` / `bold` /
`minimal` / `karaoke`，字号字段是 `fontSizeRatio`）。本文件只借用它的**相对几何**，文案与实现自己写。

⚠️ 本仓必须记牢的一个坑（本轮实测，别再踩）：
    本仓字幕走 libass（ffmpeg 的 `subtitles` 滤镜 + `force_style`），而 libass 把 `FontSize` 当
    **脚本像素**，会按 `frameH / PlayResY(288)` 放大到成片像素。实测 1080×1920 下 `FontSize=16`
    渲染出的字高是 **68px**（3.5% 帧高），不是 16px；即 1 个脚本单位 ≈ 6.67 成片像素。
    所以"字号 = 帧宽比例"在这里**不能**写成 `FontSize = ratio × width` —— 那会得到 54 单位，
    实测字高 229px、折成 4 行、占掉约半个屏幕。

    本文件的做法：以**本仓现有默认**（1080 宽 → 16 单位）为绝对锚点，四档只按 ClipForge 的
    **相对比例**（bold / standard / minimal = 0.062 / 0.05 / 0.042）缩放。好处是默认档**零可见变更**，
    而"字号随帧宽比例"这件事仍然成立（帧宽未知时回落 `LEGACY_FONT_SIZE`，即改造前的固定值）。

| 档位 | 定位 | 相对 standard | 描边（脚本单位） |
|---|---|---|---|
| `standard` | 通用易读（默认） | 1.0× | 2 |
| `bold` | 重击大字 | 1.24× | 4 |
| `minimal` | 纪实干净 | 0.84× | 1 |
| `karaoke` | 逐字高亮 | 1.0× | 2 |

**一处有意的偏差**：参考实现的 `standard` / `karaoke` 带半透明底板，而本仓默认观感是"白字 + 黑描边、
无底板"。加底板是**可见变更**，未经确认不做 —— 所以这里保持无底板（`BorderStyle=1`）。
"""
from __future__ import annotations

from dataclasses import dataclass

from onetake_api.platform.errors import DomainError

DEFAULT_CAPTION_STYLE = "standard"
# 帧宽未知时的字号：与改造前的固定值一致 → 不传 width 的老调用**逐字不变**
LEGACY_FONT_SIZE = 16
# 标定：REFERENCE_WIDTH 宽 → REFERENCE_FONT_SIZE 个 libass 脚本单位（即现有默认观感）
REFERENCE_WIDTH = 1080
REFERENCE_FONT_SIZE = 16
# 相对比例的分母：参考实现里 standard 的 fontSizeRatio
_REFERENCE_RATIO = 0.05


class CaptionStyleError(DomainError):
    """未知 / 非法字幕样式（配置或调用方传错）。不重试，交人工。"""

    code = "CAPTION_STYLE_INVALID"
    http_status = 400
    retryable = False


@dataclass(frozen=True)
class CaptionStyle:
    key: str
    size_scale: float       # 相对 standard 的字号倍率（来自参考实现的 fontSizeRatio / 0.05）
    outline: int            # 描边宽度（libass 脚本单位；1 单位 ≈ frameH/288 成片像素）
    karaoke: bool = False   # True → 走 ASS 逐字路径（批次 1c 已实现：subtitle_burner.build_karaoke_ass）


CAPTION_STYLES: dict[str, CaptionStyle] = {
    "standard": CaptionStyle("standard", 1.0, 2),
    "bold": CaptionStyle("bold", 0.062 / _REFERENCE_RATIO, 4),
    "minimal": CaptionStyle("minimal", 0.042 / _REFERENCE_RATIO, 1),
    "karaoke": CaptionStyle("karaoke", 1.0, 2, karaoke=True),
}
CAPTION_STYLE_KEYS: tuple[str, ...] = tuple(CAPTION_STYLES)

# 中文标签（**唯一真源**：前端下拉读 `GET /video/compose-options`，不在前端再写一份）
CAPTION_STYLE_LABELS: dict[str, str] = {
    "standard": "标准",
    "bold": "加粗",
    "minimal": "极简",
    "karaoke": "卡拉OK（逐字高亮）",
}


def resolve_caption_style(style: str | None) -> CaptionStyle:
    """样式名 → 预设。空值取默认档；未知样式**显式报错**（不静默回落，避免"选了没生效"）。"""
    key = (style or DEFAULT_CAPTION_STYLE).strip().lower()
    preset = CAPTION_STYLES.get(key)
    if preset is None:
        raise CaptionStyleError(f"未知字幕样式：{style or ''}（可选：{'、'.join(CAPTION_STYLE_KEYS)}）")
    return preset


def font_size_for(width: int | None, style: CaptionStyle) -> int:
    """按帧宽比例算字号（libass 脚本单位）。帧宽未知 / 非正 → 回落 `LEGACY_FONT_SIZE`。"""
    if not width or width <= 0:
        return LEGACY_FONT_SIZE
    return max(1, round(width * REFERENCE_FONT_SIZE / REFERENCE_WIDTH * style.size_scale))