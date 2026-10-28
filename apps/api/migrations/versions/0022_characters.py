"""characters: 出镜人库（跨项目复用）

Revision ID: 0022_characters
Revises: 0021_pipeline_auto_run
Create Date: 2026-10-15

新建 schema `character` + 表 `character.characters`：出镜人母版（人物照片/四视角）**一次沉淀、
跨项目复用**。母版图存对象存储的独立前缀 `characters/{id}/sheet.png`，不挂任何项目 →
项目的媒体清理不得动该前缀（见 modules/character/domain.py 的边界说明）。
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0022_characters"
down_revision: Union[str, None] = "0021_pipeline_auto_run"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS character")
    op.create_table(
        "characters",
        sa.Column("id", sa.String(length=40), primary_key=True),
        sa.Column("name", sa.String(length=80), nullable=False),
        sa.Column("appearance", sa.String(length=400), nullable=False, server_default=""),
        sa.Column("voice_style", sa.String(length=80), nullable=True),
        sa.Column("sheet_object_key", sa.String(length=300), nullable=False),
        sa.Column("source", sa.String(length=20), nullable=False, server_default="uploaded"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        schema="character",
    )


def downgrade() -> None:
    op.drop_table("characters", schema="character")
    op.execute("DROP SCHEMA IF EXISTS character")
