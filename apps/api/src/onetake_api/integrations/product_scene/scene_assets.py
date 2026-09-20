from __future__ import annotations

from pathlib import Path

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


def load_scene_keyframe(visual_goal: str) -> bytes:
    filename, _prompt = SCENE_ASSETS.get(visual_goal, SCENE_ASSETS["product_reveal"])
    path = SCENE_DIR / filename
    if not path.is_file():
        raise FileNotFoundError(f"scene asset missing: {path}")
    return path.read_bytes()


def scene_prompt(visual_goal: str) -> str:
    return SCENE_ASSETS.get(visual_goal, SCENE_ASSETS["product_reveal"])[1]
