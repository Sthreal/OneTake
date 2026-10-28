"""project.character_id: 项目引用出镜人（人物库）

Revision ID: 0023_project_character
Revises: 0022_characters
Create Date: 2026-10-15

给 project.projects 加一列 character_id（可空）：项目"选用哪个出镜人"。
出镜人母版本身存在 character 库（独立前缀 characters/{id}/sheet.png），这里只存引用。
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0023_project_character"
down_revision: Union[str, None] = "0022_characters"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("projects", sa.Column("character_id", sa.String(length=40), nullable=True), schema="project")


def downgrade() -> None:
    op.drop_column("projects", "character_id", schema="project")
