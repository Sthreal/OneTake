import httpx
import pytest

from onetake_api.integrations.wan_s2v.adapter import WanS2VAdapter, WanS2VError


class FakeVideoSynthesis:
    calls: list[dict] = []
    wait_response = None

    @classmethod
    def async_call(cls, **kwargs):
        cls.calls.append(kwargs)
        return type("Response", (), {"status_code": 200, "output": type("Output", (), {"task_id": "s2v_task_1"})()})()

    @classmethod
    def wait(cls, **_kwargs):
        if cls.wait_response is not None:
            return cls.wait_response
        return type(
            "Response",
            (),
            {
                "status_code": 200,
                "output": type("Output", (), {"video_url": "https://cdn.example/avatar.mp4", "task_status": "SUCCEEDED"})(),
            },
        )()


def _client() -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == "https://cdn.example/avatar.mp4"
        return httpx.Response(200, content=b"avatar-video")

    return httpx.Client(transport=httpx.MockTransport(handler))


def _adapter(*, dimensions: tuple[int, int] = (720, 1280)) -> WanS2VAdapter:
    return WanS2VAdapter(
        api_key="key",
        model="wan2.2-s2v",
        resolution="720P",
        max_seconds=30,
        upload_image=lambda _content: "https://cdn.example/avatar.png",
        upload_audio=lambda _content: "https://cdn.example/voice.wav",
        video_synthesis=FakeVideoSynthesis,
        inspect_dimensions=lambda _content: dimensions,
        client=_client(),
    )


def test_wan_s2v_adapter_submits_image_and_audio_and_downloads() -> None:
    FakeVideoSynthesis.calls.clear()
    FakeVideoSynthesis.wait_response = None
    adapter = _adapter()

    video, task_id = adapter.generate(
        image_bytes=b"avatar-image",
        audio_bytes=b"voice-audio",
        prompt="正面对镜口播",
        duration_seconds=18,
    )

    assert video == b"avatar-video"
    assert task_id == "s2v_task_1"
    call = FakeVideoSynthesis.calls[0]
    assert call["img_url"] == "https://cdn.example/avatar.png"
    assert call["audio_url"] == "https://cdn.example/voice.wav"
    assert call["resolution"] == "720P"
    assert call["duration"] == 18


def test_wan_s2v_adapter_rejects_missing_audio() -> None:
    with pytest.raises(WanS2VError, match="输入音频为空"):
        _adapter().generate(image_bytes=b"avatar-image", audio_bytes=b"", prompt="口播", duration_seconds=18)


def test_wan_s2v_adapter_rejects_non_vertical_output() -> None:
    FakeVideoSynthesis.wait_response = None
    with pytest.raises(WanS2VError, match="输出比例错误"):
        _adapter(dimensions=(960, 960)).generate(
            image_bytes=b"avatar-image",
            audio_bytes=b"voice-audio",
            prompt="口播",
            duration_seconds=18,
        )


def test_wan_s2v_adapter_surfaces_task_failure() -> None:
    FakeVideoSynthesis.wait_response = type(
        "Response",
        (),
        {
            "status_code": 200,
            "output": type("Output", (), {"task_status": "FAILED", "message": "bad audio"})(),
        },
    )()
    try:
        with pytest.raises(WanS2VError, match="任务状态"):
            _adapter().generate(
                image_bytes=b"avatar-image",
                audio_bytes=b"voice-audio",
                prompt="口播",
                duration_seconds=18,
            )
    finally:
        FakeVideoSynthesis.wait_response = None