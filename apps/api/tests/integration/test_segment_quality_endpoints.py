"""批次 5 集成测：逐镜评分端点（费用闸 / 报告落库 / 交付门 warn）。

VLM 适配器被打桩（**不联网、不花钱**）：这里验证的是"接线与纪律"，
真实评分效果要等用户点头后才能真跑一次付费调用。
"""
from __future__ import annotations

from dataclasses import dataclass

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from onetake_api.config import get_settings
from onetake_api.integrations.qwen_vl_quality.adapter import SEGMENT_QUALITY_DIMENSIONS, SegmentScoreResult
from onetake_api.integrations.object_storage.public import ObjectStoragePublicService
from onetake_api.modules.video_plan.segment_service import VideoSegmentApplicationService

from test_video_stock_fill import _seed, _service


@dataclass
class _FakeVlm:
    provider_name = "fake-vlm"
    model = "fake-vlm-1"
    scores: dict

    def score_segment(self, **_kwargs) -> SegmentScoreResult:
        return SegmentScoreResult(scores=dict(self.scores), issues=[], evidence_seconds=[0.5])


def _env(monkeypatch, *, enabled: bool) -> None:
    monkeypatch.setenv("MOCK_PROVIDERS", "true")
    monkeypatch.setenv("PRODUCT_SCENE_ENABLED", "true")
    monkeypatch.setenv("VIDEO_CONTINUITY_ENABLED", "true")
    monkeypatch.setenv("STOCK_ENABLED", "false")
    monkeypatch.setenv("SEGMENT_QUALITY_ENABLED", "true" if enabled else "false")
    get_settings.cache_clear()


def _accepted_segment(db_session: Session, storage: ObjectStoragePublicService, name: str) -> str:
    """造一个"已采用分段"的项目（MOCK_PROVIDERS=true → 生成免费）。"""
    project_id, _plan = _seed(db_session, storage, name)
    calls: list[bytes] = []
    service = _service(storage, calls)
    segments = service.materialize_segments(db_session, project_id=project_id)
    target = next(item for item in segments if item.scene_id == "scene_1")
    service.generate_candidate(db_session, project_id=project_id, segment_id=target.id, seed=7)
    refreshed = service.materialize_segments(db_session, project_id=project_id)
    target = next(item for item in refreshed if item.scene_id == "scene_1")
    candidate = target.candidates[-1]
    service.accept_candidate(db_session, project_id=project_id, candidate_id=candidate.id)
    return project_id


def test_segment_quality_runs_through_cost_gate_and_persists_report(
    client: TestClient, db_session: Session, object_storage: ObjectStoragePublicService, monkeypatch
) -> None:
    _env(monkeypatch, enabled=True)
    project_id = _accepted_segment(db_session, object_storage, "逐镜评分")

    gate_calls: list[dict] = []
    # 注：MOCK_PROVIDERS=true 时预估是免费的 → 内层闸会**主动跳过**（既有语义"免费不设闸"），
    # 所以这里盯的是**端点是否经过费用闸这一步**（VideoPlanApplicationService 的包装），而不是内层是否真的拦。
    monkeypatch.setattr(
        "onetake_api.modules.video_plan.service.VideoPlanApplicationService.require_cost_approval",
        lambda self, session, *, project_id, plan_id, **kwargs: gate_calls.append(
            {"project_id": project_id, "plan_id": plan_id}
        ),
    )
    monkeypatch.setattr(
        "onetake_api.modules.content_qa.service._build_segment_quality_adapter",
        lambda settings: _FakeVlm(scores={dimension: 92 for dimension in SEGMENT_QUALITY_DIMENSIONS}),
    )

    response = client.post(f"/api/v1/projects/{project_id}/content-quality/segments")
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["calls"] == 1 and data["provider"] == "fake-vlm", data["segments"]
    assert data["segments"][0]["overall"] == 92 and data["segments"][0]["order_index"] == 1
    assert gate_calls and gate_calls[0]["project_id"] == project_id        # 付费闸被调用过

    again = client.get(f"/api/v1/projects/{project_id}/content-quality/segments")
    assert again.status_code == 200 and again.json()["data"]["segments"][0]["overall"] == 92

    gate = client.get(f"/api/v1/projects/{project_id}/video/gate").json()["data"]
    check = next(item for item in gate["checks"] if item["id"] == "segment_quality")
    assert check["level"] == "ok", check


