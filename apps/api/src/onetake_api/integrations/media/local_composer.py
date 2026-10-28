"""本地 FFmpeg 合成器（Phase 4）。

替代 Shotstack 的按次付费云合成，落地总体方案 §8 的处理顺序（顺序是硬约束）：

    商品图层兜底 → 混音(loudnorm I=-14) → 字幕烧录 → native-feel → AIGC 标识（最后）

为什么顺序不能变：
- 字幕要在 native-feel 之前（走位抖动会撕字幕边缘）
- AIGC 标识必须在最后（手抖的 crop 会把它裁掉一块）

设计取舍：
- 混音步骤用 `-c:v copy` 只换音轨，避免无谓的重复编码
- 只有确实需要的步骤才重新编码视频（字幕 / 去 AI 味 / 标识）
- 每一步都检查输出非空；任一步失败即抛领域错误，不产出"半成品当成品"
"""
from __future__ import annotations

import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from imageio_ffmpeg import get_ffmpeg_exe

from onetake_api.config import Settings, get_settings
from onetake_api.integrations.media.aigc_label import draw_aigc_label
from onetake_api.integrations.media.bgm import BgmMixSettings, BgmTrack, build_ducked_mix_filter, resolve_bgm_track
from onetake_api.integrations.media.native_feel import apply_native_feel
from onetake_api.integrations.media.subtitle_burner import burn_subtitles
from onetake_api.modules.composition.port import CompositionRequest
from onetake_api.platform.errors import DomainError


@dataclass(frozen=True)
class ComposeOverrides:
    """「方案覆盖 → 全局配置」的解析结果（**纯函数**：便于单测，不碰 ffmpeg）。

    方案级字段为 `None` 时一律回落全局配置 —— 这样"没设过"与"设成和全局一样"在行为上等价，
    也保证迁移前的老方案逐字不变。
    """

    caption_style: str
    bgm_enabled: bool
    bgm_gain_db: float

    @classmethod
    def resolve(cls, request: object, settings: object) -> "ComposeOverrides":
        requested_bgm = getattr(request, "bgm_enabled", None)
        requested_gain = getattr(request, "bgm_gain_db", None)
        return cls(
            caption_style=str(getattr(request, "caption_style", None) or getattr(settings, "caption_style", "standard")),
            bgm_enabled=bool(getattr(settings, "bgm_enabled", False) if requested_bgm is None else requested_bgm),
            bgm_gain_db=float(getattr(settings, "bgm_gain_db", -20.0) if requested_gain is None else requested_gain),
        )


class LocalComposerError(DomainError):
    code = "COMPOSITION_PROVIDER_ERROR"
    http_status = 502
    retryable = True


class LocalCompositionAdapter:
    """实现 CompositionPort：全部在本地用 FFmpeg 完成，不产生任何按次费用。"""

    provider_name = "local-ffmpeg"

    def __init__(self, *, settings: Settings | None = None) -> None:
        self._settings = settings

    @property
    def settings(self) -> Settings:
        return self._settings or get_settings()

    def compose(self, request: CompositionRequest) -> bytes:
        if not request.base_video_bytes:
            raise LocalComposerError("合成输入为空")
        settings = self.settings
        video = request.base_video_bytes
        # S4-④a：方案级覆盖优先（字幕样式 / BGM 开关 / BGM 强度），未设则回落全局配置
        overrides = ComposeOverrides.resolve(request, settings)
        # 批次 4b：BGM **只在开启且确实有旁白轨**时才解析/叠加（没有旁白 → 保持「成片无音轨」的既有契约）
        bgm = resolve_bgm_track(settings=settings) if overrides.bgm_enabled and request.audio_bytes else None
        base_mix = BgmMixSettings.from_settings(settings)
        video = _mix_audio(
            video, request, keep_model_audio=settings.video_keep_model_audio,
            bgm=bgm,
            bgm_mix=BgmMixSettings(
                gain_db=overrides.bgm_gain_db, duck_threshold=base_mix.duck_threshold, duck_ratio=base_mix.duck_ratio,
            ),
        )
        if request.srt_bytes:
            video = burn_subtitles(
                base_video_bytes=video, srt_bytes=request.srt_bytes,
                duration_seconds=request.duration_seconds, fps=request.fps,
                preserve_audio=bool(request.audio_bytes),
                # 批次 1a：样式与"帧宽比例字号"从配置/请求透传（默认档与改造前逐字相同）
                width=request.width, style=overrides.caption_style,
            )
        if settings.native_feel_enabled:
            video = apply_native_feel(
                video, width=request.width, height=request.height, fps=request.fps,
                strength=settings.native_feel_strength,
            )
        if settings.aigc_label_enabled and settings.aigc_label_source == "local":
            video = draw_aigc_label(
                video, width=request.width, height=request.height, fps=request.fps,
                text=settings.aigc_label_text, position=settings.aigc_label_position,
                size_ratio=settings.aigc_label_size_ratio, opacity=settings.aigc_label_opacity,
                margin_ratio=settings.aigc_label_safe_margin_ratio,
                avoid_subtitle=bool(request.srt_bytes) and settings.aigc_label_avoid_subtitle,
            )
        return video


