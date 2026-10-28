"""批次 5 单测：逐镜评分的加权/报告/读取 + VLM 适配器（打桩，不联网）。"""
from __future__ import annotations

import json
from types import SimpleNamespace

import httpx
import pytest

from onetake_api.integrations.qwen_vl_quality.adapter import (
    SEGMENT_QUALITY_DIMENSIONS,
    QwenVlSemanticAdapter,
    QwenVlQualityError,
)
from onetake_api.modules.content_qa import segment_quality
from onetake_api.modules.content_qa.segment_quality import (
    LOW_SCORE_THRESHOLD,
    SegmentQualityReport,
    build_report,
    missing_dimensions,
    overall_score,
    read_report,
)


class _FakeStorage:
    def __init__(self, objects: dict[str, bytes] | None = None) -> None:
        self.objects = objects or {}
        self.written: dict[str, bytes] = {}

    def put_bytes(self, *, object_key: str, content: bytes, mime_type: str) -> None:
        self.written[object_key] = content

    def read_object(self, *, object_key: str):
        return [self.objects[object_key]]


# ---- 加权与报告 ----


def test_overall_score_follows_declared_weights() -> None:
    assert overall_score({dimension: 100 for dimension in SEGMENT_QUALITY_DIMENSIONS}) == 100
    assert overall_score({"product_fidelity": 100}) == 30          # 只有商品保真满分 → 权重 30
    assert overall_score({}) == 0
    # 权重表必须覆盖全部维度（否则可以靠"少报一个维度"刷分）
    assert set(segment_quality.SEGMENT_QUALITY_WEIGHTS) == set(SEGMENT_QUALITY_DIMENSIONS)


def test_missing_dimensions_is_explicit() -> None:
    assert missing_dimensions({"visual": 80}) == [
        "temporal", "script_fidelity", "product_fidelity", "continuity"
    ]


def test_report_round_trip_and_low_scores() -> None:
    report = build_report(
        project_id="prj_1", plan_id="vid_1", provider="qwen-vl-plus-quality", model="qwen3-vl-plus", calls=2,
        segments=[
            ("seg_1", 1, "scene_1", {dimension: 90 for dimension in SEGMENT_QUALITY_DIMENSIONS}, [], [0.5]),
            ("seg_2", 2, "scene_2", {**{dimension: 90 for dimension in SEGMENT_QUALITY_DIMENSIONS}, "product_fidelity": 20},
             ["第 1.20 秒：商品包装文字变形"], [1.2]),
        ],
    )
    assert report.segments[0].overall == 90
    assert report.low_scores and report.low_scores[0].segment_id == "seg_2"
    assert report.issues and "第 2 镜" in report.issues[0]
    restored = SegmentQualityReport.from_dict(json.loads(json.dumps(report.to_dict())))
    assert restored.segments[1].evidence_seconds == [1.2]
    assert restored.low_scores[0].overall == report.low_scores[0].overall


def test_write_then_read_report(monkeypatch) -> None:
    storage = _FakeStorage()
    report = build_report(
        project_id="prj_1", plan_id="vid_1", provider="p", model="m", calls=1,
        segments=[("seg_1", 1, "scene_1", {dimension: 80 for dimension in SEGMENT_QUALITY_DIMENSIONS}, [], [])],
    )
    key = segment_quality.write_report(storage, report)
    assert key == "projects/prj_1/quality/segment-scores.json"
    monkeypatch.setattr(segment_quality, "get_object_storage", lambda: storage)
    storage.objects[key] = storage.written[key]
    restored = read_report("prj_1")
    assert restored is not None and restored.segments[0].overall == 80


def test_read_report_swallows_missing_and_broken(monkeypatch) -> None:
    assert read_report("prj_none", storage=_FakeStorage()) is None
    broken = _FakeStorage({"projects/prj_x/quality/segment-scores.json": b"not json"})
    assert read_report("prj_x", storage=broken) is None


# ---- 适配器（打桩）----


def _adapter(handler) -> QwenVlSemanticAdapter:
    return QwenVlSemanticAdapter(
        api_key="k", endpoint="https://dashscope.example/vl", model="qwen3-vl-plus", frame_count=5,
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )


def _segment_video() -> bytes:
    import subprocess
    import tempfile
    from pathlib import Path
    from imageio_ffmpeg import get_ffmpeg_exe

    with tempfile.TemporaryDirectory() as temp_dir:
        path = Path(temp_dir) / "seg.mp4"
        subprocess.run(
            [get_ffmpeg_exe(), "-y", "-f", "lavfi", "-i", "testsrc=size=160x280:rate=12:duration=1.2",
             "-c:v", "libx264", "-pix_fmt", "yuv420p", str(path)],
            check=True, capture_output=True,
        )
        return path.read_bytes()


def _product_png() -> bytes:
    import io

    from PIL import Image

    buffer = io.BytesIO()
    Image.new("RGB", (120, 200), (200, 60, 60)).save(buffer, format="PNG")
    return buffer.getvalue()


