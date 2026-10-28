from __future__ import annotations

from io import BytesIO
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

SCENE_DIR = Path(__file__).resolve().parents[2] / "assets" / "scenes"

SCENE_ASSETS = {
    "pain_point": (
        "pain-office.png",
        "办公室桌面环境，空杯和纸张，冷色光线，表达工作疲惫感，不出现人物、额外主体、文字。",
    ),
    "product_reveal": (
        "reveal-studio.png",
        "温暖现代影棚和展示台，灯光渐亮，中央留出稳定空间，镜头缓慢推近，不出现额外主体、人物或文字。",
    ),
    "usage_scenario": (
        "usage-active.png",
        "户外运动后的自然环境，长椅和绿植，树叶轻微运动，中央留出稳定空间，不出现人物、额外主体、文字。",
    ),
    "cta": (
        "cta-studio.png",
        "明亮的橙色调影棚，中央平台和柔和光晕，灯光轻微变化，镜头缓慢推近，不出现额外主体、人物或文字。",
    ),
}


CLEAN_BACKGROUNDS = {
    "pain_point": ((38, 46, 60), (176, 186, 196)),
    "product_reveal": ((232, 226, 214), (255, 250, 240)),
    "usage_scenario": ((118, 156, 142), (224, 238, 220)),
    "cta": ((214, 138, 74), (255, 236, 206)),
}


def _render_clean_background(visual_goal: str, width: int = 1080, height: int = 1920) -> bytes:
    top, bottom = CLEAN_BACKGROUNDS.get(visual_goal, CLEAN_BACKGROUNDS["product_reveal"])
    image = Image.new("RGB", (width, height))
    draw = ImageDraw.Draw(image)
    for y in range(height):
        ratio = y / max(1, height - 1)
        color = tuple(round(top[index] * (1 - ratio) + bottom[index] * ratio) for index in range(3))
        draw.line((0, y, width, y), fill=color)
    glow = Image.new("L", (width, height), 0)
    glow_draw = ImageDraw.Draw(glow)
    glow_draw.ellipse((width * 0.12, height * 0.12, width * 0.88, height * 0.88), fill=90)
    glow = glow.filter(ImageFilter.GaussianBlur(radius=180))
    warm = Image.new("RGB", (width, height), (255, 255, 255))
    image = Image.composite(warm, image, glow.point(lambda value: int(value * 0.22)))
    output = BytesIO()
    image.save(output, format="PNG", optimize=True)
    return output.getvalue()


def load_scene_keyframe(visual_goal: str) -> bytes:
    # 关键帧必须是可追溯的干净背景，不能继续使用本地 mock 场景图。
    # 这里用确定性生成的纯背景替代 pain-office.png 等素材，避免把 mock 痕迹带进 Wan。
    return _render_clean_background(visual_goal)


def scene_prompt(visual_goal: str) -> str:
    return SCENE_ASSETS.get(visual_goal, SCENE_ASSETS["product_reveal"])[1]
