"""create voice schema

Revision ID: 0006_voice
Revises: 0005_script
Create Date: 2026-09-18
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0006_voice"
down_revision: Union[str, None] = "0005_script"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS voice")
    op.create_table(
        "runs",
        sa.Column("id", sa.String(length=40), primary_key=True),
        sa.Column("project_id", sa.String(length=40), nullable=False),
        sa.Column("script_version_id", sa.String(length=40), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("provider", sa.String(length=60), nullable=False),
        sa.Column("model", sa.String(length=80), nullable=False),
        sa.Column("voice_id", sa.String(length=80), nullable=False),
        sa.Column("language", sa.String(length=20), nullable=False),
        sa.Column("speed", sa.Float(), nullable=False),
        sa.Column("text", sa.String(length=1200), nullable=False),
        sa.Column("audio_object_key", sa.String(length=500), nullable=True),
        sa.Column("audio_mime_type", sa.String(length=80), nullable=True),
        sa.Column("duration_seconds", sa.Float(), nullable=True),
        sa.Column("timestamps", sa.JSON(), nullable=False),
        sa.Column("error_code", sa.String(length=80), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        schema="voice",
    )
    op.create_index("ix_voice_runs_project_id", "runs", ["project_id"], schema="voice")
    op.create_index("ix_voice_runs_status", "runs", ["status"], schema="voice")


def downgrade() -> None:
    op.drop_index("ix_voice_runs_status", table_name="runs", schema="voice")
    op.drop_index("ix_voice_runs_project_id", table_name="runs", schema="voice")
    op.drop_table("runs", schema="voice")
    op.execute("DROP SCHEMA IF EXISTS voice")
