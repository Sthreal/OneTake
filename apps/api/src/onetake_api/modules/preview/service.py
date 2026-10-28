"""预览片构建器与幂等（S12 提交 1+2）。

**零付费的三条硬规矩**：
1. 底片只从「已采用的关键帧 → 已确认主图（mock 渲染）」两级里取，**永不**调用生成端点；
2. 音轨只**复用**已有配音（付费产物也复用，但不重新生成），没有就用静音轨；
3. 合成只走既有 `LocalCompositionAdapter`（本地 ffmpeg，零按次费用）。

**不入交付物**：产物写 `preview/` 独立前缀，不写 `outputs` 表、不进交付门。
幂等靠 `plan_id + 底片指纹` 的 JSON 边车（不建新表）。
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import tempfile
import wave
from dataclasses import asdict
from io import BytesIO
from pathlib import Path

from imageio_ffmpeg import get_ffmpeg_exe
from sqlalchemy.orm import Session

from onetake_api.config import Settings, get_settings
from onetake_api.integrations.object_storage.dependencies import get_object_storage
from onetake_api.integrations.object_storage.public import ObjectStoragePublicService
from onetake_api.modules.composition.port import CompositionPort, CompositionRequest
from onetake_api.modules.composition.service import LocalCompositionAdapter
from onetake_api.modules.content_plan.public import ContentPlanPublicService
from onetake_api.modules.main_image.public import MainImagePublicService
from onetake_api.modules.preview.domain import (
    AUDIO_SOURCE_EXISTING,
    AUDIO_SOURCE_SILENT,
    BASE_SOURCE_KEYFRAME,
    BASE_SOURCE_MOCK,
    PREVIEW_CRF,
    PREVIEW_FPS,
    PREVIEW_HEIGHT,
    PREVIEW_MAX_BYTES,
    PREVIEW_SHRINK_CRF,
    PREVIEW_SHRINK_MAXRATE,
    PREVIEW_SHUTDOWN_BUFSIZE,
    PREVIEW_WIDTH,
    PreviewArtifact,
    PreviewManifest,
    PreviewNotFoundError,
    PreviewUnavailableError,
    preview_key,
    preview_manifest_key,
)
from onetake_api.modules.video_plan.domain import VideoPlan
from onetake_api.modules.video_plan.keyframe_domain import KEYFRAME_ACCEPTED
from onetake_api.modules.video_plan.keyframe_repository import VideoKeyframeCandidateRepository
from onetake_api.modules.video_plan.public import VideoPlanPublicService
from onetake_api.platform.clock import SystemClock
from onetake_api.platform.errors import DomainError


class PreviewService:
    def __init__(
        self,
        *,
        storage: ObjectStoragePublicService | None = None,
        composer: CompositionPort | None = None,
        settings: Settings | None = None,
    ) -> None:
        self._plans = VideoPlanPublicService()
        self._main_images = MainImagePublicService()
        self._keyframes = VideoKeyframeCandidateRepository()
        self._content_plans = ContentPlanPublicService()
        self._storage = storage
        self._composer = composer
        self._settings = settings
        self._clock = SystemClock()

    # ---------------------------------------------------------------- public
    def build_preview(self, session: Session, project_id: str, *, plan: VideoPlan | None = None,
                      force: bool = False) -> PreviewArtifact:
        resolved = plan or self._plans.latest(session, project_id).plan
        if resolved is None:
            raise PreviewUnavailableError("还没有视频方案，无法生成预览片")
        if plan is None:
            _ = self._plans.latest(session, project_id)  # 触发项目存在性校验

        base_bytes, base_source, base_fingerprint = self._resolve_base(session, project_id)
        audio_bytes, audio_source, audio_fingerprint = self._resolve_audio(session, resolved)
        srt_bytes = self._resolve_srt(session, resolved)
        fingerprint = self._fingerprint(
            plan=resolved,
            base_fingerprint=base_fingerprint,
            audio_fingerprint=audio_fingerprint,
            srt_bytes=srt_bytes,
        )

        key = preview_key(project_id, resolved.id)
        if not force:
            cached = self._load_manifest(project_id, resolved.id)
            if cached is not None and cached.fingerprint == fingerprint and self._object_exists(cached.object_key):
                return self._artifact(cached, cached=True)

        video = self._compose(base_bytes=base_bytes, audio_bytes=audio_bytes, srt_bytes=srt_bytes, plan=resolved)
        video = self._shrink_if_needed(video, plan=resolved)
        self.storage.put_bytes(object_key=key, content=video, mime_type="video/mp4")
        manifest = PreviewManifest(
            project_id=project_id,
            plan_id=resolved.id,
            fingerprint=fingerprint,
            object_key=key,
            width=PREVIEW_WIDTH,
            height=PREVIEW_HEIGHT,
            fps=PREVIEW_FPS,
            duration_seconds=resolved.duration_seconds,
            size_bytes=len(video),
            base_source=base_source,
            audio_source=audio_source,
        )
        self._save_manifest(manifest)
        return self._artifact(manifest, cached=False)

    def latest(self, session: Session, project_id: str) -> PreviewArtifact:
        plan = self._plans.latest(session, project_id).plan
        if plan is None:
            raise PreviewNotFoundError("还没有视频方案，也就没有预览片")
        manifest = self._load_manifest(project_id, plan.id)
        if manifest is None or not self._object_exists(manifest.object_key):
            raise PreviewNotFoundError("预览片尚未生成")
        return self._artifact(manifest, cached=True)

    # --------------------------------------------------------------- 内部：来源
    def _resolve_base(self, session: Session, project_id: str) -> tuple[bytes, str, str]:
        """底片：已采用的关键帧 → 已确认主图（mock 渲染）。两级都用不到就明确报错。"""
        keyframe = self._first_accepted_keyframe(session, project_id)
        if keyframe is not None:
            candidate, scene_id = keyframe
            if candidate.image_object_key:
                content = b"".join(self.storage.read_object(object_key=candidate.image_object_key))
                return content, BASE_SOURCE_KEYFRAME, f"kf:{candidate.id}:{hashlib.sha256(content).hexdigest()[:16]}"
        view = self._main_images.latest(session, project_id)
        if view is not None and view.version.transparent_object_key:
            content = b"".join(self.storage.read_object(object_key=view.version.transparent_object_key))
            return content, BASE_SOURCE_MOCK, f"miv:{view.version.id}:{hashlib.sha256(content).hexdigest()[:16]}"
        raise PreviewUnavailableError("既没有已采用的关键帧，也没有可用的主图，无法生成预览片")

    def _first_accepted_keyframe(self, session: Session, project_id: str):
        plan = self._content_plans.latest(session, project_id)
        if plan is None or not plan.variants:
            return None
        try:
            variant = plan.variants[plan.selected_variant_index]
        except IndexError:
            return None
        for scene in variant.scenes:
            candidate = self._keyframes.accepted_for_scene(session, project_id=project_id, scene_id=scene.scene_id)
            if candidate is not None and candidate.status == KEYFRAME_ACCEPTED and candidate.image_object_key:
                return candidate, scene.scene_id
        return None

    def _resolve_audio(self, session: Session, plan: VideoPlan) -> tuple[bytes | None, str, str]:
        """音轨：**只复用已有配音**（付费产物也复用，但不重新生成）→ 否则静音轨。"""
        if plan.voice_enabled and plan.voice_object_key:
            try:
                content = b"".join(self.storage.read_object(object_key=plan.voice_object_key))
            except Exception:
                content = b""
            if content:
                return content, AUDIO_SOURCE_EXISTING, f"voice:{plan.voice_object_key}"
        return self._silent_wav(plan.duration_seconds), AUDIO_SOURCE_SILENT, "silent"

    def _resolve_srt(self, session: Session, plan: VideoPlan) -> bytes | None:
        if plan.subtitle_enabled and plan.subtitle_object_key:
            try:
                return b"".join(self.storage.read_object(object_key=plan.subtitle_object_key))
            except Exception:
                return None
        return None

    @staticmethod
    def _silent_wav(duration_seconds: float) -> bytes:
        frame_rate = 48000
        frames = max(1, round(duration_seconds * frame_rate))
        output = BytesIO()
        with wave.open(output, "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(frame_rate)
            wav.writeframes(b"\x00\x00" * frames)
        return output.getvalue()

    # --------------------------------------------------------------- 内部：渲染
    def _compose(self, *, base_bytes: bytes, audio_bytes: bytes | None, srt_bytes: bytes | None,
                 plan: VideoPlan) -> bytes:
        base = self._render_base_still(base_bytes, duration_seconds=plan.duration_seconds)
        return self.composer.compose(CompositionRequest(
            base_video_bytes=base,
            audio_bytes=audio_bytes,
            srt_bytes=srt_bytes,
            duration_seconds=plan.duration_seconds,
            width=PREVIEW_WIDTH,
            height=PREVIEW_HEIGHT,
            fps=PREVIEW_FPS,
            motion_effect=None,
        ))

    def _render_base_still(self, image_bytes: bytes, *, duration_seconds: float) -> bytes:
        """把一张底图渲成 480×854 的低码率底片。

        **不复用 `render_base_video`**：它把码率写死成 `-b:v 8M`（渲染器里那是对成片有意义的值），
        在预览尺寸下会直接顶掉「≤3MB」的验收线。这里只做"低分辨率 + 低温 CRF"这一件事，
        不引入任何第二套合成逻辑 —— 混音 / 字幕 / 标识仍然全部走既有 `LocalCompositionAdapter`。
        """
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            image_path = root / "preview.png"
            output_path = root / "base.mp4"
            image_path.write_bytes(image_bytes)
            layout = (
                f"scale={PREVIEW_WIDTH}:{PREVIEW_HEIGHT}:force_original_aspect_ratio=decrease,"
                f"pad={PREVIEW_WIDTH}:{PREVIEW_HEIGHT}:(ow-iw)/2:(oh-ih)/2:color=white,"
                "format=yuv420p"
            )
            command = [
                get_ffmpeg_exe(), "-y", "-loop", "1", "-i", str(image_path),
                "-vf", layout, "-t", f"{duration_seconds:.3f}", "-r", str(PREVIEW_FPS),
                "-an", "-c:v", "libx264", "-crf", str(PREVIEW_CRF), "-preset", "veryfast",
                "-pix_fmt", "yuv420p", str(output_path),
            ]
            self._run(command, "预览底片渲染")
            return output_path.read_bytes()

    def _shrink_if_needed(self, video_bytes: bytes, *, plan: VideoPlan) -> bytes:
        """超过 3MB 就再压一次（保证验收第 2 条）。本地 ffmpeg，零费用。"""
        if len(video_bytes) <= PREVIEW_MAX_BYTES:
            return video_bytes
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            input_path = root / "in.mp4"
            output_path = root / "out.mp4"
            input_path.write_bytes(video_bytes)
            command = [
                get_ffmpeg_exe(), "-y", "-i", str(input_path),
                "-c:v", "libx264", "-crf", str(PREVIEW_SHRINK_CRF),
                "-maxrate", PREVIEW_SHRINK_MAXRATE, "-bufsize", PREVIEW_SHUTDOWN_BUFSIZE,
                "-preset", "veryfast", "-pix_fmt", "yuv420p",
                "-c:a", "aac", "-b:a", "96k", "-t", f"{plan.duration_seconds:.3f}",
                "-movflags", "+faststart", str(output_path),
            ]
            self._run(command, "预览压缩")
            return output_path.read_bytes()

    @staticmethod
    def _run(command: list[str], label: str) -> None:
        try:
            subprocess.run(command, check=True, capture_output=True, text=True)
        except (subprocess.CalledProcessError, OSError) as exc:
            raise PreviewUnavailableError(f"{label}失败") from exc

    # --------------------------------------------------------------- 内部：幂等
    @staticmethod
    def _fingerprint(*, plan: VideoPlan, base_fingerprint: str, audio_fingerprint: str,
                     srt_bytes: bytes | None) -> str:
        payload = {
            "plan_id": plan.id,
            "duration_seconds": round(float(plan.duration_seconds), 3),
            "fps": PREVIEW_FPS,
            "size": [PREVIEW_WIDTH, PREVIEW_HEIGHT],
            "base": base_fingerprint,
            "audio": audio_fingerprint,
            "srt": hashlib.sha256(srt_bytes).hexdigest()[:16] if srt_bytes else "none",
        }
        canonical = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def _load_manifest(self, project_id: str, plan_id: str) -> PreviewManifest | None:
        try:
            content = b"".join(self.storage.read_object(object_key=preview_manifest_key(project_id, plan_id)))
        except Exception:
            return None
        try:
            payload = json.loads(content.decode("utf-8"))
        except Exception:
            return None
        try:
            return PreviewManifest(**payload)
        except TypeError:
            return None

    def _save_manifest(self, manifest: PreviewManifest) -> None:
        payload = json.dumps(asdict(manifest), ensure_ascii=False).encode("utf-8")
        self.storage.put_bytes(
            object_key=preview_manifest_key(manifest.project_id, manifest.plan_id),
            content=payload,
            mime_type="application/json",
        )

    def _object_exists(self, object_key: str) -> bool:
        try:
            self.storage.read_object(object_key=object_key)
            return True
        except Exception:
            return False

    @staticmethod
    def _artifact(manifest: PreviewManifest, *, cached: bool) -> PreviewArtifact:
        return PreviewArtifact(
            project_id=manifest.project_id,
            plan_id=manifest.plan_id,
            object_key=manifest.object_key,
            width=manifest.width,
            height=manifest.height,
            fps=manifest.fps,
            duration_seconds=manifest.duration_seconds,
            size_bytes=manifest.size_bytes,
            fingerprint=manifest.fingerprint,
            base_source=manifest.base_source,
            audio_source=manifest.audio_source,
            cached=cached,
        )

    # --------------------------------------------------------------- 依赖
    @property
    def storage(self) -> ObjectStoragePublicService:
        return self._storage or get_object_storage()

    @property
    def composer(self) -> CompositionPort:
        return self._composer or LocalCompositionAdapter(settings=self.preview_settings)

    @property
    def preview_settings(self) -> Settings:
        """预览专用的设置副本：关掉「去 AI 味」与 AIGC 标识。

        两者都会在成片里再编码一遍（`-b:v 8M`），对"先看一版"没有价值，还会把文件顶过 3MB。
        **只影响预览这一遍**，不改动成片链路的任何配置。
        """
        base = self._settings or get_settings()
        return base.model_copy(update={"native_feel_enabled": False, "aigc_label_enabled": False})
