"""create content plan schema

Revision ID: 0010_content_plan
Revises: 0009_output_video_metadata
Create Date: 2026-09-19
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0010_content_plan"
down_revision: Union[str, None] = "0009_output_video_metadata"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS content_plan")
    op.create_table(
        "plans",
        sa.Column("id", sa.String(length=40), primary_key=True),
        sa.Column("project_id", sa.String(length=40), nullable=False),
        sa.Column("script_version_id", sa.String(length=40), nullable=False),
        sa.Column("subtitle_version_id", sa.String(length=40), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("provider", sa.String(length=60), nullable=False),
        sa.Column("model", sa.String(length=80), nullable=False),
        sa.Column("variants", sa.JSON(), nullable=False),
        sa.Column("selected_variant_index", sa.Integer(), nullable=False),
        sa.Column("total_duration_seconds", sa.Float(), nullable=False),
        sa.Column("error_code", sa.String(length=80), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        schema="content_plan",
    )
    op.create_index("ix_content_plan_plans_project_id", "plans", ["project_id"], schema="content_plan")
    op.create_index("ix_content_plan_plans_status", "plans", ["status"], schema="content_plan")


def downgrade() -> None:
    op.drop_index("ix_content_plan_plans_status", table_name="plans", schema="content_plan")
    op.drop_index("ix_content_plan_plans_project_id", table_name="plans", schema="content_plan")
    op.drop_table("plans", schema="content_plan")
    op.execute("DROP SCHEMA IF EXISTS content_plan")
