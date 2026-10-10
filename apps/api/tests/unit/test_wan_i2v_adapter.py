import httpx
import pytest
from PIL import Image
from io import BytesIO

from onetake_api.integrations.wan_i2v.adapter import WanI2VAdapter, WanI2VError


class FakeVideoSynthesis:
    calls: list[dict] = []

    @classmethod
    def async_call(cls, **kwargs):
        cls.calls.append(kwargs)
        return type('Response', (), {'status_code': 200, 'output': type('Output', (), {'task_id': 'task_1'})()})()

    @staticmethod
    def wait(**_kwargs):
        return type('Response', (), {'status_code': 200, 'output': type('Output', (), {'video_url': 'https://cdn.example/video.mp4', 'task_status': 'SUCCEEDED'})()})()


def _client() -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == 'https://cdn.example/video.mp4'
        return httpx.Response(200, content=b'generated-video')

    return httpx.Client(transport=httpx.MockTransport(handler))


def _adapter(*, resolution: str, dimensions: tuple[int, int], prepared: bytes = b'prepared-image') -> WanI2VAdapter:
    return WanI2VAdapter(
        api_key='key',
        model='wan2.6-i2v',
        resolution=resolution,
        max_seconds=5,
        upload_image=lambda content: 'https://cdn.example/product.png',
        prepare_image=lambda _content: prepared,
        video_synthesis=FakeVideoSynthesis,
        inspect_dimensions=lambda _content: dimensions,
        client=_client(),
    )


def test_wan_i2v_adapter_requests_vertical_output_and_downloads() -> None:
    FakeVideoSynthesis.calls.clear()
    adapter = _adapter(resolution='720P', dimensions=(720, 1280))
    video, task_id = adapter.generate(image_bytes=b'image', prompt='商品保持原样', duration_seconds=8, negative_prompt='商品, 包装, 文字')

    assert video == b'generated-video'
    assert task_id == 'task_1'
    call = FakeVideoSynthesis.calls[0]
    assert call['resolution'] == '720P'
    assert call['duration'] == 5
    assert 'size' not in call
    assert 'ratio' not in call
    assert call['negative_prompt'] == '商品, 包装, 文字'


def test_wan_i2v_adapter_requests_1080p_vertical() -> None:
    FakeVideoSynthesis.calls.clear()
    adapter = _adapter(resolution='1080P', dimensions=(1080, 1920))
    adapter.generate(image_bytes=b'image', prompt='商品保持原样', duration_seconds=5)

    assert FakeVideoSynthesis.calls[0]['resolution'] == '1080P'


def test_wan_i2v_adapter_rejects_non_vertical_output() -> None:
    adapter = _adapter(resolution='720P', dimensions=(960, 960))
    with pytest.raises(WanI2VError, match='输出比例错误'):
        adapter.generate(image_bytes=b'image', prompt='商品保持原样', duration_seconds=5)


def test_pad_image_to_9_16_preserves_full_image() -> None:
    from onetake_api.integrations.media.image_utils import pad_image_to_9_16

    source = BytesIO()
    Image.new('RGB', (600, 800), (255, 0, 0)).save(source, format='PNG')
    output = pad_image_to_9_16(source.getvalue())
    with Image.open(BytesIO(output)) as image:
        assert image.size == (720, 1280)
        assert image.getpixel((360, 640)) == (255, 0, 0)


def test_wan_i2v_adapter_enforces_expected_dimensions(monkeypatch) -> None:
    import onetake_api.integrations.media.video_utils as vu

    monkeypatch.setattr(vu, "inspect_video_duration", lambda _content: 5.0)
    adapter = WanI2VAdapter(
        api_key='key', model='wan2.6-i2v', resolution='1080P', max_seconds=5,
        upload_image=lambda content: 'https://cdn.example/product.png',
        prepare_image=lambda _content: b'prepared-image', video_synthesis=FakeVideoSynthesis,
        inspect_dimensions=lambda _content: (1080, 1920), client=_client(),
        expected_width=1080, expected_height=1920,
    )
    video, _ = adapter.generate(image_bytes=b'image', prompt='p', duration_seconds=5)
    assert video == b'generated-video'


def test_wan_i2v_adapter_rejects_wrong_output_dimensions() -> None:
    from onetake_api.integrations.wan_i2v.adapter import VideoContractError

    adapter = WanI2VAdapter(
        api_key='key', model='wan2.6-i2v', resolution='1080P', max_seconds=5,
        upload_image=lambda content: 'https://cdn.example/product.png',
        prepare_image=lambda _content: b'prepared-image', video_synthesis=FakeVideoSynthesis,
        inspect_dimensions=lambda _content: (720, 1280), client=_client(),
        expected_width=1080, expected_height=1920,
    )
    with pytest.raises(VideoContractError, match='输出尺寸'):
        adapter.generate(image_bytes=b'image', prompt='p', duration_seconds=5)


def test_wan_i2v_adapter_rejects_duration_drift(monkeypatch) -> None:
    from onetake_api.integrations.wan_i2v.adapter import VideoContractError
    import onetake_api.integrations.media.video_utils as vu

    monkeypatch.setattr(vu, 'inspect_video_duration', lambda _content: 3.0)
    adapter = WanI2VAdapter(
        api_key='key', model='wan2.6-i2v', resolution='1080P', max_seconds=5,
        upload_image=lambda content: 'https://cdn.example/product.png',
        prepare_image=lambda _content: b'prepared-image', video_synthesis=FakeVideoSynthesis,
        inspect_dimensions=lambda _content: (1080, 1920), client=_client(),
        expected_width=1080, expected_height=1920, duration_tolerance_seconds=0.2,
    )
    with pytest.raises(VideoContractError, match='时长'):
        adapter.generate(image_bytes=b'image', prompt='p', duration_seconds=5)
