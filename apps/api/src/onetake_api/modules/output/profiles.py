"""导出档位（批次 6）：把"目标平台规格"和"处理策略"绑成一个 profile，端点只认 key。

**小红书 3:4 的二选一怎么定的**：方案里让我在"模糊背景留白"与"指定位置裁切"之间选一个。
这里没有硬选死：**默认 `blur_pad`（不丢任何画面）**，同时把 `center_crop` 做成可切换策略
（`EXPORT_XIAOHONGSHU_STRATEGY`）。理由：One Take 的成片是**商品 + 字幕 + AIGC 标识**三段信息都在画面里，
裁切会按画面内容随机丢东西（尤其字幕带与标识），而模糊留白零信息损失、观感也可控。
"""
from __future__ import annotations

from dataclasses import dataclass

from onetake_api.integrations.media.export import (
    STRATEGY_BLUR_PAD,
    STRATEGY_CENTER_CROP,
    STRATEGY_PASSTHROUGH,
)
from onetake_api.platform.errors import DomainError

DEFAULT_PROFILE = "douyin"
PROFILE_DOUYIN = "douyin"
PROFILE_XIAOHONGSHU = "xiaohongshu"


class ExportProfileError(DomainError):
    code = "EXPORT_PROFILE_INVALID"
    http_status = 400
    retryable = False


@dataclass(frozen=True)
class ExportProfile:
    key: str
    label: str
    width: int
    height: int
    strategy: str
    platforms: tuple[str, ...]
    note: str = ""


EXPORT_PROFILES: dict[str, ExportProfile] = {
    PROFILE_DOUYIN: ExportProfile(
        key=PROFILE_DOUYIN, label="抖音 / 视频号 / TikTok（9:16 竖版）",
        width=1080, height=1920, strategy=STRATEGY_PASSTHROUGH,
        platforms=("douyin", "wechat_channels", "tiktok"),
        note="与原片同规格，直接流拷贝（不重编码、零损失）",
    ),
    PROFILE_XIAOHONGSHU: ExportProfile(
        key=PROFILE_XIAOHONGSHU, label="小红书（3:4）",
        width=1080, height=1440, strategy=STRATEGY_BLUR_PAD,
        platforms=("xiaohongshu",),
        note="默认模糊背景留白（不丢画面）；可切 center_crop 居中裁切",
    ),
}
PROFILE_KEYS: tuple[str, ...] = tuple(EXPORT_PROFILES)


def list_export_profiles(*, settings) -> list[ExportProfile]:
    """列出档位，并把小红书那一档的策略换成配置里的当前值（前端展示与实际一致）。"""
    profiles: list[ExportProfile] = []
    for key, profile in EXPORT_PROFILES.items():
        if key == PROFILE_XIAOHONGSHU:
            profile = _with_strategy(profile, _xiaohongshu_strategy(settings))
        profiles.append(profile)
    return profiles


def resolve_export_profile(key: str | None, *, settings) -> ExportProfile:
    resolved_key = (key or "").strip().lower() or DEFAULT_PROFILE   # 空串/纯空白 → 默认档
    profile = EXPORT_PROFILES.get(resolved_key)
    if profile is None:
        raise ExportProfileError(f"未知导出档位：{key or ''}（可选：{'、'.join(PROFILE_KEYS)}）")
    if resolved_key == PROFILE_XIAOHONGSHU:
        profile = _with_strategy(profile, _xiaohongshu_strategy(settings))
    return profile


def _xiaohongshu_strategy(settings) -> str:
    strategy = str(getattr(settings, "export_xiaohongshu_strategy", STRATEGY_BLUR_PAD))
    if strategy not in {STRATEGY_BLUR_PAD, STRATEGY_CENTER_CROP}:
        raise ExportProfileError(f"未知小红书导出策略：{strategy}（可选：blur_pad、center_crop）")
    return strategy


def _with_strategy(profile: ExportProfile, strategy: str) -> ExportProfile:
    return ExportProfile(
        key=profile.key, label=profile.label, width=profile.width, height=profile.height,
        strategy=strategy, platforms=profile.platforms, note=profile.note,
    )