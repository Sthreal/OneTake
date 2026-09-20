from io import BytesIO

from PIL import Image

from onetake_api.integrations.product_scene.style_profiles import apply_style_to_keyframe, get_style_profile


def _scene_png() -> bytes:
    image = Image.new("RGB", (200, 300), (100, 120, 140))
    output = BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


def test_template_maps_to_style_profile() -> None:
    assert get_style_profile("clean").style_id == "clean_studio"
    assert get_style_profile("dynamic").style_id == "realistic_commercial"
    assert get_style_profile("lifestyle").style_id == "natural_lifestyle"
    assert get_style_profile(None).style_id == "realistic_commercial"


def test_style_changes_keyframe_color() -> None:
    source = _scene_png()
    clean = apply_style_to_keyframe(source, get_style_profile("clean"))
    lifestyle = apply_style_to_keyframe(source, get_style_profile("lifestyle"))
    with Image.open(BytesIO(clean)) as clean_image, Image.open(BytesIO(lifestyle)) as lifestyle_image:
        assert clean_image.size == (200, 300)
        assert lifestyle_image.size == (200, 300)
        assert clean_image.getpixel((100, 150)) != lifestyle_image.getpixel((100, 150))
