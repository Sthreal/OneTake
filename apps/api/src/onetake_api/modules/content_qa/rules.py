from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path

from imageio_ffmpeg import get_ffmpeg_exe

from onetake_api.modules.content_qa.domain import LEVEL_FAIL, LEVEL_OK, LEVEL_WARN, QaCheck, QaRequest, QaResult
from onetake_api.modules.content_qa.signals import QC_PARAMS, QcSignals, SignalProbeError, probe_signals

# 权重口径（Phase 5 重排）：
# - 关键项合计 100 分，决定 passed（>=85 且无 critical 失败）
# - 客观信号（静音/冻结/响度/时长漂移）**不计分**，只产出 warn 级条目，
#   因为它们往往是"风格问题"而非"坏片"；真正的坏片由黑帧这类关键项拦住
CRITICAL_WEIGHTS = {
    # 关键项合计必须为 100：客观信号是 weight=0 的纯 warn，不需要为它们腾分数
    "timeline": 20,
    "product_layer": 20,
    "audio": 15,
    "subtitle": 15,
    "black_frames": 15,
    "spec": 15,
}
PASS_SCORE = 85


class RuleContentQaAdapter:
    provider_name = "rules-content-qa"
    model_name = "rules-v2"

    def evaluate(self, request: QaRequest) -> QaResult:
        signals, probe_error = self._probe(request)
        checks = [
            self._timeline_check(request),
            self._product_check(request),
            self._audio_check(request),
            self._subtitle_check(request),
            self._black_frame_check(signals, probe_error),
            self._silence_check(signals, request),
            self._freeze_check(signals),
            self._loudness_check(signals, request),
            self._duration_drift_check(signals, request),
            self._spec_check(request),
        ]
        score = sum(check.weight for check in checks if check.passed)
        critical = [check.check_id for check in checks if check.critical and not check.passed]
        return QaResult(
            passed=score >= PASS_SCORE and not critical,
            score=score,
            checks=checks,
            critical_failures=critical,
            signals=signals.as_dict() if signals else None,
        )

    @staticmethod
    def _probe(request: QaRequest) -> tuple[QcSignals | None, str | None]:
        try:
            return probe_signals(request.video_bytes), None
        except SignalProbeError as exc:
            return None, exc.message

    # ---- 关键项 ----

    @staticmethod
    def _timeline_check(request: QaRequest) -> QaCheck:
        variant = request.plan.variants[request.plan.selected_variant_index]
        scenes = sorted(variant.scenes, key=lambda item: item.start_seconds)
        valid = bool(scenes)
        cursor = 0.0
        for scene in scenes:
            if scene.start_seconds < 0 or scene.end_seconds <= scene.start_seconds or scene.start_seconds < cursor - 0.001:
                valid = False
                break
            cursor = scene.end_seconds
        if scenes and abs(scenes[-1].end_seconds - request.plan.total_duration_seconds) > 0.2:
            valid = False
        message = "分镜时间轴连续且覆盖完整" if valid else "分镜时间轴不连续或未覆盖完整"
        return QaCheck("timeline", "分镜时间轴", valid, CRITICAL_WEIGHTS["timeline"], message, True,
                       LEVEL_OK if valid else LEVEL_FAIL)

    @staticmethod
    def _product_check(request: QaRequest) -> QaCheck:
        variant = request.plan.variants[request.plan.selected_variant_index]
        required = any(scene.overlay_product for scene in variant.scenes)
        valid = not required or request.product_layered
        message = "商品图层已锁定" if valid else "分镜要求商品图层，但成片未保留"
        return QaCheck("product_layer", "商品图层", valid, CRITICAL_WEIGHTS["product_layer"], message, True,
                       LEVEL_OK if valid else LEVEL_FAIL)

    @staticmethod
    def _audio_check(request: QaRequest) -> QaCheck:
        valid = not request.expected_audio or request.metadata.audio_codec == "aac"
        message = "音频轨道符合要求" if valid else "缺少 AAC 音频轨道"
        return QaCheck("audio", "配音音轨", valid, CRITICAL_WEIGHTS["audio"], message, True,
                       LEVEL_OK if valid else LEVEL_FAIL)

    @staticmethod
    def _subtitle_check(request: QaRequest) -> QaCheck:
        message = "字幕已进入成片流程" if request.subtitle_embedded else "字幕未进入成片流程"
        return QaCheck("subtitle", "字幕输出", request.subtitle_embedded, CRITICAL_WEIGHTS["subtitle"], message, True,
                       LEVEL_OK if request.subtitle_embedded else LEVEL_FAIL)

    def _black_frame_check(self, signals: QcSignals | None, probe_error: str | None) -> QaCheck:
        if signals is None:
            return QaCheck(
                "black_frames", "黑帧检查", False, CRITICAL_WEIGHTS["black_frames"],
                f"无法解析视频信号：{probe_error or '未知原因'}", True, LEVEL_FAIL,
            )
        if signals.black:
            spans = [round(segment.start, 2) for segment in signals.black]
            return QaCheck(
                "black_frames", "黑帧检查", False, CRITICAL_WEIGHTS["black_frames"],
                f"检测到 {len(signals.black)} 段黑帧（起始 {spans[:3]} 秒）", True, LEVEL_FAIL,
                at_seconds=[segment.start for segment in signals.black],
            )
        return QaCheck("black_frames", "黑帧检查", True, CRITICAL_WEIGHTS["black_frames"],
                       "整片未检出黑帧", True, LEVEL_OK)

    @staticmethod
    def _spec_check(request: QaRequest) -> QaCheck:
        metadata = request.metadata
        valid = (
            metadata.width == 1080
            and metadata.height == 1920
            and abs(metadata.fps - 30) <= 0.1
            # 短版（2026-10-15）：成片时长跟随分镜（8~25 秒）；原来钉死 18 秒下限会把 10~14 秒的成片判 fail
            and 8 <= metadata.duration_seconds <= 25
            and metadata.video_codec == "h264"
            and request.size_bytes <= 30 * 1024 * 1024
        )
        message = "成片规格校验通过" if valid else "成片规格不符合要求"
        return QaCheck("spec", "成片规格", valid, CRITICAL_WEIGHTS["spec"], message, True,
                       LEVEL_OK if valid else LEVEL_FAIL)

    # ---- 客观信号（不计分，只产出 warn）----

    def _silence_check(self, signals: QcSignals | None, request: QaRequest) -> QaCheck:
        if signals is None or not request.expected_audio:
            return QaCheck("silence", "静音检查", True, 0, "无音轨或信号不可用，跳过静音检查", False, LEVEL_OK)
        if signals.silence:
            longest = max(segment.duration for segment in signals.silence)
            return QaCheck(
                "silence", "静音检查", False, 0,
                f"检测到 {len(signals.silence)} 段静音，最长 {longest:.1f} 秒", False, LEVEL_WARN,
                at_seconds=[segment.start for segment in signals.silence],
            )
        return QaCheck("silence", "静音检查", True, 0, "未检出长静音", False, LEVEL_OK)

    def _freeze_check(self, signals: QcSignals | None) -> QaCheck:
        if signals is None:
            return QaCheck("freeze", "冻结检查", True, 0, "信号不可用，跳过冻结检查", False, LEVEL_OK)
        if signals.freeze:
            longest = max(segment.duration for segment in signals.freeze)
            return QaCheck(
                "freeze", "冻结检查", False, 0,
                f"检测到 {len(signals.freeze)} 段画面冻结，最长 {longest:.1f} 秒", False, LEVEL_WARN,
                at_seconds=[segment.start for segment in signals.freeze],
            )
        return QaCheck("freeze", "冻结检查", True, 0, "未检出长时间画面冻结", False, LEVEL_OK)

    def _loudness_check(self, signals: QcSignals | None, request: QaRequest) -> QaCheck:
        if signals is None or not request.expected_audio or signals.loudness_lufs is None:
            return QaCheck("loudness", "响度检查", True, 0, "无音轨或响度不可测，跳过响度检查", False, LEVEL_OK)
        target = QC_PARAMS["loudness_target_lufs"]
        delta = abs(signals.loudness_lufs - target)
        if signals.loudness_lufs < QC_PARAMS["loudness_fail_below_lufs"]:
            return QaCheck(
                "loudness", "响度检查", False, 0,
                f"响度 {signals.loudness_lufs:.1f} LUFS 明显过低（低于 {QC_PARAMS['loudness_fail_below_lufs']}），人声可能缺失",
                False, LEVEL_WARN,
            )
        if delta > QC_PARAMS["loudness_warn_delta"]:
            return QaCheck(
                "loudness", "响度检查", False, 0,
                f"响度 {signals.loudness_lufs:.1f} LUFS 偏离目标 {target:.0f} LUFS 超过 {QC_PARAMS['loudness_warn_delta']:.0f}",
                False, LEVEL_WARN,
            )
        if signals.true_peak_dbfs is not None and signals.true_peak_dbfs > QC_PARAMS["true_peak_warn_above_dbfs"]:
            return QaCheck(
                "loudness", "响度检查", False, 0,
                f"真峰值 {signals.true_peak_dbfs:.2f} dBFS 偏高，可能削波", False, LEVEL_WARN,
            )
        return QaCheck("loudness", "响度检查", True, 0, f"响度 {signals.loudness_lufs:.1f} LUFS 正常", False, LEVEL_OK)

    def _duration_drift_check(self, signals: QcSignals | None, request: QaRequest) -> QaCheck:
        if signals is None or signals.duration_seconds is None:
            return QaCheck("duration_drift", "时长检查", True, 0, "时长不可测，跳过时长检查", False, LEVEL_OK)
        drift = abs(signals.duration_seconds - request.metadata.duration_seconds)
        if drift > QC_PARAMS["duration_drift_warn_seconds"]:
            return QaCheck(
                "duration_drift", "时长检查", False, 0,
                f"成片时长与元数据相差 {drift:.2f} 秒（超过 {QC_PARAMS['duration_drift_warn_seconds']} 秒）",
                False, LEVEL_WARN,
            )
        return QaCheck("duration_drift", "时长检查", True, 0, "时长与元数据一致", False, LEVEL_OK)