def test_segment_quality_warn_when_scores_are_low(
    client: TestClient, db_session: Session, object_storage: ObjectStoragePublicService, monkeypatch
) -> None:
    _env(monkeypatch, enabled=True)
    project_id = _accepted_segment(db_session, object_storage, "逐镜评分低分")
    monkeypatch.setattr(
        "onetake_api.modules.video_plan.service.VideoPlanApplicationService.require_cost_approval",
        lambda self, session, *, project_id, plan_id, **kwargs: None,
    )
    low = {dimension: 95 for dimension in SEGMENT_QUALITY_DIMENSIONS}
    low["product_fidelity"] = 10                                            # 商品保真崩了
    low["visual"] = 20                                                      # 叠加画面问题 → 加权总分 51（< 70）
    monkeypatch.setattr(
        "onetake_api.modules.content_qa.service._build_segment_quality_adapter",
        lambda settings: _FakeVlm(scores=low),
    )
    assert client.post(f"/api/v1/projects/{project_id}/content-quality/segments").status_code == 200

    gate = client.get(f"/api/v1/projects/{project_id}/video/gate").json()["data"]
    check = next(item for item in gate["checks"] if item["id"] == "segment_quality")
    assert check["level"] == "warn" and "第 1 镜" in check["message"]
    # warn 的既有语义：逐条确认后才允许下载（这里断言它**没有**被当成 fail 阻断）
    assert gate["status"] == "warn" and gate["download_allowed"] is False
    # 把**所有** warn 都确认掉（这个种子项目还缺质检报告等其它 warn），再看是否放行
    warn_ids = [item["id"] for item in gate["checks"] if item["level"] == "warn"]
    assert "segment_quality" in warn_ids
    acked = client.post(f"/api/v1/projects/{project_id}/video/gate/ack", json={"check_ids": warn_ids})
    assert acked.status_code == 200
    assert acked.json()["data"]["download_allowed"] is True
    assert "segment_quality" in acked.json()["data"]["acknowledged"]


def test_segment_quality_disabled_by_default(
    client: TestClient, db_session: Session, object_storage: ObjectStoragePublicService, monkeypatch
) -> None:
    _env(monkeypatch, enabled=False)
    project_id = _accepted_segment(db_session, object_storage, "逐镜评分未启用")
    response = client.post(f"/api/v1/projects/{project_id}/content-quality/segments")
    assert response.status_code == 409 and "SEGMENT_QUALITY_DISABLED" in response.text
    assert client.get(f"/api/v1/projects/{project_id}/content-quality/segments").json()["data"] is None


def test_segment_quality_surfaces_gate_error(
    client: TestClient, db_session: Session, object_storage: ObjectStoragePublicService, monkeypatch
) -> None:
    """费用闸拒绝时，端点必须把拒绝原样带出来（不能偷偷跑完再报成功）。"""
    from onetake_api.modules.pipeline.public import CostApprovalRequiredError

    _env(monkeypatch, enabled=True)
    project_id = _accepted_segment(db_session, object_storage, "逐镜评分被闸")

    def _blocked(self, session, *, project_id, plan_id, **kwargs):
        raise CostApprovalRequiredError("费用未审批")

    # 拦在端点真正调用的那一层（免费预估时内层会跳过，所以盯包装层才有效）
    monkeypatch.setattr(
        "onetake_api.modules.video_plan.service.VideoPlanApplicationService.require_cost_approval", _blocked
    )
    response = client.post(f"/api/v1/projects/{project_id}/content-quality/segments")
    assert response.status_code >= 400 and "费用未审批" in response.text