def _run(command: list[str], label: str) -> None:
    try:
        subprocess.run(command, check=True, capture_output=True, text=True)
    except (subprocess.CalledProcessError, OSError) as exc:
        raise LocalComposerError(f"{label}失败") from exc


def _mix_audio(
    video_bytes: bytes, request: CompositionRequest, *, keep_model_audio: bool,
    bgm: BgmTrack | None = None, bgm_mix: BgmMixSettings | None = None,
) -> bytes:
    """音轨替换 + 响度归一（-14 LUFS）+（可选）BGM 闪避混音 + 时长对齐；视频流直接 copy，不重复编码。

    `bgm` 只会与 **TTS 旁白轨**混合（保模型原声那条路径不叠 BGM，避免双音源语义不清）。
    """
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        video_path = root / "base.mp4"
        output_path = root / "mixed.mp4"
        video_path.write_bytes(video_bytes)
        command = [get_ffmpeg_exe(), "-y", "-i", str(video_path)]
        if request.audio_bytes:
            audio_path = root / "voice.wav"
            audio_path.write_bytes(request.audio_bytes)
            command += ["-i", str(audio_path)]
            if bgm is not None:
                # 音乐循环到成片长度（末尾由外层 -t 兜底），并被旁白压下去
                mix = bgm_mix or BgmMixSettings()
                bgm_path = root / f"bgm{bgm.suffix}"
                bgm_path.write_bytes(bgm.content)
                command += ["-stream_loop", "-1", "-i", str(bgm_path)]
                filter_complex = build_ducked_mix_filter(
                    voice_index=1, bgm_index=2, duration_seconds=request.duration_seconds,
                    gain_db=mix.gain_db, threshold=mix.duck_threshold, ratio=mix.duck_ratio,
                )
            else:
                # alimiter(level=false) 是 NaN 兜底：loudnorm 对纯数字静音输入会算出 NaN 增益，
                # AAC 编码器遇到 NaN 帧直接报错（成片失败）。alimiter 对正常音频是逐位无操作，
                # 只在静音时把 NaN 钳成 0，保证「有 TTS 音频就必然产出带音轨成片」的契约。
                filter_complex = "[1:a]loudnorm=I=-14:TP=-1.5:LRA=11,alimiter=limit=0.95:level=false[a]"
            command += [
                "-filter_complex", filter_complex,
                "-map", "0:v:0", "-map", "[a]",
                "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2",
            ]
        elif keep_model_audio:
            # 保留基片自带音轨（模型原声/口型台词）；此时上层不会再传 TTS 音频，避免双声
            command += ["-map", "0:v:0", "-map", "0:a?"]
        else:
            # 产品契约：未开启"保留模型原声"且没有 TTS 音频（即用户关闭了语音）→ 成片必须无音轨
            command += ["-map", "0:v:0", "-an"]
        command += [
            "-c:v", "copy", "-t", f"{request.duration_seconds:.3f}",
            "-movflags", "+faststart", str(output_path),
        ]
        _run(command, "混音")
        return _read(output_path, "混音")


def _read(path: Path, label: str) -> bytes:
    if not path.is_file() or path.stat().st_size == 0:
        raise LocalComposerError(f"{label}输出为空")
    return path.read_bytes()