def test_score_segment_sends_product_plus_frames_and_parses_strict_json() -> None:
    seen: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content.decode("utf-8"))
        seen.append(payload)
        content = payload["input"]["messages"][0]["content"]
        images = [item for item in content if "image" in item]
        assert len(images) == 6                                    # 1 张商品主图 + 5 张抽帧
        text = next(item["text"] for item in content if "text" in item)
        assert "第 2 镜（共 3 镜）" in text and "这一镜的文案" in text
        assert "秒" in text and text.count(".") >= 5               # 提示词里给了抽帧时刻表（证据只能从这里选）
        # 实测：默认温度下同一批内容的分数会抖动到 50/90/0 → 逐镜评分必须贪心解码才有可比性
        assert payload["parameters"]["temperature"] == 0.0
        return httpx.Response(200, json={
            "output": {"choices": [{"message": {"content": json.dumps({
                "scores": {"visual": 88, "temporal": 76, "script_fidelity": 80, "product_fidelity": 66, "continuity": 90},
                "issues": ["第 0.40 秒：包装文字略糊"],
                "evidence_seconds": [0.4],
            })}}]},
            # DashScope 会回真实用量：我们要把它留住，用来校准"每次调用多少钱"
            "usage": {"input_tokens": 12345, "output_tokens": 210, "total_tokens": 12555},
        })

    adapter = _adapter(handler)
    result = adapter.score_segment(
        video_bytes=_segment_video(), duration_seconds=1.2, product_image_bytes=_product_png(),
        script_excerpt="涂上立刻显气色", shot_prompt="近景展示膏体", order_index=2, total_segments=3,
    )
    assert result.scores["product_fidelity"] == 66
    assert result.issues == ["第 0.40 秒：包装文字略糊"] and result.evidence_seconds == [0.4]
    assert seen and seen[0]["model"] == "qwen3-vl-plus"
    assert result.usage == {"input_tokens": 12_345, "output_tokens": 210, "total_tokens": 12_555}   # 真实用量被留住


def test_score_segment_rejects_missing_dimensions() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"output": {"choices": [{"message": {"content": json.dumps({
            "scores": {"visual": 90}, "issues": [], "evidence_seconds": [],
        })}}]}})

    with pytest.raises(QwenVlQualityError):
        _adapter(handler).score_segment(
            video_bytes=_segment_video(), duration_seconds=1.2, product_image_bytes=_product_png(),
            script_excerpt="x", shot_prompt="y", order_index=1, total_segments=1,
        )


def test_gate_segment_quality_check_levels() -> None:
    from onetake_api.modules.video_plan.gate import segment_quality_check

    clean = build_report(
        project_id="prj", plan_id="vid", provider="p", model="m", calls=1,
        segments=[("seg", 1, "scene", {dimension: 95 for dimension in SEGMENT_QUALITY_DIMENSIONS}, [], [])],
    )
    check = segment_quality_check(report=clean)
    assert check is not None and check.id == "segment_quality" and check.level == "ok"

    low = build_report(
        project_id="prj", plan_id="vid", provider="p", model="m", calls=1,
        segments=[("seg", 1, "scene", {**{d: 95 for d in SEGMENT_QUALITY_DIMENSIONS}, "visual": 10},
                   ["第 0.50 秒：画面糊"], [0.5])],
    )
    check = segment_quality_check(report=low)
    assert check is not None and check.level == "warn" and "第 1 镜" in check.message
    assert segment_quality_check(report=None) is None             # 没跑过 ≠ 通过
    assert LOW_SCORE_THRESHOLD == 70


def test_segment_quality_reports_missing_media_as_409_not_500(monkeypatch) -> None:
    """真机踩到的：旧项目的素材被媒体清理任务删了 → `read_object` 抛 S3 错误 → 原来是 500。

    正确行为是**明确 409**（"素材已不存在/请换项目"），让人看得懂、也让前端能区分。
    """
    from types import SimpleNamespace

    from onetake_api.modules.content_qa.service import (
        ContentQaApplicationService,
        SegmentQualityMediaMissingError,
    )

    class _MissingStorage:
        def read_object(self, *, object_key: str):
            raise RuntimeError("NoSuchKey: " + object_key)

    class _FakeAdapter:
        provider_name = "fake"
        model = "fake-1"

        def score_segment(self, **_kwargs):                       # pragma: no cover - 不该被调用
            raise AssertionError("素材都读不到，不该去调模型")

    service = ContentQaApplicationService(storage=_MissingStorage())
    service._plans = SimpleNamespace(latest=lambda session, project_id: None)
    service._projects = SimpleNamespace(get_project=lambda session, **kwargs: None)   # 本用例不碰 DB

    plan = SimpleNamespace(id="vid_x", main_image_object_key="projects/p/main.png")
    monkeypatch.setattr(
        "onetake_api.modules.video_plan.public.VideoPlanPublicService.latest",
        lambda self, session, project_id: SimpleNamespace(plan=plan),
    )
    candidate = SimpleNamespace(id="can_1", video_object_key="projects/p/video/seg-1.mp4", duration_seconds=3.0)
    segment = SimpleNamespace(
        id="seg_1", scene_id="scene_1", order_index=1, duration_seconds=3.0,
        accepted_candidate_id="can_1", candidates=[candidate],
    )
    monkeypatch.setattr(
        "onetake_api.modules.video_plan.segment_repository.VideoSegmentRepository.list_for_plan",
        lambda self, session, plan_id: [segment],
    )

    with pytest.raises(SegmentQualityMediaMissingError) as error:
        service.score_segments(None, project_id="prj_x", adapter=_FakeAdapter())
    assert error.value.http_status == 409 and "主图" in str(error.value)