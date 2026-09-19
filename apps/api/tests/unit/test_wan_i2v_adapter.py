import httpx

from onetake_api.integrations.wan_i2v.adapter import WanI2VAdapter


class FakeVideoSynthesis:
    @staticmethod
    def async_call(**kwargs):
        assert kwargs['resolution'] == '720P'
        assert kwargs['duration'] == 5
        assert kwargs['ratio'] == '9:16'
        return type('Response', (), {'status_code': 200, 'output': type('Output', (), {'task_id': 'task_1'})()})()

    @staticmethod
    def wait(**_kwargs):
        return type('Response', (), {'status_code': 200, 'output': type('Output', (), {'video_url': 'https://cdn.example/video.mp4', 'task_status': 'SUCCEEDED'})()})()


def test_wan_i2v_adapter_submits_polls_and_downloads(monkeypatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == 'https://cdn.example/video.mp4'
        return httpx.Response(200, content=b'generated-video')

    adapter = WanI2VAdapter(
        api_key='key',
        model='wan2.6-i2v',
        resolution='720P',
        max_seconds=5,
        upload_image=lambda _content: 'https://cdn.example/product.png',
        video_synthesis=FakeVideoSynthesis,
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    video, task_id = adapter.generate(image_bytes=b'image', prompt='商品保持原样', duration_seconds=8)
    assert video == b'generated-video'
    assert task_id == 'task_1'
