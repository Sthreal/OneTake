"""预览片的领域常量与契约（S12 提交 1）。

**预览不是交付物**：不写 `outputs` 表、不进交付门、不占用 `final.mp4` 的 key 规则 ——
它只是一份"零付费先看一版"的参考片，用来确认**节奏 / 文案 / 字幕位置**。
"""
from __future__ import annotations

from dataclasses import dataclass

from onetake_api.platform.errors import DomainError

# 预览规格（待拍板第 2 项：480×854 —— 手机竖屏看节奏足够，再高就接近"正式片"费时）
PREVIEW_WIDTH = 480
PREVIEW_HEIGHT = 854
PREVIEW_FPS = 30
# 码率上限：低温 CRF + 必要时一次收缩重编码，保证文件小（验收第 2 条 ≤3MB）
PREVIEW_CRF = 30
PREVIEW_SHRINK_CRF = 34
PREVIEW_SHRINK_MAXRATE = "800k"
PREVIEW_SHUTDOWN_BUFSIZE = "1600k"
PREVIEW_MAX_BYTES = 3 * 1024 * 1024
# 时长允许误差（验收第 2 条）
PREVIEW_MAX_DURATION_DRIFT_SECONDS = 0.5

# 底片来源（**只有这两级**，永不调用生成端点）
BASE_SOURCE_KEYFRAME = "accepted_keyframe"
BASE_SOURCE_MOCK = "mock_render"
# 音轨来源（**允许复用付费产出、绝不重新生成**，待拍板第 3 项）
AUDIO_SOURCE_EXISTING = "existing_voice"
AUDIO_SOURCE_SILENT = "silent_track"

# 存储 key：独立 `preview/` 前缀，与 `output/{plan_id}/final.mp4` 彻底隔离
def preview_key(project_id: str, plan_id: str) -> str:
    return f"projects/{project_id}/preview/{plan_id}/preview.mp4"


def preview_manifest_key(project_id: str, plan_id: str) -> str:
    """幂等清单（JSON 边车）。**不建新表**：清单与产物同生共死，天然无脏数据。"""
    return f"projects/{project_id}/preview/{plan_id}/manifest.json"


class PreviewUnavailableError(DomainError):
    """没有可用底片（既没有已采用的关键帧，也没有已确认主图）→ 明确报错，不偷偷花钱。"""

    code = "PREVIEW_UNAVAILABLE"
    http_status = 409
    retryable = False


class PreviewDisabledError(DomainError):
    code = "PREVIEW_DISABLED"
    http_status = 403
    retryable = False


class PreviewNotFoundError(DomainError):
    code = "PREVIEW_NOT_FOUND"
    http_status = 404
    retryable = False


@dataclass(frozen=True)
class PreviewArtifact:
    project_id: str
    plan_id: str
    object_key: str
    width: int
    height: int
    fps: int
    duration_seconds: float
    size_bytes: int
    fingerprint: str
    base_source: str
    audio_source: str
    cached: bool = False


@dataclass(frozen=True)
class PreviewManifest:
    """幂等清单：`plan_id + 底片指纹` 命中就直接复用（避免反复渲染）。"""

    project_id: str
    plan_id: str
    fingerprint: str
    object_key: str
    width: int
    height: int
    fps: int
    duration_seconds: float
    size_bytes: int
    base_source: str
    audio_source: str
