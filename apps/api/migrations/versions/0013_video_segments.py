"""create video segment and candidate tables

Revision ID: 0013_video_segments
Revises: 0012_content_semantic_quality
Create Date: 2026-10-11
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0013_video_segments"
down_revision: Union[str, None] = "0012_content_semantic_quality"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "segments",
        sa.Column("id", sa.String(length=40), primary_key=True),
        sa.Column("plan_id", sa.String(length=40), nullable=False),
        sa.Column("project_id", sa.String(length=40), nullable=False),
        sa.Column("order_index", sa.Integer(), nullable=False),
        sa.Column("scene_id", sa.String(length=40), nullable=False),
        sa.Column("start_seconds", sa.Float(), nullable=False),
        sa.Column("end_seconds", sa.Float(), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("accepted_candidate_id", sa.String(length=40), nullable=True),
        sa.Column("last_error", sa.String(length=120), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        schema="video_plan",
    )
    op.create_unique_constraint("uq_video_plan_segments_plan_order", "segments", ["plan_id", "order_index"], schema="video_plan")
    op.create_index("ix_video_plan_segments_project_id", "segments", ["project_id"], schema="video_plan")
    op.create_index("ix_video_plan_segments_plan_id", "segments", ["plan_id"], schema="video_plan")
    op.create_index("ix_video_plan_segments_status", "segments", ["status"], schema="video_plan")

    op.create_table(
        "candidates",
        sa.Column("id", sa.String(length=40), primary_key=True),
        sa.Column("segment_id", sa.String(length=40), nullable=False),
        sa.Column("plan_id", sa.String(length=40), nullable=False),
        sa.Column("project_id", sa.String(length=40), nullable=False),
        sa.Column("order_index", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("provider", sa.String(length=60), nullable=False),
        sa.Column("video_object_key", sa.String(length=500), nullable=True),
        sa.Column("tail_frame_object_key", sa.String(length=500), nullable=True),
        sa.Column("head_frame_object_key", sa.String(length=500), nullable=True),
        sa.Column("anchor_source", sa.String(length=30), nullable=False),
        sa.Column("anchor_candidate_id", sa.String(length=40), nullable=True),
        sa.Column("duration_seconds", sa.Float(), nullable=True),
        sa.Column("width", sa.Integer(), nullable=True),
        sa.Column("height", sa.Integer(), nullable=True),
        sa.Column("fps", sa.Integer(), nullable=True),
        sa.Column("seed", sa.Integer(), nullable=True),
        sa.Column("error_code", sa.String(length=80), nullable=True),
        sa.Column("error_message", sa.String(length=300), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        schema="video_plan",
    )
    op.create_index("ix_video_plan_candidates_segment_id", "candidates", ["segment_id"], schema="video_plan")
    op.create_index("ix_video_plan_candidates_plan_id", "candidates", ["plan_id"], schema="video_plan")
    op.create_index("ix_video_plan_candidates_project_id", "candidates", ["project_id"], schema="video_plan")


def downgrade() -> None:
    op.drop_index("ix_video_plan_candidates_project_id", "candidates", schema="video_plan")
    op.drop_index("ix_video_plan_candidates_plan_id", "candidates", schema="video_plan")
    op.drop_index("ix_video_plan_candidates_segment_id", "candidates", schema="video_plan")
    op.drop_table("candidates", schema="video_plan")
    op.drop_index("ix_video_plan_segments_status", "segments", schema="video_plan")
    op.drop_index("ix_video_plan_segments_plan_id", "segments", schema="video_plan")
    op.drop_index("ix_video_plan_segments_project_id", "segments", schema="video_plan")
    op.drop_constraint("uq_video_plan_segments_plan_order", "segments", schema="video_plan", type_="unique")
    op.drop_table("segments", schema="video_plan")
