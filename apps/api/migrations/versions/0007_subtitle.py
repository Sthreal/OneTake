"""add subtitle schema and voice subtitle switch

Revision ID: 0007_subtitle
Revises: 0006_voice
Create Date: 2026-09-18
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0007_subtitle"
down_revision: Union[str, None] = "0006_voice"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "runs",
        sa.Column("subtitle_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        schema="voice",
    )
    op.add_column(
        "runs",
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        schema="voice",
    )
    op.execute("CREATE SCHEMA IF NOT EXISTS subtitle")
    op.create_table(
        "versions",
        sa.Column("id", sa.String(length=40), primary_key=True),
        sa.Column("project_id", sa.String(length=40), nullable=False),
        sa.Column("script_version_id", sa.String(length=40), nullable=False),
        sa.Column("voice_run_id", sa.String(length=40), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("language", sa.String(length=20), nullable=False),
        sa.Column("segments", sa.JSON(), nullable=False),
        sa.Column("srt_object_key", sa.String(length=500), nullable=True),
        sa.Column("error_code", sa.String(length=80), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        schema="subtitle",
    )
    op.create_index("ix_subtitle_versions_project_id", "versions", ["project_id"], schema="subtitle")
    op.create_index("ix_subtitle_versions_status", "versions", ["status"], schema="subtitle")


def downgrade() -> None:
    op.drop_index("ix_subtitle_versions_status", table_name="versions", schema="subtitle")
    op.drop_index("ix_subtitle_versions_project_id", table_name="versions", schema="subtitle")
    op.drop_table("versions", schema="subtitle")
    op.execute("DROP SCHEMA IF EXISTS subtitle")
    op.drop_column("runs", "confirmed_at", schema="voice")
    op.drop_column("runs", "subtitle_enabled", schema="voice")
