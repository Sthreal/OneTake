from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO

from PIL import Image, ImageEnhance

DEFAULT_STYLE_ID = "dynamic"


@dataclass(frozen=True)
class StyleProfile:
    style_id: str
    name: str
    prompt: str
    negative_prompt: str
    color_tint: tuple[float, float, float]
    saturation: float
    contrast: float


STYLE_PROFILES = {
    "clean": StyleProfile(
        style_id="clean_studio",
        name="干净影棚",
        prompt="统一为真实商业影棚摄影，冷色干净光线，真实材质，柔和阴影，画面简洁",
        negative_prompt="动画, 插画, 卡通, 手绘, 低多边形, 3D卡通",
        color_tint=(0.98, 1.0, 1.04),
        saturation=0.92,
        contrast=1.02,
    ),
    "dynamic": StyleProfile(
        style_id="realistic_commercial",
        name="真实商业广告",
        prompt="统一为真实商业广告摄影，真实材质和自然光影，暖色电影感，轻微景深，画面高级",
        negative_prompt="动画, 插画, 卡通, 手绘, 赛璐璐, 低多边形, 3D卡通, 矢量图",
        color_tint=(1.03, 1.0, 0.97),
        saturation=1.02,
        contrast=1.04,
    ),
    "lifestyle": StyleProfile(
        style_id="natural_lifestyle",
        name="自然生活方式",
        prompt="统一为自然生活方式广告摄影，真实日光和材质，温暖通透，低对比，生活感自然",
        negative_prompt="动画, 插画, 卡通, 手绘, 低多边形, 3D卡通",
        color_tint=(1.04, 1.01, 0.96),
        saturation=1.05,
        contrast=0.98,
    ),
}


def get_style_profile(template_id: str | None) -> StyleProfile:
    return STYLE_PROFILES.get(template_id or DEFAULT_STYLE_ID, STYLE_PROFILES[DEFAULT_STYLE_ID])


def apply_style_to_keyframe(image_bytes: bytes, profile: StyleProfile) -> bytes:
    with Image.open(BytesIO(image_bytes)) as source:
        image = source.convert("RGB")
        channels = []
        for channel, factor in zip(image.split(), profile.color_tint):
            channels.append(channel.point(lambda value, factor=factor: min(255, round(value * factor))))
        image = Image.merge("RGB", channels)
        image = ImageEnhance.Color(image).enhance(profile.saturation)
        image = ImageEnhance.Contrast(image).enhance(profile.contrast)
        output = BytesIO()
        image.save(output, format="PNG", optimize=True)
        return output.getvalue()
