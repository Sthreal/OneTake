"""create pipeline recognition and job schemas

Revision ID: 0003_pipeline_recognition_jobs
Revises: 0002_asset
Create Date: 2026-09-17
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0003_pipeline_recognition_jobs"
down_revision: Union[str, None] = "0002_asset"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS pipeline")
    op.execute("CREATE SCHEMA IF NOT EXISTS recognition")
    op.execute("CREATE SCHEMA IF NOT EXISTS job")

    op.create_table(
        "pipeline_runs",
        sa.Column("id", sa.String(length=40), primary_key=True),
        sa.Column("project_id", sa.String(length=40), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("current_step", sa.Integer(), nullable=False),
        sa.Column("state_version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        schema="pipeline",
    )
    op.create_index("ix_pipeline_runs_project_id", "pipeline_runs", ["project_id"], schema="pipeline")

    op.create_table(
        "runs",
        sa.Column("id", sa.String(length=40), primary_key=True),
        sa.Column("project_id", sa.String(length=40), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("input_hash", sa.String(length=64), nullable=False),
        sa.Column("selected_asset_id", sa.String(length=40), nullable=True),
        sa.Column("selected_candidate_id", sa.String(length=40), nullable=True),
        sa.Column("error_code", sa.String(length=80), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        schema="recognition",
    )
    op.create_index("ix_recognition_runs_project_id", "runs", ["project_id"], schema="recognition")

    op.create_table(
        "candidates",
        sa.Column("id", sa.String(length=40), primary_key=True),
        sa.Column("run_id", sa.String(length=40), nullable=False),
        sa.Column("asset_id", sa.String(length=40), nullable=False),
        sa.Column("label", sa.String(length=120), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("reason", sa.String(length=240), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        schema="recognition",
    )
    op.create_index("ix_recognition_candidates_run_id", "candidates", ["run_id"], schema="recognition")

    op.create_table(
        "jobs",
        sa.Column("id", sa.String(length=40), primary_key=True),
        sa.Column("project_id", sa.String(length=40), nullable=False),
        sa.Column("pipeline_run_id", sa.String(length=40), nullable=False),
        sa.Column("reference_id", sa.String(length=40), nullable=False),
        sa.Column("job_type", sa.String(length=50), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("idempotency_key", sa.String(length=120), nullable=False),
        sa.Column("provider", sa.String(length=40), nullable=False),
        sa.Column("input_hash", sa.String(length=64), nullable=False),
        sa.Column("error_code", sa.String(length=80), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        schema="job",
    )
    op.create_index("ix_jobs_project_id", "jobs", ["project_id"], schema="job")
    op.create_index("ix_jobs_status", "jobs", ["status"], schema="job")


def downgrade() -> None:
    op.drop_index("ix_jobs_status", table_name="jobs", schema="job")
    op.drop_index("ix_jobs_project_id", table_name="jobs", schema="job")
    op.drop_table("jobs", schema="job")
    op.drop_index("ix_recognition_candidates_run_id", table_name="candidates", schema="recognition")
    op.drop_table("candidates", schema="recognition")
    op.drop_index("ix_recognition_runs_project_id", table_name="runs", schema="recognition")
    op.drop_table("runs", schema="recognition")
    op.drop_index("ix_pipeline_runs_project_id", table_name="pipeline_runs", schema="pipeline")
    op.drop_table("pipeline_runs", schema="pipeline")
    op.execute("DROP SCHEMA IF EXISTS job")
    op.execute("DROP SCHEMA IF EXISTS recognition")
    op.execute("DROP SCHEMA IF EXISTS pipeline")
