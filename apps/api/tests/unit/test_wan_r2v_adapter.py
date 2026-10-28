"""Phase 3 单测：r2v 适配器（请求形态、媒体数组、轮询、截断与失败处理）。"""
from __future__ import annotations

import pytest

from onetake_api.integrations.wan_r2v.adapter import MAX_MEDIA_ITEMS, WanR2VAdapter, WanR2VError


class _FakeResponse:
    def __init__(self, payload: dict | None = None, content: bytes = b"") -> None:
        self._payload = payload or {}
        self.content = content

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return self._payload


class _FakeClient:
    def __init__(self, *, statuses: list[str], video: bytes = b"fake-mp4") -> None:
        self.posted: dict | None = None
        self.task_queries = 0
        self._statuses = list(statuses)
        self._video = video

    def post(self, url, headers=None, json=None, **_kwargs):  # noqa: A002 - 对齐 httpx 签名
        self.posted = {"url": url, "headers": headers, "json": json}
        return _FakeResponse({"output": {"task_id": "task-1", "task_status": "PENDING"}})

    def get(self, url, headers=None, timeout=None, **_kwargs):
        if "/tasks/" in url:
            self.task_queries += 1
            status = self._statuses.pop(0) if self._statuses else "SUCCEEDED"
            output: dict = {"task_status": status}
            if status.upper() in {"SUCCEEDED", "SUCCESS"}:
                output["video_url"] = "https://example.com/film.mp4"
            return _FakeResponse({"output": output})
        return _FakeResponse(content=self._video)


def _adapter(client: _FakeClient, uploads: list[tuple[str, bytes]], **overrides) -> WanR2VAdapter:
    def _upload(content: bytes, name: str) -> str:
        uploads.append((name, content))
        return f"oss://bucket/{name}"

    options = {
        "api_key": "test-key",
        "model": "wan2.7-r2v",
        "upload_media": _upload,
        "client": client,
        "poll_interval_seconds": 0.001,
        "poll_timeout_seconds": 5.0,
        "prepare_image": lambda content: b"flat:" + content,
        "inspect_dimensions": lambda _content: (1080, 1920),
    }
    options.update(overrides)
    return WanR2VAdapter(**options)


def test_generate_film_builds_media_array_and_flattens_inputs() -> None:
    uploads: list[tuple[str, bytes]] = []
    client = _FakeClient(statuses=["PENDING", "SUCCEEDED"])
    adapter = _adapter(client, uploads)

    video, task_id = adapter.generate_film(
        first_frame_bytes=b"first", reference_images=[b"r1", b"r2"], prompt="时间码分镜", duration_seconds=13
    )

    assert video == b"fake-mp4"
    assert task_id == "task-1"
    # 透明通道处理：上传的必须是 flatten 之后的内容
    assert [name for name, _ in uploads] == ["r2v-first.png", "r2v-ref-2.png", "r2v-ref-3.png"]
    assert uploads[0][1] == b"flat:first"

    assert client.posted is not None
    body = client.posted["json"]
    assert body["model"] == "wan2.7-r2v"
    media = body["input"]["media"]
    assert media[0]["type"] == "first_frame"
    assert media[0]["url"].startswith("oss://")
    assert [item["type"] for item in media] == ["first_frame", "reference_image", "reference_image"]
    parameters = body["parameters"]
    assert parameters["duration"] == 13
    assert parameters["ratio"] == "9:16"
    assert parameters["watermark"] is False
    assert client.posted["headers"]["X-DashScope-Async"] == "enable"
    assert client.task_queries == 2  # 先 PENDING 再 SUCCEEDED


def test_generate_film_truncates_extra_references() -> None:
    uploads: list[tuple[str, bytes]] = []
    client = _FakeClient(statuses=["SUCCEEDED"])
    adapter = _adapter(client, uploads)

    adapter.generate_film(
        first_frame_bytes=b"first", reference_images=[b"1", b"2", b"3", b"4", b"5", b"6"],
        prompt="p", duration_seconds=5,
    )

    media = client.posted["json"]["input"]["media"]
    assert len(media) == MAX_MEDIA_ITEMS


def test_generate_film_clamps_duration_to_limit() -> None:
    uploads: list[tuple[str, bytes]] = []
    client = _FakeClient(statuses=["SUCCEEDED"])
    adapter = _adapter(client, uploads, max_seconds=15)

    adapter.generate_film(first_frame_bytes=b"first", reference_images=[], prompt="p", duration_seconds=40)

    assert client.posted["json"]["parameters"]["duration"] == 15


def test_generate_film_raises_on_failed_task() -> None:
    uploads: list[tuple[str, bytes]] = []
    client = _FakeClient(statuses=["FAILED"])
    adapter = _adapter(client, uploads)

    with pytest.raises(WanR2VError):
        adapter.generate_film(first_frame_bytes=b"first", reference_images=[], prompt="p", duration_seconds=5)


def test_generate_film_requires_key_model_and_frames() -> None:
    uploads: list[tuple[str, bytes]] = []
    client = _FakeClient(statuses=["SUCCEEDED"])

    with pytest.raises(WanR2VError):
        _adapter(client, uploads, api_key="").generate_film(
            first_frame_bytes=b"first", reference_images=[], prompt="p", duration_seconds=5
        )
    with pytest.raises(WanR2VError):
        _adapter(client, uploads, model="").generate_film(
            first_frame_bytes=b"first", reference_images=[], prompt="p", duration_seconds=5
        )
    with pytest.raises(WanR2VError):
        _adapter(client, uploads).generate_film(
            first_frame_bytes=b"", reference_images=[], prompt="p", duration_seconds=5
        )


def test_generate_film_rejects_wrong_output_size() -> None:
    uploads: list[tuple[str, bytes]] = []
    client = _FakeClient(statuses=["SUCCEEDED"])
    adapter = _adapter(
        client, uploads, expected_width=1080, expected_height=1920,
        inspect_dimensions=lambda _content: (720, 1280),
    )

    with pytest.raises(WanR2VError):
        adapter.generate_film(first_frame_bytes=b"first", reference_images=[], prompt="p", duration_seconds=5)