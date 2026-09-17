from io import BytesIO

from PIL import Image

from onetake_api.modules.main_image.image_processing import MAX_JPG_BYTES, standardize_main_image


def _transparent_product() -> bytes:
    canvas = Image.new("RGBA", (900, 700), (0, 0, 0, 0))
    product = Image.new("RGBA", (420, 600), (235, 78, 54, 255))
    canvas.alpha_composite(product, dest=(240, 50))
    output = BytesIO()
    canvas.save(output, format="PNG")
    return output.getvalue()


def test_standardize_main_image_outputs_expected_assets() -> None:
    result = standardize_main_image(_transparent_product())
    assert result.png_width == 2000
    assert result.png_height == 2000
    assert result.jpg_width == 1000
    assert result.jpg_height == 1000
    assert result.jpg_size_bytes <= MAX_JPG_BYTES
    assert 0.8 <= result.product_ratio <= 0.85

    with Image.open(BytesIO(result.png_bytes)) as png:
        assert png.mode == "RGBA"
        assert png.getpixel((0, 0))[3] == 0
        assert png.getchannel("A").getbbox() is not None

    with Image.open(BytesIO(result.jpg_bytes)) as jpg:
        assert jpg.mode == "RGB"
        assert jpg.getpixel((0, 0)) == (255, 255, 255)
