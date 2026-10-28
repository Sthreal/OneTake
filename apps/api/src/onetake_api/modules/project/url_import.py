"""从商品 URL 建项目（S13 提交 3）。

**核心取舍：不新增资产路径。** 抓到的图片走与手动上传**完全相同**的一段代码 ——
`AssetPublicService.presign_upload` 登记 → 服务端写 MinIO → `complete_upload` 复核并转 READY。
好处是白拿既有的一整套保证：`uq_asset_project_sha256` 去重、大小/格式/尺寸三重校验、
`AssetRegistered` 事件、`pipeline.mark_assets_ready`、项目配额。

失败语义（两者要分清）：
- **SSRF 拒绝**（含**任何一跳**跳转）→ **硬拒绝**，抛 `UrlNotAllowedError`（上层 4xx），**不建项目**。
  因为它不是"抓不到"，而是"试图访问内网"——降级成 warning 会把这个信号藏起来。
- **普通抓取失败**（超时 / 目标 4xx / 非 HTML / 图片取不到）→ **项目照建** + 返回 `warning`，
  用户继续走手动上传（硬约束是"可追踪、可回退"，不是"一步成功"）。
"""
from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
from io import BytesIO

import httpx
from PIL import Image, UnidentifiedImageError
from sqlalchemy.orm import Session

from onetake_api.integrations.object_storage.public import ObjectStoragePublicService
from onetake_api.integrations.url_fetch.fetcher import UrlFetchError, fetch_html, fetch_image
from onetake_api.integrations.url_fetch.guard import UrlNotAllowedError, validate_target_url
from onetake_api.integrations.url_fetch.parser import parse_product_page
from onetake_api.modules.asset.application.commands import (
    CompleteUploadCommand,
    PresignUploadCommand,
)
from onetake_api.modules.asset.domain.model import PIL_FORMAT_TO_MIME
from onetake_api.modules.asset.public import AssetPublicService
from onetake_api.modules.project.public import ProjectPublicService

MAX_TITLE_CHARS = 60
FALLBACK_NOTE = "由商品链接导入"


@dataclass(frozen=True)
class UrlImportResult:
    project_id: str
    product_name: str
    product_price: str | None
    asset_ids: list[str] = field(default_factory=list)
    warning: str | None = None
    source: str = "none"


def _shorten(value: str | None, fallback: str) -> str:
    text = (value or "").strip()
    if not text:
        return fallback
    return text[:MAX_TITLE_CHARS]


def _image_metadata(content: bytes) -> tuple[str, int, int]:
    """返回 (mime, width, height)；不是受支持的图片就抛 `UrlFetchError`。"""
    try:
        with Image.open(BytesIO(content)) as image:
            image.verify()
        with Image.open(BytesIO(content)) as image:
            detected = (image.format or "").upper()
            width, height = image.size
    except (UnidentifiedImageError, OSError) as exc:
        raise UrlFetchError("抓到的图片无法识别") from exc
    mime = PIL_FORMAT_TO_MIME.get(detected)
    if mime is None:
        raise UrlFetchError(f"不支持的图片格式（{detected or '未知'}）")
    return mime, width, height


def _register_asset(
    session: Session,
    *,
    storage: ObjectStoragePublicService,
    project_id: str,
    filename: str,
    content: bytes,
) -> str:
    """把图片落进**既有**资产链路（presign → 写对象 → complete），返回 asset_id。"""
    mime, width, height = _image_metadata(content)
    sha256 = hashlib.sha256(content).hexdigest()
    command = PresignUploadCommand(
        original_filename=filename, mime_type=mime, size_bytes=len(content),
        width=width, height=height, sha256=sha256,
    )
    assets = AssetPublicService()
    presigned = assets.presign_upload(session, project_id=project_id, command=command, storage=storage)
    storage.put_bytes(
        object_key=presigned.asset.object_key, content=content, mime_type=mime
    )
    completed = assets.complete_upload(
        session,
        project_id=project_id,
        asset_id=presigned.asset.id,
        command=CompleteUploadCommand(
            original_filename=filename, mime_type=mime, size_bytes=len(content),
            width=width, height=height, sha256=sha256,
        ),
        storage=storage,
    )
    return completed.id


def import_project_from_url(
    session: Session,
    *,
    url: str,
    storage: ObjectStoragePublicService,
    client: httpx.Client | None = None,
) -> UrlImportResult:
    """粘一个商品链接 → 建好项目（尽量）落好主图。"""
    # 先挡掉明显的内网地址：这一步不发任何请求（验收 2）
    validate_target_url(url)

    draft = None
    warning: str | None = None
    try:
        page = fetch_html(url, client=client)
        draft = parse_product_page(page.html, base_url=page.url)
    except UrlNotAllowedError:
        raise  # 任何一跳指向内网 → 硬拒绝（验收 5）
    except UrlFetchError as exc:
        warning = f"页面抓取失败（{exc.message}），已建项目，请手动上传商品图"

    product_name = _shorten(draft.title if draft else None, url.split("/")[2] if "//" in url else "新项目")
    project = ProjectPublicService().create_project(
        session, product_name=product_name, product_note=FALLBACK_NOTE
    )

    asset_ids: list[str] = []
    if draft is not None and draft.image_url:
        try:
            binary = fetch_image(draft.image_url, client=client)
            asset_ids.append(
                _register_asset(
                    session, storage=storage, project_id=project.id,
                    filename=f"import.{binary.content_type.split('/')[-1]}", content=binary.content,
                )
            )
        except UrlNotAllowedError:
            raise  # 图片地址指向内网同样硬拒绝
        except Exception as exc:  # noqa: BLE001 —— 有意放宽，理由见下
            # 图片失败**不阻断**：项目已经建好，用户可以手动补图。
            # 放宽到 Exception 是有意的 —— 资产链路自身也会因"重复素材 / 超配额 / 尺寸不符"拒绝，
            # 那些都属于"这张图用不了"，不该让整个导入失败。
            detail = getattr(exc, "message", None) or str(exc)
            warning = (warning + "；" if warning else "") + f"主图导入失败（{detail}），请手动上传"
    elif draft is not None:
        warning = (warning + "；" if warning else "") + "页面里没有可用主图，请手动上传"

    return UrlImportResult(
        project_id=project.id,
        product_name=product_name,
        product_price=draft.price if draft else None,
        asset_ids=asset_ids,
        warning=warning,
        source=draft.source if draft else "none",
    )