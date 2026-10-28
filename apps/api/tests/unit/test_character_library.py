"""出镜人库（人物库）单测：0 成本入库、四视角母版升级、跨项目复用与清理保护。

为什么要有它：这条链直接对应用户的问题——"花钱生成的人物能不能沉淀进人物库、下次直接用"。
所以这里同时钉两件事：
1. 母版存在**独立前缀** `characters/`，所以项目媒体清理（`projects/{id}/`）永远碰不到它 → 跨项目复用才成立；
2. 升级四视角是**一次调用**，且重跑**仍以原照片为输入**（不会拿上一次产物再生成、越跑越糊）。
"""
from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from io import BytesIO
from types import SimpleNamespace

import pytest
from PIL import Image

from onetake_api.modules.character.domain import CharacterNotFoundError, CharacterValidationError
from onetake_api.modules.character.public import (
    CharacterPublicService,
    sheet_key,
    source_sheet_key,
)
from onetake_api.modules.asset.domain.model import Asset


def _png(*, width: int = 600, height: int = 900, colour: tuple[int, int, int] = (30, 40, 50)) -> bytes:
    buffer = BytesIO()
    Image.new("RGB", (width, height), colour).save(buffer, format="PNG")
    return buffer.getvalue()


class FakeStorage:
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}
        self.puts: list[str] = []

    def read_object(self, *, object_key: str) -> Iterator[bytes]:
        yield self.objects[object_key]

    def put_bytes(self, *, object_key: str, content: bytes, mime_type: str):
        self.objects[object_key] = content
        self.puts.append(object_key)
        return SimpleNamespace(object_key=object_key)

    def stat_object(self, *, object_key: str):
        return SimpleNamespace(size=len(self.objects[object_key])) if object_key in self.objects else None

    def create_get_url(self, *, object_key: str, expires_seconds: int):
        if object_key not in self.objects:
            raise RuntimeError("missing")
        return SimpleNamespace(url=f"http://storage/{object_key}")


class FakeRepository:
    def __init__(self) -> None:
        self.items: dict[str, object] = {}

    def add(self, _session, character) -> None:
        self.items[character.id] = character

    def update(self, _session, character) -> None:
        self.items[character.id] = character

    def get(self, _session, character_id: str):
        return self.items.get(character_id)

    def list_all(self, _session):
        return list(self.items.values())


class FakeAssets:
    def __init__(self, asset) -> None:
        self._asset = asset

    def get_asset(self, _session, *, asset_id: str):
        return self._asset if self._asset and self._asset.id == asset_id else None


def _asset(*, project_id: str = "prj_1", asset_id: str = "ast_1") -> Asset:
    now = datetime(2026, 10, 15, tzinfo=UTC)
    return Asset(
        id=asset_id, project_id=project_id, object_key=f"projects/{project_id}/assets/{asset_id}.png",
        original_filename="photo.png", mime_type="image/png", size_bytes=10, width=600, height=900,
        sha256=None, status="ready", created_at=now, updated_at=now,
    )


class FakeSession:
    def __init__(self) -> None:
        self.commits = 0

    def commit(self) -> None:
        self.commits += 1


def _service(*, storage: FakeStorage, repository: FakeRepository, asset=None) -> CharacterPublicService:
    service = CharacterPublicService(storage=storage)
    service._repository = repository
    service._assets = FakeAssets(asset)
    return service


def _mock_settings():
    return SimpleNamespace(
        mock_providers=True, dashscope_api_key="", keyframe_grid_image_size="1440*2560",
        image_edit_endpoint="", image_edit_model="qwen-image-edit-plus",
    )


def test_sheet_keys_live_under_the_character_prefix_not_a_project() -> None:
    assert sheet_key("chr_1") == "characters/chr_1/sheet.png"
    assert source_sheet_key("chr_1") == "characters/chr_1/source.png"
    # 项目媒体清理删的是 projects/{id}/ 前缀 —— 这两条键必须落在它之外，跨项目复用才成立
    assert not sheet_key("chr_1").startswith("projects/")
    assert not source_sheet_key("chr_1").startswith("projects/")


