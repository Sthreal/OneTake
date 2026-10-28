"""交付门警告确认记录（Phase 5）。"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, String, delete, select
from sqlalchemy.orm import Mapped, Session, mapped_column

from onetake_api.platform.database import Base


class GateAckModel(Base):
    __tablename__ = "gate_acks"
    __table_args__ = {"schema": "video_plan"}

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    project_id: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    check_id: Mapped[str] = mapped_column(String(60), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class GateAckRepository:
    def list_for_project(self, session: Session, project_id: str) -> list[str]:
        models = session.scalars(
            select(GateAckModel).where(GateAckModel.project_id == project_id).order_by(GateAckModel.created_at)
        ).all()
        return [model.check_id for model in models]

    def add(self, session: Session, *, ack_id: str, project_id: str, check_id: str, created_at: datetime) -> None:
        existing = session.scalar(
            select(GateAckModel).where(GateAckModel.project_id == project_id, GateAckModel.check_id == check_id)
        )
        if existing is not None:
            return
        session.add(GateAckModel(id=ack_id, project_id=project_id, check_id=check_id, created_at=created_at))

    def clear_for_project(self, session: Session, project_id: str) -> None:
        """重新生成成片后，旧的确认记录必须失效（否则等于默认放行新片子）。"""
        session.execute(delete(GateAckModel).where(GateAckModel.project_id == project_id))