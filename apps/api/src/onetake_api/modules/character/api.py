"""出镜人库接口（跨项目复用）。

- POST /characters                       用一张已上传的照片建出镜人（0 成本；照片复制到 characters/{id}/sheet.png 永久留存）
- POST /characters/{id}/sheet/generate   把照片升级成 2×2 四视角母版（**1 次付费调用**，mock 时 0 成本）—— 结果永久入库
- GET  /characters                       列出人物库（带母版预览 URL + 升级这一次的价格）
- GET  /characters/{id}                  单个出镜人
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from onetake_api.config import get_settings
from onetake_api.modules.character.public import CharacterPublicService
from onetake_api.platform.request_context import get_request_id
from onetake_api.platform.database import get_session

router = APIRouter(prefix="/api/v1", tags=["characters"])


class CharacterGenerateRequest(BaseModel):
    seed: int | None = None


def _price_value(raw) -> float | None:
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


class CharacterCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    project_id: str = Field(min_length=1, max_length=40)
    asset_id: str = Field(min_length=1, max_length=40)
    appearance: str = Field(default="", max_length=400)
    voice_style: str | None = Field(default=None, max_length=80)


class CharacterData(BaseModel):
    character_id: str
    name: str
    appearance: str
    voice_style: str | None
    source: str
    sheet_url: str | None


class SheetGenerationData(BaseModel):
    """前端在按"升级四视角"之前必须能看到"这一次要不要钱、多少钱"（用户规矩：付费前先点头）。"""

    cny_per_call: float | None = None
    is_mock: bool = False


class CharacterListData(BaseModel):
    characters: list[CharacterData]
    sheet_generation: SheetGenerationData


class CharacterResponse(BaseModel):
    data: CharacterData
    request_id: str


class CharacterListResponse(BaseModel):
    data: CharacterListData
    request_id: str


def _character_data(service: CharacterPublicService, character) -> CharacterData:
    return CharacterData(
        character_id=character.id, name=character.name, appearance=character.appearance,
        voice_style=character.voice_style, source=character.source,
        sheet_url=service.sheet_url(character),
    )


@router.post("/characters", response_model=CharacterResponse, status_code=status.HTTP_201_CREATED)
def create_character(payload: CharacterCreateRequest, session: Session = Depends(get_session)) -> CharacterResponse:
    service = CharacterPublicService()
    character = service.create_from_asset(
        session, name=payload.name, appearance=payload.appearance, voice_style=payload.voice_style,
        project_id=payload.project_id, asset_id=payload.asset_id,
    )
    return CharacterResponse(data=_character_data(service, character), request_id=get_request_id())


def _sheet_generation_data() -> SheetGenerationData:
    settings = get_settings()
    is_mock = bool(settings.mock_providers) or not settings.dashscope_api_key
    return SheetGenerationData(
        cny_per_call=None if is_mock else _price_value(settings.qwen_image_edit_price_per_call),
        is_mock=is_mock,
    )


@router.get("/characters", response_model=CharacterListResponse)
def list_characters(session: Session = Depends(get_session)) -> CharacterListResponse:
    service = CharacterPublicService()
    characters = [ _character_data(service, item) for item in service.list_characters(session) ]
    return CharacterListResponse(
        data=CharacterListData(characters=characters, sheet_generation=_sheet_generation_data()),
        request_id=get_request_id(),
    )


@router.post("/characters/{character_id}/sheet/generate", response_model=CharacterResponse)
def generate_character_sheet(
    character_id: str,
    payload: CharacterGenerateRequest | None = None,
    session: Session = Depends(get_session),
) -> CharacterResponse:
    """把人物照片升级成四视角母版（一次付费调用）。原照片留在 characters/{id}/source.png，重跑仍以它为准。"""
    service = CharacterPublicService()
    character = service.generate_four_view_sheet(
        session,
        character_id=character_id,
        seed=payload.seed if payload else None,
    )
    return CharacterResponse(data=_character_data(service, character), request_id=get_request_id())


@router.get("/characters/{character_id}", response_model=CharacterResponse)
def get_character(character_id: str, session: Session = Depends(get_session)) -> CharacterResponse:
    service = CharacterPublicService()
    return CharacterResponse(
        data=_character_data(service, service.get_character(session, character_id=character_id)),
        request_id=get_request_id(),
    )
