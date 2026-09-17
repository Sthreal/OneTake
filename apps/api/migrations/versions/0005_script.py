"""create script schema

Revision ID: 0005_script
Revises: 0004_main_image
Create Date: 2026-09-18
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0005_script"
down_revision: Union[str, None] = "0004_main_image"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS script")
    op.create_table(
        "versions",
        sa.Column("id", sa.String(length=40), primary_key=True),
        sa.Column("project_id", sa.String(length=40), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("provider", sa.String(length=60), nullable=False),
        sa.Column("model", sa.String(length=80), nullable=False),
        sa.Column("source_object_key", sa.String(length=500), nullable=False),
        sa.Column("facts", sa.JSON(), nullable=False),
        sa.Column("hook", sa.String(length=240), nullable=False),
        sa.Column("pain_point", sa.String(length=240), nullable=False),
        sa.Column("selling_points", sa.JSON(), nullable=False),
        sa.Column("usage_scenario", sa.String(length=300), nullable=False),
        sa.Column("offer", sa.String(length=160), nullable=True),
        sa.Column("cta", sa.String(length=240), nullable=False),
        sa.Column("full_text", sa.String(length=1200), nullable=False),
        sa.Column("character_count", sa.Integer(), nullable=False),
        sa.Column("estimated_duration_seconds", sa.Float(), nullable=False),
        sa.Column("error_code", sa.String(length=80), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("project_id", "version_number", name="uq_script_project_version"),
        schema="script",
    )
    op.create_index("ix_script_versions_project_id", "versions", ["project_id"], schema="script")
    op.create_index("ix_script_versions_status", "versions", ["status"], schema="script")


def downgrade() -> None:
    op.drop_index("ix_script_versions_status", table_name="versions", schema="script")
    op.drop_index("ix_script_versions_project_id", table_name="versions", schema="script")
    op.drop_table("versions", schema="script")
    op.execute("DROP SCHEMA IF EXISTS script")
