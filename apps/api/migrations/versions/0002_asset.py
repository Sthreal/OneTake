"""create asset schema

Revision ID: 0002_asset
Revises: 0001_project_outbox
Create Date: 2026-09-17
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0002_asset"
down_revision: Union[str, None] = "0001_project_outbox"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS asset")
    op.create_table(
        "assets",
        sa.Column("id", sa.String(length=40), primary_key=True),
        sa.Column("project_id", sa.String(length=40), nullable=False),
        sa.Column("object_key", sa.String(length=500), nullable=False),
        sa.Column("original_filename", sa.String(length=255), nullable=False),
        sa.Column("mime_type", sa.String(length=50), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("width", sa.Integer(), nullable=False),
        sa.Column("height", sa.Integer(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("project_id", "sha256", name="uq_asset_project_sha256"),
        schema="asset",
    )
    op.create_index("ix_asset_project_id", "assets", ["project_id"], schema="asset")


def downgrade() -> None:
    op.drop_index("ix_asset_project_id", table_name="assets", schema="asset")
    op.drop_table("assets", schema="asset")
    op.execute("DROP SCHEMA IF EXISTS asset")