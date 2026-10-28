"""add video plan gate report

Revision ID: 0020_video_plan_gate
Revises: 0019_gate_acks
Create Date: 2026-10-14
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0020_video_plan_gate"
down_revision: Union[str, None] = "0019_gate_acks"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 交付门结论随成片一起落库：GET /video/gate 与下载放行都以它为唯一依据
    op.add_column("plans", sa.Column("gate_report", sa.JSON(), nullable=True), schema="video_plan")


def downgrade() -> None:
    op.drop_column("plans", "gate_report", schema="video_plan")