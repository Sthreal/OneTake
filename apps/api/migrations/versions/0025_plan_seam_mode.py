"""add video plan seam mode

Revision ID: 0025_plan_seam_mode
Revises: 0024_plan_motion_realism
Create Date: 2026-10-15
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0025_plan_seam_mode"
down_revision: Union[str, None] = "0024_plan_motion_realism"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 接缝模式：pin（钉帧，默认）/ tail（续拍）/ off（各镜独立）。
    # server_default='pin' = S6 之前的行为 → 已有方案零行为变更。
    op.add_column(
        "plans",
        sa.Column("seam_mode", sa.String(length=20), nullable=False, server_default="pin"),
        schema="video_plan",
    )
    op.alter_column("plans", "seam_mode", server_default=None, schema="video_plan")


def downgrade() -> None:
    op.drop_column("plans", "seam_mode", schema="video_plan")
