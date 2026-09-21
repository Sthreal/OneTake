import json

import httpx
import pytest

from onetake_api.integrations.wan_s2v.adapter import WanS2VAdapter, WanS2VError

VIDEO_URL = "https://cdn.example/avatar.mp4"
TASK_URL = "/api/v1/tasks/s2v_task_1"


def _adapter(
    handler,
    *,
    dimensions: tuple[int, int] = (720, 1280),
    poll_timeout_seconds: float = 1.0,
    image_url: str = "https://cdn.example/avatar.png",
    audio_url: str = "https://cdn.example/voice.wav",
) -> WanS2VAdapter:
    client = httpx.Client(transport=httpx.MockTransport(handler))
    return WanS2VAdapter(
        api_key="key",
        model="wan2.2-s2v",
        resolution="720P",
        max_seconds=30,
        upload_image=lambda _content: image_url,
        upload_audio=lambda _content: audio_url,
        inspect_dimensions=lambda _content: dimensions,
        poll_interval_seconds=0,
        poll_timeout_seconds=poll_timeout_seconds,
        client=client,
    )


def test_wan_s2v_adapter_submits_image_and_audio_and_downloads() -> None:
    requests: list[httpx.Request] = []
    statuses = iter(["RUNNING", "SUCCEEDED"])

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.method == "POST":
            return httpx.Response(200, json={"output": {"task_id": "s2v_task_1"}})
        if request.url.path == TASK_URL:
            status = next(statuses)
            output = {"task_status": status}
            if status == "SUCCEEDED":
                output["results"] = {"video_url": VIDEO_URL}
            return httpx.Response(200, json={"output": output})
        if str(request.url) == VIDEO_URL:
            return httpx.Response(200, content=b"avatar-video")
        raise AssertionError(f"unexpected request: {request.method} {request.url}")

    adapter = _adapter(
        handler,
        image_url="oss://dashscope/avatar.png",
        audio_url="oss://dashscope/voice.wav",
    )
    video, task_id = adapter.generate(
        image_bytes=b"avatar-image",
        audio_bytes=b"voice-audio",
        prompt="正面对镜口播",
        duration_seconds=18,
    )

    assert video == b"avatar-video"
    assert task_id == "s2v_task_1"
    submit = json.loads(requests[0].content)
    assert requests[0].headers["X-DashScope-Async"] == "enable"
    assert requests[0].headers["X-DashScope-OssResourceResolve"] == "enable"
    assert submit["model"] == "wan2.2-s2v"
    assert submit["input"] == {
        "image_url": "oss://dashscope/avatar.png",
        "audio_url": "oss://dashscope/voice.wav",
        "prompt": "正面对镜口播",
    }
    assert submit["parameters"]["resolution"] == "720P"
    assert submit["parameters"]["duration"] == 18


def test_wan_s2v_adapter_rejects_missing_audio() -> None:
    adapter = _adapter(lambda _request: httpx.Response(500))
    with pytest.raises(WanS2VError, match="输入音频为空"):
        adapter.generate(image_bytes=b"avatar-image", audio_bytes=b"", prompt="口播", duration_seconds=18)


def test_wan_s2v_adapter_rejects_non_vertical_output() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(200, json={"output": {"task_id": "s2v_task_1"}})
        if request.url.path == TASK_URL:
            return httpx.Response(
                200,
                json={"output": {"task_status": "SUCCEEDED", "results": {"video_url": VIDEO_URL}}},
            )
        return httpx.Response(200, content=b"avatar-video")

    with pytest.raises(WanS2VError, match="输出比例错误"):
        _adapter(handler, dimensions=(960, 960)).generate(
            image_bytes=b"avatar-image",
            audio_bytes=b"voice-audio",
            prompt="口播",
            duration_seconds=18,
        )


def test_wan_s2v_adapter_surfaces_task_failure() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(200, json={"output": {"task_id": "s2v_task_1"}})
        if request.url.path == TASK_URL:
            return httpx.Response(
                200,
                json={"output": {"task_status": "FAILED", "message": "bad audio"}},
            )
        raise AssertionError(f"unexpected request: {request.url}")

    with pytest.raises(WanS2VError, match="任务状态 FAILED：bad audio"):
        _adapter(handler).generate(
            image_bytes=b"avatar-image",
            audio_bytes=b"voice-audio",
            prompt="口播",
            duration_seconds=18,
        )


def test_wan_s2v_adapter_surfaces_submit_error() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"code": "InvalidParameter", "message": "bad image"})

    with pytest.raises(WanS2VError, match="提交失败：InvalidParameter"):
        _adapter(handler).generate(
            image_bytes=b"avatar-image",
            audio_bytes=b"voice-audio",
            prompt="口播",
            duration_seconds=18,
        )


def test_wan_s2v_adapter_times_out_without_polling() -> None:
    methods: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        methods.append(request.method)
        return httpx.Response(200, json={"output": {"task_id": "s2v_task_1"}})

    with pytest.raises(WanS2VError, match="任务超时"):
        _adapter(handler, poll_timeout_seconds=0).generate(
            image_bytes=b"avatar-image",
            audio_bytes=b"voice-audio",
            prompt="口播",
            duration_seconds=18,
        )
    assert methods == ["POST"]