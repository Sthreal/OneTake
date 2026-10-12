"""add video plan batch fields

Revision ID: 0014_video_batch
Revises: 0013_video_segments
Create Date: 2026-10-11
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0014_video_batch"
down_revision: Union[str, None] = "0013_video_segments"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("plans", sa.Column("batch_status", sa.String(length=20), nullable=False, server_default="idle"), schema="video_plan")
    op.add_column("plans", sa.Column("batch_stop_requested", sa.Boolean(), nullable=False, server_default=sa.false()), schema="video_plan")
    op.alter_column("plans", "batch_status", server_default=None, schema="video_plan")
    op.alter_column("plans", "batch_stop_requested", server_default=None, schema="video_plan")


def downgrade() -> None:
    op.drop_column("plans", "batch_stop_requested", schema="video_plan")
    op.drop_column("plans", "batch_status", schema="video_plan")
