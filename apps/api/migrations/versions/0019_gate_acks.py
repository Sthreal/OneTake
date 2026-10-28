"""add video gate acknowledgements

Revision ID: 0019_gate_acks
Revises: 0018_content_qa_signals
Create Date: 2026-10-14
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0019_gate_acks"
down_revision: Union[str, None] = "0018_content_qa_signals"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 交付门警告的人工确认记录：warn 项必须逐条确认后才允许下载
    op.create_table(
        "gate_acks",
        sa.Column("id", sa.String(length=40), primary_key=True),
        sa.Column("project_id", sa.String(length=40), nullable=False),
        sa.Column("check_id", sa.String(length=60), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        schema="video_plan",
    )
    op.create_index("ix_video_plan_gate_acks_project_id", "gate_acks", ["project_id"], schema="video_plan")
    op.create_unique_constraint("uq_video_gate_acks_project_check", "gate_acks", ["project_id", "check_id"], schema="video_plan")


def downgrade() -> None:
    op.drop_constraint("uq_video_gate_acks_project_check", "gate_acks", schema="video_plan", type_="unique")
    op.drop_index("ix_video_plan_gate_acks_project_id", table_name="gate_acks", schema="video_plan")
    op.drop_table("gate_acks", schema="video_plan")