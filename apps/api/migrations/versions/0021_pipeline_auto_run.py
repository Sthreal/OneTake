"""pipeline auto-run state and cost approvals

Revision ID: 0021_pipeline_auto_run
Revises: 0020_video_plan_gate
Create Date: 2026-10-14

S8+S9+S10 的**唯一一处 schema 变更**（已获批，见 `docs/方案档案.md` S8+S9+S10 第六节）：

- `pipeline.pipeline_runs` 加三列：
  · `stage`：断点续跑的锚点（可空：老数据没有阶段概念，续跑时按 `current_step` 兜底）
  · `auto_run`：这一轮是不是自动链跑的（人/机可区分）
  · `auto_confirmed_stages`：被**系统**自动放行的闸口清单（审计用；人工确认不写这里）
- 新建 `pipeline.cost_approvals`：付费审批记录。**独立成表**而不复用 `gate_acks`，
  因为语义不同（一个是交付门 ack，一个是"批准花钱"）。
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0021_pipeline_auto_run"
down_revision: Union[str, None] = "0020_video_plan_gate"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("pipeline_runs", sa.Column("stage", sa.String(length=40), nullable=True), schema="pipeline")
    op.add_column(
        "pipeline_runs",
        sa.Column("auto_run", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        schema="pipeline",
    )
    op.add_column(
        "pipeline_runs",
        sa.Column("auto_confirmed_stages", sa.JSON(), nullable=False, server_default=sa.text("'[]'::json")),
        schema="pipeline",
    )

    op.create_table(
        "cost_approvals",
        sa.Column("id", sa.String(length=40), primary_key=True),
        sa.Column("project_id", sa.String(length=40), nullable=False),
        sa.Column("plan_id", sa.String(length=40), nullable=False),
        sa.Column("estimated_cny", sa.Float(), nullable=False),
        sa.Column("payload_hash", sa.String(length=64), nullable=False),
        sa.Column("approved_by", sa.String(length=40), nullable=False),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=False),
        schema="pipeline",
    )
    op.create_index(
        "ix_cost_approvals_project_id", "cost_approvals", ["project_id"], schema="pipeline"
    )
    # 审批按 (project, plan, payload_hash) 查 —— 改方案会让 payload_hash 变，旧审批自然失效
    op.create_index(
        "ix_cost_approvals_payload_hash", "cost_approvals", ["plan_id", "payload_hash"], schema="pipeline"
    )


def downgrade() -> None:
    op.drop_index("ix_cost_approvals_payload_hash", table_name="cost_approvals", schema="pipeline")
    op.drop_index("ix_cost_approvals_project_id", table_name="cost_approvals", schema="pipeline")
    op.drop_table("cost_approvals", schema="pipeline")
    op.drop_column("pipeline_runs", "auto_confirmed_stages", schema="pipeline")
    op.drop_column("pipeline_runs", "auto_run", schema="pipeline")
    op.drop_column("pipeline_runs", "stage", schema="pipeline")