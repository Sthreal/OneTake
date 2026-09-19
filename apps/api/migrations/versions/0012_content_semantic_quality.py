"""add semantic content quality fields

Revision ID: 0012_content_semantic_quality
Revises: 0011_content_quality
Create Date: 2026-09-19
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0012_content_semantic_quality"
down_revision: Union[str, None] = "0011_content_quality"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("reports", sa.Column("rule_score", sa.Integer(), nullable=True), schema="content_qa")
    op.add_column("reports", sa.Column("semantic_score", sa.Integer(), nullable=True), schema="content_qa")
    op.add_column("reports", sa.Column("semantic_checks", sa.JSON(), nullable=False, server_default=sa.text("'[]'::json")), schema="content_qa")
    op.add_column("reports", sa.Column("semantic_issues", sa.JSON(), nullable=False, server_default=sa.text("'[]'::json")), schema="content_qa")
    op.alter_column("reports", "semantic_checks", server_default=None, schema="content_qa")
    op.alter_column("reports", "semantic_issues", server_default=None, schema="content_qa")


def downgrade() -> None:
    op.drop_column("reports", "semantic_issues", schema="content_qa")
    op.drop_column("reports", "semantic_checks", schema="content_qa")
    op.drop_column("reports", "semantic_score", schema="content_qa")
    op.drop_column("reports", "rule_score", schema="content_qa")
