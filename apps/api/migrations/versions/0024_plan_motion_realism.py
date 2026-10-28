"""add video plan motion realism tier

Revision ID: 0024_plan_motion_realism
Revises: 0023_project_character
Create Date: 2026-10-15
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0024_plan_motion_realism"
down_revision: Union[str, None] = "0023_project_character"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 提示词真实感档：auto / constraints / off。
    # **server_default='off' 就是口径本身**（S5 拍板第 5 条）：已存在的方案一律 off —— 历史项目
    # 重跑时提示词逐字不变、可复现；新项目由 `VideoPlanApplicationService.create_plan` 显式写 auto。
    op.add_column(
        "plans",
        sa.Column("motion_realism", sa.String(length=20), nullable=False, server_default="off"),
        schema="video_plan",
    )
    op.alter_column("plans", "motion_realism", server_default=None, schema="video_plan")


def downgrade() -> None:
    op.drop_column("plans", "motion_realism", schema="video_plan")
