"""交付门 + 合规 的端到端契约测试（Phase 5）。

覆盖真实链路：合规扫描命中违禁词 → 交付门产出 warn → 确认后放行下载。
"""
from __future__ import annotations

from datetime import UTC, datetime

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from onetake_api.modules.project.public import ProjectPublicService
from onetake_api.modules.subtitle.domain import SUBTITLE_CONFIRMED, SubtitleVersion
from onetake_api.modules.subtitle.repository import SubtitleRepository


def _seed_subtitle(session: Session, *, product_name: str, text: str) -> str:
    project = ProjectPublicService().create_project(session, product_name=product_name, product_note=None)
    now = datetime.now(UTC)
    SubtitleRepository().add(session, SubtitleVersion(
        "sub_gate", project.id, "scr_gate", "voi_gate", SUBTITLE_CONFIRMED, True, "zh",
        [{"index": 1, "text": text, "start": 0, "end": 5}],
        f"projects/{project.id}/subtitle.srt", None, now, now, now, now,
    ))
    session.flush()
    return project.id


def test_gate_reports_banned_words_and_unlocks_after_ack(
    client: TestClient, db_session: Session
) -> None:
    project_id = _seed_subtitle(db_session, product_name="违禁词", text="全网最低价，绝对最好用")

    compliance = client.get(f"/api/v1/projects/{project_id}/compliance").json()["data"]
    assert compliance["evaluated"] is True
    words = [hit["word"] for hit in compliance["banned_words"]]
    assert "全网最低" in words and "最好" in words
    assert any(hit["where"] == "subtitle" for hit in compliance["banned_words"])

    gate = client.get(f"/api/v1/projects/{project_id}/video/gate").json()["data"]
    assert gate["status"] == "warn"
    assert gate["download_allowed"] is False
    ad_check = next(check for check in gate["checks"] if check["id"] == "ad_words")
    assert ad_check["level"] == "warn"
    assert "全网最低" in ad_check["message"]

    ack = client.post(f"/api/v1/projects/{project_id}/video/gate/ack", json={"check_ids": ["ad_words"]})
    assert ack.status_code == 200
    assert "ad_words" in ack.json()["data"]["acknowledged"]


def test_compliance_is_clean_for_neutral_copy(client: TestClient, db_session: Session) -> None:
    project_id = _seed_subtitle(db_session, product_name="中性文案", text="容量合适，日常通勤都能用")
    compliance = client.get(f"/api/v1/projects/{project_id}/compliance").json()["data"]
    assert compliance["banned_words"] == []
    assert compliance["platform_warnings"] == []