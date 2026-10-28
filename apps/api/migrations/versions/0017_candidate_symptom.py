"""add segment candidate symptom

Revision ID: 0017_candidate_symptom
Revises: 0016_video_keyframes
Create Date: 2026-10-14
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0017_candidate_symptom"
down_revision: Union[str, None] = "0016_video_keyframes"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 症状式返修：记录"这一次只改了什么"，便于追溯与对比
    op.add_column("candidates", sa.Column("symptom", sa.String(length=40), nullable=True), schema="video_plan")


def downgrade() -> None:
    op.drop_column("candidates", "symptom", schema="video_plan")