from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, Float, Integer, String, select
from sqlalchemy.orm import Mapped, Session, mapped_column

from onetake_api.modules.video_plan.keyframe_domain import (
    KEYFRAME_ACCEPTED,
    KEYFRAME_REJECTED,
    VideoKeyframeCandidate,
)
from onetake_api.platform.database import Base


class VideoKeyframeCandidateModel(Base):
    __tablename__ = "keyframe_candidates"
    __table_args__ = {"schema": "video_plan"}

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    project_id: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    content_plan_id: Mapped[str] = mapped_column(String(40), nullable=False)
    scene_id: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    order_index: Mapped[int] = mapped_column(Integer, nullable=False)
    mode: Mapped[str] = mapped_column(String(20), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    provider: Mapped[str] = mapped_column(String(60), nullable=False)
    seed: Mapped[int | None] = mapped_column(Integer, nullable=True)
    image_object_key: Mapped[str | None] = mapped_column(String(500), nullable=True)
    width: Mapped[int | None] = mapped_column(Integer, nullable=True)
    height: Mapped[int | None] = mapped_column(Integer, nullable=True)
    product_match: Mapped[float | None] = mapped_column(Float, nullable=True)
    text_intact: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    issues: Mapped[list | None] = mapped_column(JSON, nullable=True)
    fallback: Mapped[str | None] = mapped_column(String(20), nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


def _to_domain(model: VideoKeyframeCandidateModel) -> VideoKeyframeCandidate:
    return VideoKeyframeCandidate(
        id=model.id, project_id=model.project_id, content_plan_id=model.content_plan_id,
        scene_id=model.scene_id, order_index=model.order_index, mode=model.mode, status=model.status,
        provider=model.provider, created_at=model.created_at, seed=model.seed,
        image_object_key=model.image_object_key, width=model.width, height=model.height,
        product_match=model.product_match, text_intact=model.text_intact,
        issues=list(model.issues or []), fallback=model.fallback, error_code=model.error_code,
    )


class VideoKeyframeCandidateRepository:
    def add(self, session: Session, candidate: VideoKeyframeCandidate) -> None:
        session.add(VideoKeyframeCandidateModel(
            id=candidate.id, project_id=candidate.project_id, content_plan_id=candidate.content_plan_id,
            scene_id=candidate.scene_id, order_index=candidate.order_index, mode=candidate.mode,
            status=candidate.status, provider=candidate.provider, seed=candidate.seed,
            image_object_key=candidate.image_object_key, width=candidate.width, height=candidate.height,
            product_match=candidate.product_match, text_intact=candidate.text_intact,
            issues=list(candidate.issues), fallback=candidate.fallback, error_code=candidate.error_code,
            created_at=candidate.created_at,
        ))

    def list_for_project(self, session: Session, project_id: str) -> list[VideoKeyframeCandidate]:
        models = session.scalars(
            select(VideoKeyframeCandidateModel)
            .where(VideoKeyframeCandidateModel.project_id == project_id)
            .order_by(VideoKeyframeCandidateModel.order_index, VideoKeyframeCandidateModel.created_at)
        ).all()
        return [_to_domain(model) for model in models]

    def get(self, session: Session, keyframe_id: str) -> VideoKeyframeCandidate | None:
        model = session.get(VideoKeyframeCandidateModel, keyframe_id)
        return _to_domain(model) if model else None

    def accepted_for_scene(self, session: Session, *, project_id: str, scene_id: str) -> VideoKeyframeCandidate | None:
        model = session.scalar(
            select(VideoKeyframeCandidateModel)
            .where(
                VideoKeyframeCandidateModel.project_id == project_id,
                VideoKeyframeCandidateModel.scene_id == scene_id,
                VideoKeyframeCandidateModel.status == KEYFRAME_ACCEPTED,
            )
            .order_by(VideoKeyframeCandidateModel.created_at.desc())
        )
        return _to_domain(model) if model else None

    def update_status(self, session: Session, keyframe_id: str, status: str) -> None:
        model = session.get(VideoKeyframeCandidateModel, keyframe_id)
        if model is not None:
            model.status = status

    def supersede_pending(self, session: Session, *, project_id: str, scene_id: str) -> None:
        """新候选生成后，把同一分镜下仍处于 ready 的旧候选标记为 rejected（候选不覆盖，保留可回溯）。"""
        models = session.scalars(
            select(VideoKeyframeCandidateModel).where(
                VideoKeyframeCandidateModel.project_id == project_id,
                VideoKeyframeCandidateModel.scene_id == scene_id,
                VideoKeyframeCandidateModel.status == "ready",
            )
        ).all()
        for model in models:
            model.status = KEYFRAME_REJECTED

    def reject_all_for_scene(self, session: Session, *, project_id: str, scene_id: str, except_id: str) -> None:
        models = session.scalars(
            select(VideoKeyframeCandidateModel).where(
                VideoKeyframeCandidateModel.project_id == project_id,
                VideoKeyframeCandidateModel.scene_id == scene_id,
                VideoKeyframeCandidateModel.id != except_id,
                VideoKeyframeCandidateModel.status.in_([KEYFRAME_ACCEPTED, "ready"]),
            )
        ).all()
        for model in models:
            model.status = KEYFRAME_REJECTED