def test_create_from_asset_copies_the_photo_into_the_library() -> None:
    storage = FakeStorage()
    storage.objects["projects/prj_1/assets/ast_1.png"] = _png()
    repository = FakeRepository()
    service = _service(storage=storage, repository=repository, asset=_asset())

    character = service.create_from_asset(
        FakeSession(), name=" 小夏 ", appearance=" 短发 ", voice_style="longxiaochun_v2",
        project_id="prj_1", asset_id="ast_1",
    )

    assert character.name == "小夏"
    assert character.source == "uploaded"
    assert character.sheet_object_key == sheet_key(character.id)
    assert storage.puts == [character.sheet_object_key]
    assert storage.objects[character.sheet_object_key] == _png()


def test_create_from_asset_rejects_a_photo_from_another_project() -> None:
    storage = FakeStorage()
    service = _service(storage=storage, repository=FakeRepository(), asset=_asset(project_id="prj_other"))

    with pytest.raises(CharacterValidationError):
        service.create_from_asset(
            FakeSession(), name="小夏", appearance="", voice_style=None,
            project_id="prj_1", asset_id="ast_1",
        )


def test_get_character_raises_when_missing() -> None:
    service = _service(storage=FakeStorage(), repository=FakeRepository())

    with pytest.raises(CharacterNotFoundError):
        service.get_character(FakeSession(), character_id="chr_missing")


def test_sheet_url_is_none_when_the_object_is_gone() -> None:
    service = _service(storage=FakeStorage(), repository=FakeRepository())

    assert service.sheet_url(SimpleNamespace(sheet_object_key="characters/chr_1/sheet.png")) is None


def test_upgrade_to_four_views_keeps_the_original_photo_and_is_repeatable() -> None:
    storage = FakeStorage()
    original = _png(width=600, height=900)
    storage.objects["projects/prj_1/assets/ast_1.png"] = original
    repository = FakeRepository()
    service = _service(storage=storage, repository=repository, asset=_asset())
    session = FakeSession()
    character = service.create_from_asset(
        session, name="小夏", appearance="短发、米色上衣", voice_style=None,
        project_id="prj_1", asset_id="ast_1",
    )

    upgraded = service.generate_four_view_sheet(session, character_id=character.id, settings=_mock_settings())

    assert upgraded.source == "generated"
    assert upgraded.sheet_object_key == sheet_key(character.id)
    # 原照片被留了一份 —— 重跑仍以它为输入
    assert storage.objects[source_sheet_key(character.id)] == original
    first_sheet = storage.objects[sheet_key(character.id)]
    with Image.open(BytesIO(first_sheet)) as sheet:
        assert sheet.width > 600 and sheet.height > 900

    # 第二次升级：仍然以**原照片**为输入 → 结果与第一次逐字节相同（不是拿上一次的产物接着生成）
    again = service.generate_four_view_sheet(session, character_id=character.id, settings=_mock_settings())
    assert again.sheet_object_key == sheet_key(character.id)
    assert storage.objects[source_sheet_key(character.id)] == original
    assert storage.objects[sheet_key(character.id)] == first_sheet


def test_upgrade_reads_the_stored_source_when_the_photo_was_already_kept() -> None:
    storage = FakeStorage()
    repository = FakeRepository()
    service = _service(storage=storage, repository=repository, asset=_asset())
    session = FakeSession()
    storage.objects["projects/prj_1/assets/ast_1.png"] = _png(colour=(10, 200, 10))
    character = service.create_from_asset(
        session, name="小夏", appearance="", voice_style=None, project_id="prj_1", asset_id="ast_1",
    )

    service.generate_four_view_sheet(session, character_id=character.id, settings=_mock_settings())
    first_source = storage.objects[source_sheet_key(character.id)]
    first_sheet = storage.objects[sheet_key(character.id)]
    # 模拟"母版被改过"：把 sheet 换成别的内容，再升级 —— 输入仍必须是留存的原照片
    storage.objects[sheet_key(character.id)] = _png(colour=(1, 1, 1))
    service.generate_four_view_sheet(session, character_id=character.id, settings=_mock_settings())

    assert storage.objects[source_sheet_key(character.id)] == first_source
    assert storage.objects[sheet_key(character.id)] == first_sheet


def test_fingerprint_is_stable_and_short() -> None:
    character = SimpleNamespace(sheet_object_key="characters/chr_1/sheet.png")

    first = CharacterPublicService.fingerprint(character)

    assert first == CharacterPublicService.fingerprint(character)
    assert len(first) == 16
