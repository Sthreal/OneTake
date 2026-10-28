"""批次 6 单测：导出档位 + 真实转码（模糊留白 / 居中裁切 / 流拷贝）+ 实测报告。

转码用真 ffmpeg（不联网、不花钱）：造一段 9:16 带音轨的源片，导成 3:4 看结果。
"""
from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path

import pytest
from PIL import Image
from imageio_ffmpeg import get_ffmpeg_exe

from onetake_api.config import Settings
from onetake_api.integrations.media import export as export_media
from onetake_api.integrations.media.export import ExportError
from onetake_api.integrations.media.video_utils import inspect_video_dimensions, inspect_video_duration
from onetake_api.modules.output.profiles import (
    PROFILE_DOUYIN,
    PROFILE_XIAOHONGSHU,
    ExportProfileError,
    list_export_profiles,
    resolve_export_profile,
)

SOURCE_WIDTH, SOURCE_HEIGHT, SOURCE_SECONDS = 360, 640, 2.0


def _settings(**overrides) -> Settings:
    base = {"mock_providers": False}
    base.update(overrides)
    return Settings(**base)


def _source_video(*, width: int = SOURCE_WIDTH, height: int = SOURCE_HEIGHT, seconds: float = SOURCE_SECONDS) -> bytes:
    with tempfile.TemporaryDirectory() as temp_dir:
        output = Path(temp_dir) / "source.mp4"
        subprocess.run(
            [get_ffmpeg_exe(), "-y",
             "-f", "lavfi", "-i", f"testsrc=size={width}x{height}:rate=24:duration={seconds}",
             "-f", "lavfi", "-i", f"sine=frequency=440:duration={seconds}",
             "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(output)],
            check=True, capture_output=True,
        )
        return output.read_bytes()


# ---- 档位表 ----


def test_profiles_bind_platform_specs_and_strategy() -> None:
    profiles = {profile.key: profile for profile in list_export_profiles(settings=_settings())}
    douyin = profiles[PROFILE_DOUYIN]
    assert (douyin.width, douyin.height, douyin.strategy) == (1080, 1920, "passthrough")
    assert set(douyin.platforms) == {"douyin", "wechat_channels", "tiktok"}
    xiaohongshu = profiles[PROFILE_XIAOHONGSHU]
    assert (xiaohongshu.width, xiaohongshu.height) == (1080, 1440)
    # 默认模糊留白（不丢画面）；可切居中裁切
    assert xiaohongshu.strategy == "blur_pad"
    switched = resolve_export_profile(PROFILE_XIAOHONGSHU, settings=_settings(export_xiaohongshu_strategy="center_crop"))
    assert switched.strategy == "center_crop"


def test_unknown_profile_is_explicit() -> None:
    with pytest.raises(ExportProfileError) as error:
        resolve_export_profile("bilibili", settings=_settings())
    assert error.value.http_status == 400 and error.value.retryable is False


def test_empty_profile_falls_back_to_default() -> None:
    assert resolve_export_profile(None, settings=_settings()).key == PROFILE_DOUYIN
    assert resolve_export_profile("  ", settings=_settings()).key == PROFILE_DOUYIN


def test_bad_xiaohongshu_strategy_is_explicit() -> None:
    """Settings 的 Literal 已经挡了一层；这里验证**绕过校验**时的兜底检查也拦得住。"""
    from types import SimpleNamespace

    with pytest.raises(ExportProfileError) as error:
        resolve_export_profile(PROFILE_XIAOHONGSHU, settings=SimpleNamespace(export_xiaohongshu_strategy="stretch"))
    assert "blur_pad" in str(error.value)


# ---- 滤镜串（纯函数）----


def test_reframe_filter_shape() -> None:
    blur = export_media.build_reframe_filter(strategy="blur_pad", width=1080, height=1440, fps=30)
    assert "gblur=sigma=" in blur and "overlay=(W-w)/2:(H-h)/2" in blur and blur.endswith(",fps=30,setsar=1[out]")
    crop = export_media.build_reframe_filter(strategy="center_crop", width=1080, height=1440, fps=30)
    assert "force_original_aspect_ratio=increase,crop=1080:1440,fps=30" in crop
    still = export_media.build_reframe_filter(strategy="blur_pad", width=1080, height=1440, fps=None)
    assert "fps=" not in still                                        # 单帧路径不插 fps
    with pytest.raises(ExportError):
        export_media.build_reframe_filter(strategy="stretch", width=1, height=1, fps=30)


# ---- 真转码 ----


def test_blur_pad_export_keeps_whole_frame_and_audio() -> None:
    source = _source_video()
    exported = export_media.export_video(
        source_bytes=source, strategy="blur_pad", width=1080, height=1440, fps=30,
    )
    assert inspect_video_dimensions(exported) == (1080, 1440)
    assert abs(inspect_video_duration(exported) - SOURCE_SECONDS) <= 0.2
    measured = export_media.measure(exported)
    assert measured.has_audio is True                                 # 原声音轨被保留（多平台导出不改声音）
    assert measured.width == 1080 and measured.height == 1440
    assert measured.bitrate_kbps > 0


def test_center_crop_export_changes_frame_size() -> None:
    source = _source_video()
    exported = export_media.export_video(
        source_bytes=source, strategy="center_crop", width=1080, height=1440, fps=30,
    )
    assert inspect_video_dimensions(exported) == (1080, 1440)
    assert export_media.measure(exported).bitrate_kbps > 0


def test_passthrough_export_avoids_reencode() -> None:
    source = _source_video(width=1080, height=1920)
    exported = export_media.export_video(
        source_bytes=source, strategy="passthrough", width=1080, height=1920, fps=24,
    )
    assert inspect_video_dimensions(exported) == (1080, 1920)
    # 流拷贝：视频流字节（md5 近似用长度+尺寸判定）应基本一致；这里断言"没有变大很多"
    assert len(exported) <= len(source) * 1.2


def test_passthrough_scales_when_source_spec_differs() -> None:
    """原片不是目标规格时，"原样"策略退化成等比缩放 + 黑边（**不裁不拉**），不是原样输出小尺寸。"""
    source = _source_video(width=360, height=640)
    exported = export_media.export_video(
        source_bytes=source, strategy="passthrough", width=1080, height=1920, fps=30,
    )
    assert inspect_video_dimensions(exported) == (1080, 1920)


def test_export_frame_produces_cover_at_profile_size() -> None:
    source = _source_video()
    cover = export_media.export_frame(
        source_bytes=source, at_seconds=1.0, strategy="blur_pad", width=1080, height=1440,
    )
    with Image.open(__import__("io").BytesIO(cover)) as image:
        assert image.size == (1080, 1440)                             # 封面 = 目标画幅的构图预览
        assert image.format == "PNG"


def test_export_frame_passthrough_keeps_source_size() -> None:
    source = _source_video()
    cover = export_media.export_frame(
        source_bytes=source, at_seconds=0.5, strategy="passthrough", width=1080, height=1920,
    )
    with Image.open(__import__("io").BytesIO(cover)) as image:
        assert image.size == (SOURCE_WIDTH, SOURCE_HEIGHT)            # 原样抽帧（不缩放，零损失）