from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path

from PIL import Image, ImageStat
from imageio_ffmpeg import get_ffmpeg_exe

from onetake_api.modules.content_qa.domain import QaCheck, QaRequest, QaResult


class RuleContentQaAdapter:
    provider_name = "rules-content-qa"
    model_name = "rules-v1"

    def evaluate(self, request: QaRequest) -> QaResult:
        checks = [
            self._timeline_check(request),
            self._product_check(request),
            self._audio_check(request),
            self._subtitle_check(request),
            self._black_frame_check(request),
            self._spec_check(request),
        ]
        score = sum(check.weight for check in checks if check.passed)
        critical = [check.check_id for check in checks if check.critical and not check.passed]
        return QaResult(passed=score >= 85 and not critical, score=score, checks=checks, critical_failures=critical)

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
        return QaCheck("timeline", "分镜时间轴", valid, 20, message, True)

    @staticmethod
    def _product_check(request: QaRequest) -> QaCheck:
        variant = request.plan.variants[request.plan.selected_variant_index]
        required = any(scene.overlay_product for scene in variant.scenes)
        valid = not required or request.product_layered
        message = "商品图层已锁定" if valid else "分镜要求商品图层，但成片未保留"
        return QaCheck("product_layer", "商品图层", valid, 20, message, True)

    @staticmethod
    def _audio_check(request: QaRequest) -> QaCheck:
        valid = not request.expected_audio or request.metadata.audio_codec == "aac"
        message = "音频轨道符合要求" if valid else "缺少 AAC 音频轨道"
        return QaCheck("audio", "配音音轨", valid, 15, message, True)

    @staticmethod
    def _subtitle_check(request: QaRequest) -> QaCheck:
        message = "字幕已进入成片流程" if request.subtitle_embedded else "字幕未进入成片流程"
        return QaCheck("subtitle", "字幕输出", request.subtitle_embedded, 15, message, True)

    @staticmethod
    def _black_frame_check(request: QaRequest) -> QaCheck:
        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                root = Path(temp_dir)
                video_path = root / "candidate.mp4"
                video_path.write_bytes(request.video_bytes)
                times = [0.5, max(0.5, request.metadata.duration_seconds / 2), max(0.5, request.metadata.duration_seconds - 0.5)]
                for index, seconds in enumerate(times):
                    frame_path = root / f"frame-{index}.png"
                    subprocess.run([get_ffmpeg_exe(), "-y", "-ss", f"{seconds:.3f}", "-i", str(video_path), "-frames:v", "1", str(frame_path)], check=True, capture_output=True, text=True)
                    mean = sum(ImageStat.Stat(Image.open(frame_path).convert("RGB")).mean) / 3
                    if mean < 5:
                        raise ValueError("black frame")
        except (OSError, subprocess.CalledProcessError, ValueError):
            return QaCheck("black_frames", "黑帧检查", False, 15, "检测到黑帧或空帧", True)
        return QaCheck("black_frames", "黑帧检查", True, 15, "关键帧画面正常", True)

    @staticmethod
    def _spec_check(request: QaRequest) -> QaCheck:
        metadata = request.metadata
        valid = (
            metadata.width == 1080
            and metadata.height == 1920
            and abs(metadata.fps - 30) <= 0.1
            and 18 <= metadata.duration_seconds <= 25
            and metadata.video_codec == "h264"
            and request.size_bytes <= 30 * 1024 * 1024
        )
        message = "成片规格校验通过" if valid else "成片规格不符合要求"
        return QaCheck("spec", "成片规格", valid, 15, message, True)
