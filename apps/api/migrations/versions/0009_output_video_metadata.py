"""add output video metadata

Revision ID: 0009_output_video_metadata
Revises: 0008_video_plan_output
Create Date: 2026-09-18
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0009_output_video_metadata"
down_revision: Union[str, None] = "0008_video_plan_output"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("artifacts", sa.Column("video_width", sa.Integer(), nullable=True), schema="output")
    op.add_column("artifacts", sa.Column("video_height", sa.Integer(), nullable=True), schema="output")
    op.add_column("artifacts", sa.Column("fps", sa.Float(), nullable=True), schema="output")
    op.add_column("artifacts", sa.Column("video_codec", sa.String(length=30), nullable=True), schema="output")
    op.add_column("artifacts", sa.Column("audio_codec", sa.String(length=30), nullable=True), schema="output")


def downgrade() -> None:
    op.drop_column("artifacts", "audio_codec", schema="output")
    op.drop_column("artifacts", "video_codec", schema="output")
    op.drop_column("artifacts", "fps", schema="output")
    op.drop_column("artifacts", "video_height", schema="output")
    op.drop_column("artifacts", "video_width", schema="output")
