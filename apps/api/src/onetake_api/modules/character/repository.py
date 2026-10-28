from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, String, select
from sqlalchemy.orm import Mapped, Session, mapped_column

from onetake_api.modules.character.domain import Character
from onetake_api.platform.database import Base


class CharacterModel(Base):
    __tablename__ = "characters"
    __table_args__ = {"schema": "character"}

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    appearance: Mapped[str] = mapped_column(String(400), nullable=False, default="")
    voice_style: Mapped[str | None] = mapped_column(String(80), nullable=True)
    sheet_object_key: Mapped[str] = mapped_column(String(300), nullable=False)
    source: Mapped[str] = mapped_column(String(20), nullable=False, default="uploaded")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


def _to_domain(model: CharacterModel) -> Character:
    return Character(
        id=model.id, name=model.name, appearance=model.appearance or "",
        voice_style=model.voice_style, sheet_object_key=model.sheet_object_key,
        source=model.source, created_at=model.created_at,
    )


class CharacterRepository:
    def add(self, session: Session, character: Character) -> None:
        session.add(CharacterModel(
            id=character.id, name=character.name, appearance=character.appearance,
            voice_style=character.voice_style, sheet_object_key=character.sheet_object_key,
            source=character.source, created_at=character.created_at,
        ))

    def get(self, session: Session, character_id: str) -> Character | None:
        model = session.get(CharacterModel, character_id)
        return _to_domain(model) if model else None

    def update(self, session: Session, character: Character) -> None:
        """更新已有出镜人（母版升级成四视角后 source/sheet_object_key 会变）。"""
        model = session.get(CharacterModel, character.id)
        if model is None:
            return
        model.name = character.name
        model.appearance = character.appearance
        model.voice_style = character.voice_style
        model.sheet_object_key = character.sheet_object_key
        model.source = character.source

    def list_all(self, session: Session) -> list[Character]:
        models = session.scalars(select(CharacterModel).order_by(CharacterModel.created_at.desc())).all()
        return [_to_domain(model) for model in models]
