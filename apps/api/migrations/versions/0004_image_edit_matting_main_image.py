"""create image edit matting and main image schemas

Revision ID: 0004_main_image
Revises: 0003_pipeline_recognition_jobs
Create Date: 2026-09-18
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0004_main_image"
down_revision: Union[str, None] = "0003_pipeline_recognition_jobs"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS image_edit")
    op.execute("CREATE SCHEMA IF NOT EXISTS matting")
    op.execute("CREATE SCHEMA IF NOT EXISTS main_image")

    op.create_table(
        "runs",
        sa.Column("id", sa.String(length=40), primary_key=True),
        sa.Column("project_id", sa.String(length=40), nullable=False),
        sa.Column("main_image_version_id", sa.String(length=40), nullable=False),
        sa.Column("source_asset_id", sa.String(length=40), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("provider", sa.String(length=60), nullable=False),
        sa.Column("source_object_key", sa.String(length=500), nullable=False),
        sa.Column("output_object_key", sa.String(length=500), nullable=False),
        sa.Column("source_mime_type", sa.String(length=50), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=True),
        sa.Column("error_code", sa.String(length=80), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        schema="image_edit",
    )
    op.create_index("ix_image_edit_runs_project_id", "runs", ["project_id"], schema="image_edit")
    op.create_index("ix_image_edit_runs_version_id", "runs", ["main_image_version_id"], schema="image_edit")
    op.create_index("ix_image_edit_runs_status", "runs", ["status"], schema="image_edit")

    op.create_table(
        "runs",
        sa.Column("id", sa.String(length=40), primary_key=True),
        sa.Column("project_id", sa.String(length=40), nullable=False),
        sa.Column("main_image_version_id", sa.String(length=40), nullable=False),
        sa.Column("image_edit_run_id", sa.String(length=40), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("provider", sa.String(length=60), nullable=False),
        sa.Column("source_object_key", sa.String(length=500), nullable=False),
        sa.Column("output_object_key", sa.String(length=500), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=True),
        sa.Column("error_code", sa.String(length=80), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        schema="matting",
    )
    op.create_index("ix_matting_runs_project_id", "runs", ["project_id"], schema="matting")
    op.create_index("ix_matting_runs_version_id", "runs", ["main_image_version_id"], schema="matting")
    op.create_index("ix_matting_runs_status", "runs", ["status"], schema="matting")

    op.create_table(
        "versions",
        sa.Column("id", sa.String(length=40), primary_key=True),
        sa.Column("project_id", sa.String(length=40), nullable=False),
        sa.Column("source_asset_id", sa.String(length=40), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("image_edit_run_id", sa.String(length=40), nullable=True),
        sa.Column("matting_run_id", sa.String(length=40), nullable=True),
        sa.Column("transparent_object_key", sa.String(length=500), nullable=True),
        sa.Column("jpg_object_key", sa.String(length=500), nullable=True),
        sa.Column("png_width", sa.Integer(), nullable=True),
        sa.Column("png_height", sa.Integer(), nullable=True),
        sa.Column("jpg_width", sa.Integer(), nullable=True),
        sa.Column("jpg_height", sa.Integer(), nullable=True),
        sa.Column("jpg_size_bytes", sa.Integer(), nullable=True),
        sa.Column("product_ratio", sa.Float(), nullable=True),
        sa.Column("error_code", sa.String(length=80), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        schema="main_image",
    )
    op.create_index("ix_main_image_versions_project_id", "versions", ["project_id"], schema="main_image")
    op.create_index("ix_main_image_versions_status", "versions", ["status"], schema="main_image")


def downgrade() -> None:
    op.drop_index("ix_main_image_versions_status", table_name="versions", schema="main_image")
    op.drop_index("ix_main_image_versions_project_id", table_name="versions", schema="main_image")
    op.drop_table("versions", schema="main_image")
    op.drop_index("ix_matting_runs_status", table_name="runs", schema="matting")
    op.drop_index("ix_matting_runs_version_id", table_name="runs", schema="matting")
    op.drop_index("ix_matting_runs_project_id", table_name="runs", schema="matting")
    op.drop_table("runs", schema="matting")
    op.drop_index("ix_image_edit_runs_status", table_name="runs", schema="image_edit")
    op.drop_index("ix_image_edit_runs_version_id", table_name="runs", schema="image_edit")
    op.drop_index("ix_image_edit_runs_project_id", table_name="runs", schema="image_edit")
    op.drop_table("runs", schema="image_edit")
    op.execute("DROP SCHEMA IF EXISTS main_image")
    op.execute("DROP SCHEMA IF EXISTS matting")
    op.execute("DROP SCHEMA IF EXISTS image_edit")

