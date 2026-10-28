"""付费审批记录的仓储（S8 的硬约束落点）。

**为什么不复用 `gate_acks`**：那个是"交付门 ack"（成片能不能交），这个是"批准花钱"。
把两者塞进一张表会让"下载被拦"和"钱没批"用同一个字段表达 —— 排障与审计都会含混。

**审批与预估绑定**：查审批时按 `(project_id, plan_id, payload_hash)` 三元组查。
`payload_hash` 由"方案 + 关键参数 + 当次预估结果"算出（见 orchestrator），
所以用户改了方案之后，旧审批自然查不到 —— 不会出现"用 5 元的预估批了 50 元的方案"。
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Float, String, select
from sqlalchemy.orm import Mapped, Session, mapped_column

from onetake_api.modules.pipeline.domain import CostApproval
from onetake_api.platform.database import Base


class CostApprovalModel(Base):
    __tablename__ = "cost_approvals"
    __table_args__ = {"schema": "pipeline"}

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    project_id: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    plan_id: Mapped[str] = mapped_column(String(40), nullable=False)
    estimated_cny: Mapped[float] = mapped_column(Float, nullable=False)
    payload_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    approved_by: Mapped[str] = mapped_column(String(40), nullable=False)
    approved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


def _to_domain(model: CostApprovalModel) -> CostApproval:
    return CostApproval(
        id=model.id,
        project_id=model.project_id,
        plan_id=model.plan_id,
        estimated_cny=model.estimated_cny,
        payload_hash=model.payload_hash,
        approved_by=model.approved_by,
        approved_at=model.approved_at,
    )


class CostApprovalRepository:
    def add(self, session: Session, approval: CostApproval) -> None:
        session.add(CostApprovalModel(
            id=approval.id,
            project_id=approval.project_id,
            plan_id=approval.plan_id,
            estimated_cny=approval.estimated_cny,
            payload_hash=approval.payload_hash,
            approved_by=approval.approved_by,
            approved_at=approval.approved_at,
        ))

    def find(
        self, session: Session, *, project_id: str, plan_id: str, payload_hash: str
    ) -> CostApproval | None:
        """按"这份方案的这份预估"查审批。查不到即未获批。"""
        model = session.scalar(
            select(CostApprovalModel)
            .where(
                CostApprovalModel.project_id == project_id,
                CostApprovalModel.plan_id == plan_id,
                CostApprovalModel.payload_hash == payload_hash,
            )
            .order_by(CostApprovalModel.approved_at.desc())
        )
        return _to_domain(model) if model else None

    def list_for_project(self, session: Session, project_id: str) -> list[CostApproval]:
        models = session.scalars(
            select(CostApprovalModel)
            .where(CostApprovalModel.project_id == project_id)
            .order_by(CostApprovalModel.approved_at.desc())
        ).all()
        return [_to_domain(model) for model in models]