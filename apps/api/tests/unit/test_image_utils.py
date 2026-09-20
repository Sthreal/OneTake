from io import BytesIO

from PIL import Image, ImageDraw

from onetake_api.integrations.media.image_utils import add_contact_shadow, pad_image_to_9_16


def _product_png() -> bytes:
    image = Image.new("RGBA", (200, 300), (0, 0, 0, 0))
    ImageDraw.Draw(image).rectangle((50, 60, 150, 250), fill=(220, 40, 40, 255))
    output = BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


def test_contact_shadow_adds_alpha_without_resizing_product() -> None:
    original = _product_png()
    result = add_contact_shadow(original)
    with Image.open(BytesIO(original)) as before, Image.open(BytesIO(result)) as after:
        assert after.size == before.size
        assert after.mode == "RGBA"
        assert sum(1 for value in after.getchannel("A").getdata() if value > 0) > sum(1 for value in before.getchannel("A").getdata() if value > 0)
        assert after.getpixel((100, 180)) == (220, 40, 40, 255)


def test_pad_image_to_9_16_returns_rgb() -> None:
    result = pad_image_to_9_16(_product_png())
    with Image.open(BytesIO(result)) as image:
        assert abs(image.width / image.height - 9 / 16) < 0.01
        assert image.mode == "RGB"
