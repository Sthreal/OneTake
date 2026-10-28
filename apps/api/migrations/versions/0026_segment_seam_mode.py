"""add per-segment seam mode override

Revision ID: 0026_segment_seam_mode
Revises: 0025_plan_seam_mode
Create Date: 2026-10-15
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0026_segment_seam_mode"
down_revision: Union[str, None] = "0025_plan_seam_mode"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 段级接缝覆盖（S4-③）：**可空** —— NULL 表示「继承方案级 plans.seam_mode」。
    # 已有分段全部为 NULL ⇒ 行为与迁移前完全一致（零变更）。
    op.add_column("segments", sa.Column("seam_mode", sa.String(length=20), nullable=True), schema="video_plan")


def downgrade() -> None:
    op.drop_column("segments", "seam_mode", schema="video_plan")
