"""add per-plan compose overrides (caption style / bgm)

Revision ID: 0027_plan_compose_overrides
Revises: 0026_segment_seam_mode
Create Date: 2026-10-15
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0027_plan_compose_overrides"
down_revision: Union[str, None] = "0026_segment_seam_mode"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 方案级「合成旋钮」（S4-④a）：字幕样式 / BGM 开关 / BGM 强度。
    # **全部可空 = 跟全局配置** ⇒ 已有方案行为零变更（这正是「不猜、不突变」的口径）。
    op.add_column("plans", sa.Column("caption_style", sa.String(length=20), nullable=True), schema="video_plan")
    op.add_column("plans", sa.Column("bgm_enabled", sa.Boolean(), nullable=True), schema="video_plan")
    op.add_column("plans", sa.Column("bgm_gain_db", sa.Float(), nullable=True), schema="video_plan")


def downgrade() -> None:
    op.drop_column("plans", "bgm_gain_db", schema="video_plan")
    op.drop_column("plans", "bgm_enabled", schema="video_plan")
    op.drop_column("plans", "caption_style", schema="video_plan")
