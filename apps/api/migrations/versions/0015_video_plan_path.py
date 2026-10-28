"""add video plan generation path

Revision ID: 0015_video_plan_path
Revises: 0014_video_batch
Create Date: 2026-10-14
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0015_video_plan_path"
down_revision: Union[str, None] = "0014_video_batch"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 生成路径：segmented（默认，逐镜关键帧 → 图生视频）| one_shot（多关键帧一次出片）
    # server_default 保证历史数据与 MCP 等旧调用方零改动即可继续工作。
    op.add_column(
        "plans",
        sa.Column("path", sa.String(length=20), nullable=False, server_default="segmented"),
        schema="video_plan",
    )
    op.alter_column("plans", "path", server_default=None, schema="video_plan")


def downgrade() -> None:
    op.drop_column("plans", "path", schema="video_plan")