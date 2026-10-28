from __future__ import annotations

from sqlalchemy import DateTime, Float, Integer, String, delete, func, select
from sqlalchemy.orm import Mapped, Session, mapped_column

from onetake_api.modules.video_plan.segment_domain import VideoSegment, VideoSegmentCandidate
from onetake_api.platform.database import Base


class VideoSegmentModel(Base):
    __tablename__ = "segments"
    __table_args__ = {"schema": "video_plan"}

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    plan_id: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    project_id: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    order_index: Mapped[int] = mapped_column(Integer, nullable=False)
    scene_id: Mapped[str] = mapped_column(String(40), nullable=False)
    start_seconds: Mapped[float] = mapped_column(Float, nullable=False)
    end_seconds: Mapped[float] = mapped_column(Float, nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    accepted_candidate_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    last_error: Mapped[str | None] = mapped_column(String(120), nullable=True)
    # 段级接缝覆盖（见 migrations/versions/0026_segment_seam_mode.py）；NULL = 继承方案级
    seam_mode: Mapped[str | None] = mapped_column(String(20), nullable=True)
    created_at: Mapped[object] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[object] = mapped_column(DateTime(timezone=True), nullable=False)


class VideoSegmentCandidateModel(Base):
    __tablename__ = "candidates"
    __table_args__ = {"schema": "video_plan"}

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    segment_id: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    plan_id: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    project_id: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    order_index: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    provider: Mapped[str] = mapped_column(String(60), nullable=False)
    video_object_key: Mapped[str | None] = mapped_column(String(500), nullable=True)
    tail_frame_object_key: Mapped[str | None] = mapped_column(String(500), nullable=True)
    head_frame_object_key: Mapped[str | None] = mapped_column(String(500), nullable=True)
    anchor_source: Mapped[str] = mapped_column(String(30), nullable=False)
    anchor_candidate_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    duration_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)
    width: Mapped[int | None] = mapped_column(Integer, nullable=True)
    height: Mapped[int | None] = mapped_column(Integer, nullable=True)
    fps: Mapped[int | None] = mapped_column(Integer, nullable=True)
    seed: Mapped[int | None] = mapped_column(Integer, nullable=True)
    symptom: Mapped[str | None] = mapped_column(String(40), nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    error_message: Mapped[str | None] = mapped_column(String(300), nullable=True)
    created_at: Mapped[object] = mapped_column(DateTime(timezone=True), nullable=False)


def _segment_to_domain(model: VideoSegmentModel, candidates: list[VideoSegmentCandidate] | None = None) -> VideoSegment:
    return VideoSegment(
        id=model.id, plan_id=model.plan_id, project_id=model.project_id, order_index=model.order_index,
        scene_id=model.scene_id, start_seconds=model.start_seconds, end_seconds=model.end_seconds,
        status=model.status, accepted_candidate_id=model.accepted_candidate_id, last_error=model.last_error,
        seam_mode=model.seam_mode,
        created_at=model.created_at, updated_at=model.updated_at, candidates=candidates or [],
    )


def _candidate_to_domain(model: VideoSegmentCandidateModel) -> VideoSegmentCandidate:
    return VideoSegmentCandidate(
        id=model.id, segment_id=model.segment_id, plan_id=model.plan_id, project_id=model.project_id,
        order_index=model.order_index, status=model.status, provider=model.provider,
        anchor_source=model.anchor_source, anchor_candidate_id=model.anchor_candidate_id,
        video_object_key=model.video_object_key, tail_frame_object_key=model.tail_frame_object_key,
        head_frame_object_key=model.head_frame_object_key, duration_seconds=model.duration_seconds,
        width=model.width, height=model.height, fps=model.fps, seed=model.seed, symptom=model.symptom,
        error_code=model.error_code, error_message=model.error_message, created_at=model.created_at,
    )


class VideoSegmentRepository:
    def add_many(self, session: Session, segments: list[VideoSegment]) -> None:
        for segment in segments:
            session.add(VideoSegmentModel(
                id=segment.id, plan_id=segment.plan_id, project_id=segment.project_id,
                order_index=segment.order_index, scene_id=segment.scene_id,
                start_seconds=segment.start_seconds, end_seconds=segment.end_seconds,
                status=segment.status, accepted_candidate_id=segment.accepted_candidate_id,
                last_error=segment.last_error, seam_mode=segment.seam_mode,
                created_at=segment.created_at, updated_at=segment.updated_at,
            ))

    def list_for_plan(self, session: Session, plan_id: str) -> list[VideoSegment]:
        models = session.scalars(
            select(VideoSegmentModel).where(VideoSegmentModel.plan_id == plan_id).order_by(VideoSegmentModel.order_index.asc())
        ).all()
        candidates = VideoSegmentCandidateRepository()
        return [_segment_to_domain(model, candidates.list_for_segment(session, model.id)) for model in models]

    def get(self, session: Session, segment_id: str) -> VideoSegment | None:
        model = session.get(VideoSegmentModel, segment_id)
        return _segment_to_domain(model, VideoSegmentCandidateRepository().list_for_segment(session, model.id)) if model else None

    def effective_seams(self, session: Session, plan_id: str) -> list[str | None]:
        """按分段顺序给出**段级接缝覆盖**（可能含 None）—— 供费用预估按段推演。

        为什么预估一定要读它：接缝模式决定「这一镜有没有尾帧」，而 kf2v / i2v **单价不同** ——
        预估不读它就必然与实际不符（本仓历史上已栽过一次「预估按一种切法、生成按另一种」）。
        """
        models = session.scalars(
            select(VideoSegmentModel).where(VideoSegmentModel.plan_id == plan_id).order_by(VideoSegmentModel.order_index.asc())
        ).all()
        return [model.seam_mode for model in models]

    def update(self, session: Session, segment: VideoSegment) -> None:
        model = session.get(VideoSegmentModel, segment.id)
        if model is None:
            return
        model.status = segment.status
        model.accepted_candidate_id = segment.accepted_candidate_id
        model.last_error = segment.last_error
        model.seam_mode = segment.seam_mode
        model.updated_at = segment.updated_at


class VideoSegmentCandidateRepository:
    def add(self, session: Session, candidate: VideoSegmentCandidate) -> None:
        session.add(VideoSegmentCandidateModel(
            id=candidate.id, segment_id=candidate.segment_id, plan_id=candidate.plan_id,
            project_id=candidate.project_id, order_index=candidate.order_index, status=candidate.status,
            provider=candidate.provider, video_object_key=candidate.video_object_key,
            tail_frame_object_key=candidate.tail_frame_object_key, head_frame_object_key=candidate.head_frame_object_key,
            anchor_source=candidate.anchor_source, anchor_candidate_id=candidate.anchor_candidate_id,
            duration_seconds=candidate.duration_seconds, width=candidate.width, height=candidate.height,
            fps=candidate.fps, seed=candidate.seed, symptom=candidate.symptom, error_code=candidate.error_code,
            error_message=candidate.error_message, created_at=candidate.created_at,
        ))

    def get(self, session: Session, candidate_id: str) -> VideoSegmentCandidate | None:
        model = session.get(VideoSegmentCandidateModel, candidate_id)
        return _candidate_to_domain(model) if model else None

    def list_for_segment(self, session: Session, segment_id: str) -> list[VideoSegmentCandidate]:
        models = session.scalars(
            select(VideoSegmentCandidateModel).where(VideoSegmentCandidateModel.segment_id == segment_id).order_by(VideoSegmentCandidateModel.order_index.asc())
        ).all()
        return [_candidate_to_domain(model) for model in models]

    def next_order_index(self, session: Session, segment_id: str) -> int:
        current = session.scalar(select(func.max(VideoSegmentCandidateModel.order_index)).where(VideoSegmentCandidateModel.segment_id == segment_id))
        return (current or 0) + 1

    def update_status(self, session: Session, candidate_id: str, status: str) -> None:
        model = session.get(VideoSegmentCandidateModel, candidate_id)
        if model is not None:
            model.status = status

    def delete_for_segment(self, session: Session, segment_id: str) -> None:
        session.execute(delete(VideoSegmentCandidateModel).where(VideoSegmentCandidateModel.segment_id == segment_id))
