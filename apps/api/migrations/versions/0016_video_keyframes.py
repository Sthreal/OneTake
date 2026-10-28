"""add video keyframe candidates

Revision ID: 0016_video_keyframes
Revises: 0015_video_plan_path
Create Date: 2026-10-14
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0016_video_keyframes"
down_revision: Union[str, None] = "0015_video_plan_path"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "keyframe_candidates",
        sa.Column("id", sa.String(length=40), primary_key=True),
        sa.Column("project_id", sa.String(length=40), nullable=False),
        sa.Column("content_plan_id", sa.String(length=40), nullable=False),
        sa.Column("scene_id", sa.String(length=40), nullable=False),
        sa.Column("order_index", sa.Integer(), nullable=False),
        sa.Column("mode", sa.String(length=20), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("provider", sa.String(length=60), nullable=False),
        sa.Column("seed", sa.Integer(), nullable=True),
        sa.Column("image_object_key", sa.String(length=500), nullable=True),
        sa.Column("width", sa.Integer(), nullable=True),
        sa.Column("height", sa.Integer(), nullable=True),
        sa.Column("product_match", sa.Float(), nullable=True),
        sa.Column("text_intact", sa.Boolean(), nullable=True),
        sa.Column("issues", sa.JSON(), nullable=True),
        sa.Column("fallback", sa.String(length=20), nullable=True),
        sa.Column("error_code", sa.String(length=80), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        schema="video_plan",
    )
    op.create_index("ix_video_plan_keyframe_candidates_project_id", "keyframe_candidates", ["project_id"], schema="video_plan")
    op.create_index("ix_video_plan_keyframe_candidates_scene_id", "keyframe_candidates", ["scene_id"], schema="video_plan")
    op.create_index("ix_video_plan_keyframe_candidates_status", "keyframe_candidates", ["status"], schema="video_plan")


def downgrade() -> None:
    op.drop_index("ix_video_plan_keyframe_candidates_status", table_name="keyframe_candidates", schema="video_plan")
    op.drop_index("ix_video_plan_keyframe_candidates_scene_id", table_name="keyframe_candidates", schema="video_plan")
    op.drop_index("ix_video_plan_keyframe_candidates_project_id", table_name="keyframe_candidates", schema="video_plan")
    op.drop_table("keyframe_candidates", schema="video_plan")