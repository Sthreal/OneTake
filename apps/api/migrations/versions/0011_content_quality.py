"""create content quality schema

Revision ID: 0011_content_quality
Revises: 0010_content_plan
Create Date: 2026-09-19
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0011_content_quality"
down_revision: Union[str, None] = "0010_content_plan"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS content_qa")
    op.create_table(
        "reports",
        sa.Column("id", sa.String(length=40), primary_key=True),
        sa.Column("project_id", sa.String(length=40), nullable=False),
        sa.Column("plan_id", sa.String(length=40), nullable=False),
        sa.Column("video_plan_id", sa.String(length=40), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("score", sa.Integer(), nullable=False),
        sa.Column("passed", sa.Boolean(), nullable=False),
        sa.Column("checks", sa.JSON(), nullable=False),
        sa.Column("critical_failures", sa.JSON(), nullable=False),
        sa.Column("provider", sa.String(length=60), nullable=False),
        sa.Column("model", sa.String(length=80), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        schema="content_qa",
    )
    op.create_index("ix_content_qa_reports_project_id", "reports", ["project_id"], schema="content_qa")
    op.create_index("ix_content_qa_reports_status", "reports", ["status"], schema="content_qa")


def downgrade() -> None:
    op.drop_index("ix_content_qa_reports_status", table_name="reports", schema="content_qa")
    op.drop_index("ix_content_qa_reports_project_id", table_name="reports", schema="content_qa")
    op.drop_table("reports", schema="content_qa")
    op.execute("DROP SCHEMA IF EXISTS content_qa")
