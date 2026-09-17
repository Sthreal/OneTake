"""create project and outbox schemas

Revision ID: 0001_project_outbox
Revises:
Create Date: 2026-09-17
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0001_project_outbox"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS project")
    op.execute("CREATE SCHEMA IF NOT EXISTS outbox")

    op.create_table(
        "projects",
        sa.Column("id", sa.String(length=40), primary_key=True),
        sa.Column("product_name", sa.String(length=80), nullable=False),
        sa.Column("product_note", sa.String(length=240), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        schema="project",
    )

    op.create_table(
        "outbox_events",
        sa.Column("id", sa.String(length=40), primary_key=True),
        sa.Column("event_name", sa.String(length=100), nullable=False),
        sa.Column("event_version", sa.Integer(), nullable=False),
        sa.Column("aggregate_type", sa.String(length=50), nullable=False),
        sa.Column("aggregate_id", sa.String(length=64), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        schema="outbox",
    )
    op.create_index(
        "ix_outbox_events_status_available_at",
        "outbox_events",
        ["status", "available_at"],
        schema="outbox",
    )


def downgrade() -> None:
    op.drop_index(
        "ix_outbox_events_status_available_at",
        table_name="outbox_events",
        schema="outbox",
    )
    op.drop_table("outbox_events", schema="outbox")
    op.drop_table("projects", schema="project")
    op.execute("DROP SCHEMA IF EXISTS outbox")
    op.execute("DROP SCHEMA IF EXISTS project")