"""create video plan and output schemas

Revision ID: 0008_video_plan_output
Revises: 0007_subtitle
Create Date: 2026-09-18
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0008_video_plan_output"
down_revision: Union[str, None] = "0007_subtitle"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS video_plan")
    op.execute("CREATE SCHEMA IF NOT EXISTS output")
    op.create_table(
        "plans",
        sa.Column("id", sa.String(length=40), primary_key=True),
        sa.Column("project_id", sa.String(length=40), nullable=False),
        sa.Column("mode", sa.String(length=20), nullable=False),
        sa.Column("template_id", sa.String(length=40), nullable=True),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("duration_seconds", sa.Float(), nullable=False),
        sa.Column("width", sa.Integer(), nullable=False),
        sa.Column("height", sa.Integer(), nullable=False),
        sa.Column("fps", sa.Integer(), nullable=False),
        sa.Column("voice_enabled", sa.Boolean(), nullable=False),
        sa.Column("subtitle_enabled", sa.Boolean(), nullable=False),
        sa.Column("main_image_object_key", sa.String(length=500), nullable=False),
        sa.Column("voice_object_key", sa.String(length=500), nullable=True),
        sa.Column("subtitle_object_key", sa.String(length=500), nullable=True),
        sa.Column("base_video_object_key", sa.String(length=500), nullable=True),
        sa.Column("final_object_key", sa.String(length=500), nullable=True),
        sa.Column("provider", sa.String(length=60), nullable=False),
        sa.Column("error_code", sa.String(length=80), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        schema="video_plan",
    )
    op.create_index("ix_video_plans_project_id", "plans", ["project_id"], schema="video_plan")
    op.create_index("ix_video_plans_status", "plans", ["status"], schema="video_plan")
    op.create_table(
        "artifacts",
        sa.Column("id", sa.String(length=40), primary_key=True),
        sa.Column("project_id", sa.String(length=40), nullable=False),
        sa.Column("kind", sa.String(length=30), nullable=False),
        sa.Column("object_key", sa.String(length=500), nullable=False),
        sa.Column("mime_type", sa.String(length=80), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("duration_seconds", sa.Float(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        schema="output",
    )
    op.create_index("ix_output_artifacts_project_id", "artifacts", ["project_id"], schema="output")


def downgrade() -> None:
    op.drop_index("ix_output_artifacts_project_id", table_name="artifacts", schema="output")
    op.drop_table("artifacts", schema="output")
    op.drop_index("ix_video_plans_status", table_name="plans", schema="video_plan")
    op.drop_index("ix_video_plans_project_id", table_name="plans", schema="video_plan")
    op.drop_table("plans", schema="video_plan")
    op.execute("DROP SCHEMA IF EXISTS output")
    op.execute("DROP SCHEMA IF EXISTS video_plan")
