"""add content qa objective signals

Revision ID: 0018_content_qa_signals
Revises: 0017_candidate_symptom
Create Date: 2026-10-14
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0018_content_qa_signals"
down_revision: Union[str, None] = "0017_candidate_symptom"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 客观质检信号（黑帧/静音/冻结/响度/时长）：随报告一起落库，交付门与前端都从这里读
    op.add_column("reports", sa.Column("signals", sa.JSON(), nullable=True), schema="content_qa")


def downgrade() -> None:
    op.drop_column("reports", "signals", schema="content_qa")