"""去 AI 味后处理（native-feel）。

为什么需要：2026 年平台普遍降权"过度精致/重滤镜/摆拍"的内容，反而偏好真实手持质感。
做法刻意保守且**确定性可复现**（正弦驱动而非随机），不同 seed 产出不同变体便于 A/B：

- 手持微抖：用 crop 窗口做正弦偏移后再放大回原尺寸（不会露出黑边）
- 时间颗粒：noise 滤镜
- 轻微去抛光：降一点饱和与对比
- 可选 halation：高光提亮 + 模糊 + 暖色，再 screen 叠回（真实镜头的高光会"晕开"）

顺序注意：**必须放在 AIGC 标识与字幕之后吗？** 不 —— 正确顺序是"字幕 → native-feel → AIGC 标识"，
否则手抖的 crop 偏移会把先烧好的标识裁掉一部分（见总体方案 §9.2.1）。
"""
from __future__ import annotations

import math
import subprocess
import tempfile
from pathlib import Path

from imageio_ffmpeg import get_ffmpeg_exe

from onetake_api.integrations.media.video_utils import inspect_video_dimensions

from onetake_api.platform.errors import DomainError

STRENGTH_AMPLITUDE: dict[str, int] = {"subtle": 4, "medium": 8, "strong": 13}
GRAIN_STRENGTH = 6
DEFAULT_STRENGTH = "subtle"


class NativeFeelError(DomainError):
    code = "VIDEO_POSTPROCESS_ERROR"
    http_status = 502
    retryable = True


def build_filter_chain(
    *,
    width: int,
    height: int,
    strength: str = DEFAULT_STRENGTH,
    seed: int = 0,
    grain: bool = True,
    halation: bool = False,
    source_width: int | None = None,
    source_height: int | None = None,
) -> str:
    """构造 filter_complex（输出标签固定为 [v]），纯函数便于单测。"""
    # 裁剪必须按**源尺寸**（r2v 720P 产物 720x1280 ≠ 成片 1080x1920）：2026-10-15 实测，
    # 按成片规格算出的 crop=1070:1910 对 720 宽的输入非法 → ffmpeg 直接失败（VIDEO_POSTPROCESS_ERROR）。
    src_width = source_width or width
    src_height = source_height or height
    amplitude = STRENGTH_AMPLITUDE.get(strength, STRENGTH_AMPLITUDE[DEFAULT_STRENGTH])
    margin = amplitude * 2 + 2
    crop_width = max(2, src_width - margin)
    crop_height = max(2, src_height - margin)
    phase = math.radians(seed % 360)
    x_expr = f"{margin / 2:.1f}+{amplitude:.1f}*sin(2*PI*t/3.7+{phase:.4f})"
    y_expr = f"{margin / 2:.1f}+{amplitude * 0.6:.1f}*sin(2*PI*t/4.9+{phase:.4f})"
    chain = [
        f"crop={crop_width}:{crop_height}:x='{x_expr}':y='{y_expr}'",
        f"scale={width}:{height}",
    ]
    if grain:
        chain.append(f"noise=alls={GRAIN_STRENGTH}:allf=t+u")
    # 轻微去抛光：真实手机直出不会那么"干净"
    chain.append("eq=saturation=0.97:contrast=0.98:brightness=-0.01")
    tail = ",".join(chain)

    if not halation:
        return f"[0:v]{tail}[v]"
    glow = (
        "[0:v]split=2[base][hl];"
        "[hl]gblur=sigma=12,colorchannelmixer=rr=1.10:gg=1.02:bb=0.95[glow];"
        "[base][glow]blend=all_mode=screen:all_opacity=0.30[hlmix];"
        f"[hlmix]{tail}[v]"
    )
    return glow


def apply_native_feel(
    video_bytes: bytes,
    *,
    width: int,
    height: int,
    fps: int = 30,
    strength: str = DEFAULT_STRENGTH,
    seed: int = 0,
    grain: bool = True,
    halation: bool = False,
) -> bytes:
    if not video_bytes:
        raise NativeFeelError("去 AI 味输入为空")
    if width <= 0 or height <= 0:
        raise NativeFeelError("去 AI 味缺少有效画面尺寸")
    # 用**真实输入尺寸**算裁剪；探测失败就退回目标尺寸（与改动前一致）
    try:
        source_width, source_height = inspect_video_dimensions(video_bytes)
    except Exception:  # noqa: BLE001
        source_width, source_height = None, None
    chain = build_filter_chain(
        width=width, height=height, strength=strength, seed=seed, grain=grain, halation=halation,
        # 关键：裁剪按"源尺寸"——r2v 720P 产物是 720x1280，按 1080x1920 算裁剪会非法（2026-10-15 复现）
        source_width=source_width, source_height=source_height,
    )
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        input_path = root / "input.mp4"
        output_path = root / "output.mp4"
        input_path.write_bytes(video_bytes)
        command = [
            get_ffmpeg_exe(), "-y", "-i", str(input_path),
            "-filter_complex", chain,
            "-map", "[v]", "-map", "0:a?",
            "-r", str(fps),
            "-c:v", "libx264", "-b:v", "8M", "-pix_fmt", "yuv420p",
            "-c:a", "copy",
            str(output_path),
        ]
        try:
            subprocess.run(command, check=True, capture_output=True, text=True)
        except subprocess.CalledProcessError as exc:
            # 把 ffmpeg 的真实报错带出来：原来只有一句"处理失败"，定位只能靠手工复现
            tail = [line for line in (exc.stderr or "").strip().splitlines() if line.strip()][-2:]
            raise NativeFeelError("去 AI 味处理失败：" + " | ".join(tail)) from exc
        except OSError as exc:
            raise NativeFeelError("去 AI 味处理失败（无法启动 ffmpeg）") from exc
        if not output_path.is_file() or output_path.stat().st_size == 0:
            raise NativeFeelError("去 AI 味输出为空")
        return output_path.read_bytes()