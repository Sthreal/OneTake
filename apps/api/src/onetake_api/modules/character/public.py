from __future__ import annotations

import hashlib

from sqlalchemy.orm import Session

from onetake_api.integrations.object_storage.public import ObjectStoragePublicService
from onetake_api.modules.asset.public import AssetPublicService
from onetake_api.modules.character.domain import Character, CharacterNotFoundError, CharacterValidationError
from onetake_api.modules.character.repository import CharacterRepository
from onetake_api.platform.clock import SystemClock
from onetake_api.platform.ids import new_id

SHEET_URL_SECONDS = 3600


def sheet_key(character_id: str) -> str:
    """母版的存储键：**独立前缀**（不挂项目）—— 见 domain.py 的边界说明。"""
    return f"characters/{character_id}/sheet.png"


def source_sheet_key(character_id: str) -> str:
    """**原照片**的留存键：升级四视角前的输入会先存一份，重跑仍以它为输入（避免越跑越糊）。"""
    return f"characters/{character_id}/source.png"


def _mock_four_view_sheet(image_bytes: bytes) -> bytes:
    """mock：把同一张照片确定性拼成 2×2（带白缝）——离线/0 成本验证"入库 + 复用"这条链。"""
    from io import BytesIO

    from PIL import Image, ImageDraw

    with Image.open(BytesIO(image_bytes)) as source:
        cell = source.convert("RGB")
    width, height = cell.size
    canvas = Image.new("RGB", (width * 2, height * 2), (255, 255, 255))
    for index in range(4):
        row, column = divmod(index, 2)
        canvas.paste(cell, (column * width, row * height))
    draw = ImageDraw.Draw(canvas)
    draw.line([(width, 0), (width, height * 2)], fill=(255, 255, 255), width=2)
    draw.line([(0, height), (width * 2, height)], fill=(255, 255, 255), width=2)
    buffer = BytesIO()
    canvas.save(buffer, format="PNG")
    return buffer.getvalue()


class CharacterPublicService:
    def __init__(self, *, storage: ObjectStoragePublicService | None = None) -> None:
        self._repository = CharacterRepository()
        self._assets = AssetPublicService()
        self._storage = storage
        self._clock = SystemClock()

    @property
    def storage(self) -> ObjectStoragePublicService:
        from onetake_api.integrations.object_storage.dependencies import get_object_storage

        return self._storage or get_object_storage()

    def create_from_asset(
        self, session: Session, *, name: str, appearance: str, voice_style: str | None,
        project_id: str, asset_id: str,
    ) -> Character:
        """用**用户已上传的照片**建一个出镜人（0 成本）；照片复制到独立前缀后永久留存。"""
        if len(name.strip()) < 1:
            raise CharacterValidationError("出镜人需要一个名字")
        asset = self._assets.get_asset(session, asset_id=asset_id)
        if asset is None or asset.project_id != project_id:
            raise CharacterValidationError("照片不存在或不属于该项目")
        content = b"".join(self.storage.read_object(object_key=asset.object_key))
        if not content:
            raise CharacterValidationError("照片内容为空")
        character_id = new_id("chr")
        key = sheet_key(character_id)
        self.storage.put_bytes(object_key=key, content=content, mime_type=asset.mime_type or "image/png")
        character = Character(
            id=character_id, name=name.strip(), appearance=appearance.strip(),
            voice_style=(voice_style or None), sheet_object_key=key, source="uploaded",
            created_at=self._clock.now(),
        )
        self._repository.add(session, character)
        session.commit()
        return character

    def generate_four_view_sheet(
        self, session: Session, *, character_id: str, seed: int | None = None,
        settings=None, image_edit=None,
    ) -> Character:
        """把人物照片升级成**2×2 四视角母版**（**1 次付费调用**，一次入库、跨项目永久复用）。

        为什么值得花这一次钱：四视角母版当身份锚点比单张照片更稳（正面/侧面/背面都在，
        模型不必自己猜侧脸与背面），生成本身只做一次，之后任何项目选这个人都是 0 额外成本。

        幂等性：原照片会先留一份到 `characters/{id}/source.png`，重跑**仍以原照片为输入**
        （不会"拿上一次的产物再生成"导致越跑越糊）。
        """
        from dataclasses import replace

        from onetake_api.config import get_settings
        from onetake_api.integrations.media.image_utils import pad_image_to_9_16
        from onetake_api.integrations.product_scene.multi_view import (
            generate_multi_view_sheet,
            build_four_view_prompt,
        )

        resolved = settings or get_settings()
        character = self.get_character(session, character_id=character_id)
        current = b"".join(self.storage.read_object(object_key=character.sheet_object_key))
        if not current:
            raise CharacterValidationError("出镜人母版内容为空，无法升级四视角")

        source_key = source_sheet_key(character.id)
        if self.storage.stat_object(object_key=source_key) is None:
            self.storage.put_bytes(object_key=source_key, content=current, mime_type="image/png")
        stored_source = b"".join(self.storage.read_object(object_key=source_key)) or current

        is_mock = bool(getattr(resolved, "mock_providers", False)) or not getattr(resolved, "dashscope_api_key", "")
        if is_mock:
            # 0 成本路径：把原照片确定性拼成 2×2（离线也能验证"入库 + 复用"这条链）
            sheet = _mock_four_view_sheet(pad_image_to_9_16(stored_source))
        else:
            adapter = image_edit
            if adapter is None:
                from onetake_api.integrations.qwen_image_edit.adapter import QwenImageEditAdapter

                adapter = QwenImageEditAdapter(
                    api_key=resolved.dashscope_api_key,
                    endpoint=resolved.image_edit_endpoint,
                    model=resolved.image_edit_model,
                )
            sheet = generate_multi_view_sheet(
                adapter=adapter,
                images=[(pad_image_to_9_16(stored_source), "image/png")],
                prompt=build_four_view_prompt(name=character.name, appearance=character.appearance),
                negative_prompt="字幕、水印、logo、文字、编号、边框、格线以外的装饰、多个人、换脸、美颜过度",
                size=resolved.keyframe_grid_image_size,
                seed=seed,
            )

        updated = replace(
            character,
            sheet_object_key=sheet_key(character.id),
            source="generated",
        )
        self.storage.put_bytes(object_key=updated.sheet_object_key, content=sheet, mime_type="image/png")
        self._repository.update(session, updated)
        session.commit()
        return updated

    def list_characters(self, session: Session) -> list[Character]:
        return self._repository.list_all(session)

    def get_character(self, session: Session, *, character_id: str) -> Character:
        character = self._repository.get(session, character_id)
        if character is None:
            raise CharacterNotFoundError("出镜人不存在")
        return character

    def sheet_url(self, character: Character) -> str | None:
        try:
            return self.storage.create_get_url(object_key=character.sheet_object_key, expires_seconds=SHEET_URL_SECONDS).url
        except Exception:  # noqa: BLE001 - 图丢了就如实返回 None，不给 404 链接
            return None

    @staticmethod
    def fingerprint(character: Character) -> str:
        """母版指纹（供"是否换过人"这类幂等判断用）。"""
        return hashlib.sha256(character.sheet_object_key.encode()).hexdigest()[:16]
