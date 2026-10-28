"""客观质检信号（Phase 5）：黑帧 / 静音 / 冻结 / 响度 / 时长漂移。

为什么要从"抽 3 帧看亮度"换成信号扫描：
抽帧只能看到那几个瞬间，中段整段黑、长静音、画面冻结都检不出来；而"无人值守批量管线
发出黑帧/静音/截断视频"恰恰是同类工具最大的投诉来源。

阈值经过防误判校准（与业界实测口径一致）：
- 慢速 zoompan 不能被判成"冻结"
- 句间停顿不能被判成"静音"

本模块只负责取信号与阈值判定，不决定交付与否（那是交付门的事）。
"""
from __future__ import annotations

import re
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from imageio_ffmpeg import get_ffmpeg_exe

from onetake_api.platform.errors import DomainError

# ---- 阈值（可调，改动即改变交付门判定）----
QC_PARAMS = {
    "black_min_seconds": 0.4,
    "black_pixel_threshold": 0.10,
    "silence_noise_db": -50,
    "silence_min_seconds": 2.5,
    "freeze_noise_db": -60,
    "freeze_min_seconds": 4,
    "loudness_target_lufs": -14.0,
    "loudness_warn_delta": 4.0,
    "loudness_fail_below_lufs": -30.0,
    "true_peak_warn_above_dbfs": -0.5,
    "duration_drift_warn_seconds": 0.5,
}

_BLACK_RE = re.compile(r"black_start:\s*([\d.]+)\s+black_end:\s*([\d.]+)\s+black_duration:\s*([\d.]+)")
_SILENCE_START_RE = re.compile(r"silence_start:\s*(-?[\d.]+)")
_SILENCE_END_RE = re.compile(r"silence_end:\s*(-?[\d.]+)\s*\|\s*silence_duration:\s*([\d.]+)")
_FREEZE_START_RE = re.compile(r"freeze_start:\s*(-?[\d.]+)")
_FREEZE_END_RE = re.compile(r"freeze_end:\s*(-?[\d.]+)")
_LOUDNESS_RE = re.compile(r"Input Integrated:\s*(-?[\d.]+)\s*LUFS")
_TRUE_PEAK_RE = re.compile(r"Input True Peak:\s*(-?[\d.]+)\s*dBFS")


class SignalProbeError(DomainError):
    code = "VIDEO_QC_PROBE_FAILED"
    http_status = 502
    retryable = True


@dataclass(frozen=True)
class QcSegment:
    start: float
    end: float
    duration: float


@dataclass(frozen=True)
class QcSignals:
    black: list[QcSegment] = field(default_factory=list)
    silence: list[QcSegment] = field(default_factory=list)
    freeze: list[QcSegment] = field(default_factory=list)
    loudness_lufs: float | None = None
    true_peak_dbfs: float | None = None
    duration_seconds: float | None = None

    def as_dict(self) -> dict:
        return {
            "black": [segment.__dict__ for segment in self.black],
            "silence": [segment.__dict__ for segment in self.silence],
            "freeze": [segment.__dict__ for segment in self.freeze],
            "loudness_lufs": self.loudness_lufs,
            "true_peak_dbfs": self.true_peak_dbfs,
            "duration_seconds": self.duration_seconds,
        }

    @staticmethod
    def from_dict(payload: dict | None) -> "QcSignals":
        if not payload:
            return QcSignals()
        return QcSignals(
            black=[QcSegment(**item) for item in payload.get("black", [])],
            silence=[QcSegment(**item) for item in payload.get("silence", [])],
            freeze=[QcSegment(**item) for item in payload.get("freeze", [])],
            loudness_lufs=payload.get("loudness_lufs"),
            true_peak_dbfs=payload.get("true_peak_dbfs"),
            duration_seconds=payload.get("duration_seconds"),
        )


def parse_signals(stderr: str) -> QcSignals:
    """从 ffmpeg 的 stderr 里解析各路信号（纯函数，便于用真实输出做单测）。"""
    black = [QcSegment(float(start), float(end), float(duration)) for start, end, duration in _BLACK_RE.findall(stderr)]

    silence: list[QcSegment] = []
    pending_start: float | None = None
    for line in stderr.splitlines():
        start_match = _SILENCE_START_RE.search(line)
        if start_match:
            pending_start = float(start_match.group(1))
        end_match = _SILENCE_END_RE.search(line)
        if end_match:
            end = float(end_match.group(1))
            duration = float(end_match.group(2))
            start = pending_start if pending_start is not None else max(0.0, end - duration)
            silence.append(QcSegment(start, end, duration))
            pending_start = None

    freeze: list[QcSegment] = []
    freeze_start: float | None = None
    for line in stderr.splitlines():
        start_match = _FREEZE_START_RE.search(line)
        if start_match:
            freeze_start = float(start_match.group(1))
        end_match = _FREEZE_END_RE.search(line)
        if end_match:
            end = float(end_match.group(1))
            start = freeze_start if freeze_start is not None else end
            freeze.append(QcSegment(start, end, max(0.0, end - start)))
            freeze_start = None

    loudness_match = _LOUDNESS_RE.search(stderr)
    peak_match = _TRUE_PEAK_RE.search(stderr)
    duration_match = re.search(r"Duration:\s*(\d+):(\d+):([\d.]+)", stderr)
    duration = None
    if duration_match:
        hours, minutes, seconds = duration_match.groups()
        duration = round(int(hours) * 3600 + int(minutes) * 60 + float(seconds), 3)

    return QcSignals(
        black=black, silence=silence, freeze=freeze,
        loudness_lufs=float(loudness_match.group(1)) if loudness_match else None,
        true_peak_dbfs=float(peak_match.group(1)) if peak_match else None,
        duration_seconds=duration,
    )


def probe_signals(video_bytes: bytes) -> QcSignals:
    """跑两遍 ffmpeg：一遍取黑帧/静音/冻结，一遍取响度（loudnorm 需要独立分析）。"""
    if not video_bytes:
        raise SignalProbeError("质检输入为空")
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        video_path = root / "input.mp4"
        video_path.write_bytes(video_bytes)
        detect = [
            get_ffmpeg_exe(), "-hide_banner", "-nostats", "-i", str(video_path),
            "-vf", (
                f"blackdetect=d={QC_PARAMS['black_min_seconds']}:"
                f"pix_th={QC_PARAMS['black_pixel_threshold']},"
                f"freezedetect=n={QC_PARAMS['freeze_noise_db']}dB:d={QC_PARAMS['freeze_min_seconds']}"
            ),
            "-af", f"silencedetect=n={QC_PARAMS['silence_noise_db']}dB:d={QC_PARAMS['silence_min_seconds']}",
            "-f", "null", "-",
        ]
        loudness = [
            get_ffmpeg_exe(), "-hide_banner", "-nostats", "-i", str(video_path),
            "-af", (
                f"loudnorm=I={QC_PARAMS['loudness_target_lufs']}:TP=-1.5:LRA=11:"
                "print_format=summary"
            ),
            "-f", "null", "-",
        ]
        first = _run(detect)
        second = _run(loudness)
    return parse_signals(first + "\n" + second)


def _run(command: list[str]) -> str:
    try:
        result = subprocess.run(command, capture_output=True, errors="replace")
    except OSError as exc:
        raise SignalProbeError("质检信号扫描失败") from exc
    stderr = result.stderr or ""
    if result.returncode != 0:
        raise SignalProbeError(f"质检信号扫描失败（ffmpeg {result.returncode}）")
    return stderr