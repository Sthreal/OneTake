"""多视角母版生成（**一张整图出 2×2 四格**）—— 本仓的唯一实现。

为什么要有这个模块（2026-10-15 抽出）：同一套机制有两个消费者，禁止第二处实现：
1. 商品关键帧九宫格：`keyframe_integrated.KeyframeGenerator.generate_grid_image`
2. 出镜人四视角母版：`modules/character`（付费把真人照片升级成四视角身份锚点，一次入库、跨项目复用）

边界：本模块**只负责"一次调用 → 一张整图"**；提示词、尺寸、错误类型由调用方传入
（两边的提示词与错误码本来就不同，硬合并会互相污染）。
"""
from __future__ import annotations

from typing import Callable

from onetake_api.integrations.media.image_utils import pad_image_to_9_16
from onetake_api.platform.errors import DomainError

ROWS = 2
COLS = 2

# 出镜人四视角母版提示词：身份一致性优先，明确"同一个人"，并禁止文字/水印（避免模型在脸上加东西）
FOUR_VIEW_SUBJECT_HINT = (
    "四视角人物设定图（2×2 网格，白缝分隔，四格分辨率一致）："
    "左上=正面、右上=四分之三侧面、左下=侧面、右下=背面；"
    "四格必须是**同一个人**，发型、脸型、肤色、体型、服装配色全部一致；"
)


class MultiViewGenerationError(DomainError):
    code = "MULTI_VIEW_GENERATION_FAILED"
    http_status = 502
    retryable = True


def build_four_view_prompt(*, name: str, appearance: str) -> str:
    """出镜人四视角母版提示词（真人照片→四视角时，照片是**图 1**）。"""
    detail = (appearance or "").strip() or "以图 1 中人物的外貌为准"
    return (
        f"图 1 是出镜人「{name}」的参考照片。{FOUR_VIEW_SUBJECT_HINT}"
        f"人物外貌锚点：{detail}。"
        "保持人物真实自然、日常实拍质感、均匀柔光、纯净浅灰背景；"
        "不要改变人物的身份特征，不要美颜到失真。"
    )


def generate_multi_view_sheet(
    *,
    adapter,
    images: list[tuple[bytes, str]],
    prompt: str,
    negative_prompt: str,
    size: str,
    seed: int | None = None,
    error_cls: Callable[..., DomainError] = MultiViewGenerationError,
    failure_message: str = "多视角母版生成失败",
    empty_message: str = "多视角母版生成返回空结果",
) -> bytes:
    """调**一次**模型，出**一张** 2×2 整图（已归一化成 9:16）。

    - 只调一次 = 省调用的唯一来源；
    - `error_cls`：调用方各自的领域错误类型（关键帧用 KeyframeGenerationError、出镜人用 MultiViewGenerationError），
      这样两边的错误码与前端文案都不变。
    """
    if not images:
        raise error_cls("多视角母版生成缺少参考图")
    try:
        results = adapter.generate(
            images=images,
            prompt=prompt,
            negative_prompt=negative_prompt,
            n=1,
            seed=seed,
            size=size,
        )
    except DomainError:
        raise
    except Exception as exc:  # noqa: BLE001 - 统一转成调用方的领域错误
        raise error_cls(failure_message) from exc
    if not results:
        raise error_cls(empty_message)
    return pad_image_to_9_16(results[0])
