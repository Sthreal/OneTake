from io import BytesIO

from PIL import Image

from types import SimpleNamespace

from onetake_api.integrations.product_scene.adapter import ProductSceneAdapter
from onetake_api.modules.video_plan.service import VideoPlanApplicationService


class FakeImageEdit:
    def __init__(self) -> None:
        self.calls = []

    def edit(self, *, image_bytes: bytes, mime_type: str, prompt: str | None = None, negative_prompt: str | None = None) -> bytes:
        self.calls.append({
            "image_bytes": image_bytes,
            "mime_type": mime_type,
            "prompt": prompt,
            "negative_prompt": negative_prompt,
        })
        output = BytesIO()
        Image.new("RGB", (600, 800), (220, 40, 40)).save(output, format="PNG")
        return output.getvalue()


class FakeBackgroundVideo:
    def __init__(self) -> None:
        self.calls = []

    def generate(self, *, image_bytes: bytes, prompt: str, duration_seconds: int) -> tuple[bytes, str]:
        self.calls.append({"image_bytes": image_bytes, "prompt": prompt, "duration_seconds": duration_seconds})
        return b"background-video", "task_1"


def _png(color: tuple[int, int, int]) -> bytes:
    output = BytesIO()
    Image.new("RGB", (600, 800), color).save(output, format="PNG")
    return output.getvalue()


def test_product_scene_generates_background_then_animates_background_only() -> None:
    image_edit = FakeImageEdit()
    background_video = FakeBackgroundVideo()
    adapter = ProductSceneAdapter(image_edit=image_edit, background_video=background_video)

    background = adapter.generate_background_image(_png((30, 60, 220)), scene_style="clean")
    video, task_id = adapter.animate_background(
        background_image=background,
        prompt="场景风格：clean。",
        duration_seconds=5,
    )

    assert video == b"background-video"
    assert task_id == "task_1"
    edit_call = image_edit.calls[0]
    assert "移除画面中的商品" in str(edit_call["prompt"])
    assert "浅色现代影棚" in str(edit_call["prompt"])
    assert "商品" in str(edit_call["negative_prompt"])
    with Image.open(BytesIO(edit_call["image_bytes"])) as prepared_product:
        assert prepared_product.size == (720, 1280)

    video_call = background_video.calls[0]
    with Image.open(BytesIO(video_call["image_bytes"])) as prepared_background:
        assert prepared_background.size == (720, 1280)
        assert prepared_background.getpixel((360, 640)) == (220, 40, 40)
    assert "不要出现商品" in video_call["prompt"]
    assert video_call["duration_seconds"] == 5


def test_product_scene_is_enabled_only_for_dynamic_real_providers(monkeypatch) -> None:
    settings = SimpleNamespace(
        mock_providers=False,
        product_scene_enabled=True,
        wan_i2v_provider="real",
        image_edit_provider="real",
        composition_provider="shotstack",
        dashscope_api_key="key",
        wan_i2v_model="wan2.6-i2v-flash",
        shotstack_api_key="key",
    )
    monkeypatch.setattr("onetake_api.modules.video_plan.service.get_settings", lambda: settings)
    assert VideoPlanApplicationService._uses_product_scene(SimpleNamespace(mode="product", template_id="dynamic")) is True
    assert VideoPlanApplicationService._uses_product_scene(SimpleNamespace(mode="product", template_id="clean")) is False
    assert VideoPlanApplicationService._uses_product_scene(SimpleNamespace(mode="avatar", template_id=None)) is False

    settings.product_scene_enabled = False
    assert VideoPlanApplicationService._uses_product_scene(SimpleNamespace(mode="product", template_id="dynamic")) is False
