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


def test_product_scene_is_enabled_for_all_product_templates_with_real_providers(monkeypatch) -> None:
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
    for template_id in ("clean", "dynamic", "lifestyle"):
        assert VideoPlanApplicationService._uses_product_scene(SimpleNamespace(mode="product", template_id=template_id)) is True
    assert VideoPlanApplicationService._uses_product_scene(SimpleNamespace(mode="avatar", template_id=None)) is False

    settings.product_scene_enabled = False
    assert VideoPlanApplicationService._uses_product_scene(SimpleNamespace(mode="product", template_id="dynamic")) is False


def test_scene_assets_are_vertical() -> None:
    from onetake_api.integrations.product_scene.scene_assets import load_scene_keyframe, scene_prompt

    for goal in ("pain_point", "product_reveal", "usage_scenario", "cta"):
        with Image.open(BytesIO(load_scene_keyframe(goal))) as image:
            assert image.size == (720, 1280)
        prompt = scene_prompt(goal)
        assert "商品" not in prompt
        assert "包装" not in prompt


def test_product_scene_video_uses_selected_style_profile(monkeypatch) -> None:
    import onetake_api.modules.video_plan.service as service_module

    scenes = [
        SimpleNamespace(visual_goal="pain_point", start_seconds=0.0, end_seconds=3.0),
        SimpleNamespace(visual_goal="product_reveal", start_seconds=3.0, end_seconds=6.0),
        SimpleNamespace(visual_goal="usage_scenario", start_seconds=6.0, end_seconds=13.0),
        SimpleNamespace(visual_goal="cta", start_seconds=13.0, end_seconds=18.0),
    ]
    content_plan = SimpleNamespace(
        status="confirmed",
        selected_variant_index=0,
        variants=[SimpleNamespace(scenes=scenes)],
    )
    settings = SimpleNamespace(
        dashscope_api_key="key",
        wan_i2v_model="wan2.6-i2v-flash",
        wan_i2v_resolution="720P",
        wan_i2v_max_seconds=5,
    )
    calls = {"styles": [], "durations": []}

    class FakeUploader:
        def __init__(self, **_kwargs) -> None:
            pass

        def upload_image(self, _content: bytes, _filename: str) -> str:
            return "https://example.test/image.png"

    class FakeWan:
        def __init__(self, **_kwargs) -> None:
            pass

        def generate(self, *, image_bytes: bytes, prompt: str, duration_seconds: int, negative_prompt: str):
            assert image_bytes
            assert prompt
            assert negative_prompt
            calls["durations"].append(duration_seconds)
            return b"video", "task"

    monkeypatch.setattr(service_module, "get_settings", lambda: settings)
    monkeypatch.setattr(service_module, "DashScopeTemporaryUploader", FakeUploader)
    monkeypatch.setattr(service_module, "WanI2VAdapter", FakeWan)
    monkeypatch.setattr(service_module.ContentPlanPublicService, "latest", lambda _self, _session, _project_id: content_plan)
    monkeypatch.setattr(service_module, "load_scene_keyframe", lambda goal: goal.encode())
    monkeypatch.setattr(
        service_module,
        "apply_style_to_keyframe",
        lambda image, profile: calls["styles"].append(profile.style_id) or image,
    )
    monkeypatch.setattr(service_module, "build_background_prompt", lambda _scene, profile: profile.prompt)
    monkeypatch.setattr(service_module, "build_background_negative_prompt", lambda _scene, profile: profile.negative_prompt)
    monkeypatch.setattr(service_module, "concatenate_videos", lambda **_kwargs: b"final")

    service = VideoPlanApplicationService(composition=SimpleNamespace(provider_name="shotstack"))
    expected_styles = {
        "clean": "clean_studio",
        "dynamic": "realistic_commercial",
        "lifestyle": "natural_lifestyle",
    }

    for template_id, style_id in expected_styles.items():
        calls["styles"].clear()
        calls["durations"].clear()
        plan = SimpleNamespace(project_id="prj_1", template_id=template_id, duration_seconds=18, fps=30)
        assert service._create_product_scene_video(None, plan, b"main-image") == b"final"
        assert calls["styles"] == [style_id] * 4
        assert calls["durations"] == [3, 3, 4, 3, 5]
    assert calls["durations"] == [3, 3, 4, 3, 5]


def test_create_base_video_routes_all_product_templates_to_scene_pipeline(monkeypatch) -> None:
    import onetake_api.modules.video_plan.service as service_module

    settings = SimpleNamespace(
        product_scene_enabled=True,
        mock_providers=False,
        image_edit_provider="real",
        wan_i2v_provider="real",
        composition_provider="shotstack",
        dashscope_api_key="key",
        wan_i2v_model="wan2.6-i2v-flash",
        shotstack_api_key="key",
    )
    monkeypatch.setattr(service_module, "get_settings", lambda: settings)
    calls: list[str] = []
    service = VideoPlanApplicationService(composition=SimpleNamespace(provider_name="shotstack"))
    monkeypatch.setattr(
        service,
        "_create_product_scene_video",
        lambda _session, plan, _image: calls.append(plan.template_id) or b"product-scene",
    )

    for template_id in ("clean", "dynamic", "lifestyle"):
        plan = SimpleNamespace(
            mode="product",
            template_id=template_id,
            duration_seconds=18,
            width=1080,
            height=1920,
            fps=30,
        )
        assert service._create_base_video(None, plan, b"main-image") == b"product-scene"

    assert calls == ["clean", "dynamic", "lifestyle"]
