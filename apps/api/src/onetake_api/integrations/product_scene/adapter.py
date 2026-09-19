from __future__ import annotations

from collections.abc import Callable
from typing import Protocol

from onetake_api.integrations.media.image_utils import pad_image_to_9_16

BACKGROUND_EDIT_PROMPT = (
    "移除画面中的商品主体、包装、标签、Logo、促销文字和水印，"
    "把商品占用的区域自然补全为一个完整、连续、真实的场景背景。"
    "画面必须有清晰的承载面和空间氛围，并在中央保留适合放置商品的位置；"
    "不要输出纯白空背景，不要生成任何商品、文字、Logo、标签或水印。"
)
BACKGROUND_EDIT_NEGATIVE_PROMPT = "商品, 包装, 标签, Logo, 文字, 水印, 促销元素, 人物手持商品, 纯白空背景, 空白画布"
SCENE_STYLE_PROMPTS = {
    "clean": "浅色现代影棚，柔和渐变背景，简洁承载台，中央留出商品位置",
    "story": "自然生活场景，柔和生活光，木质桌面或家居环境，中央留出商品位置",
    "trend": "高饱和时尚广告场景，影棚灯光和轻微景深，中央留出商品位置",
}
BACKGROUND_VIDEO_PROMPT = (
    "只生成空场景背景的轻微自然运动，镜头缓慢推近，光线稳定；"
    "不要出现商品、包装、Logo、文字、水印或人物。场景要求："
)


class ImageEditPort(Protocol):
    def edit(
        self,
        *,
        image_bytes: bytes,
        mime_type: str,
        prompt: str | None = None,
        negative_prompt: str | None = None,
    ) -> bytes:
        ...


class BackgroundVideoPort(Protocol):
    def generate(self, *, image_bytes: bytes, prompt: str, duration_seconds: int) -> tuple[bytes, str]:
        ...


class ProductSceneAdapter:
    def __init__(
        self,
        *,
        image_edit: ImageEditPort,
        background_video: BackgroundVideoPort,
        prepare_image: Callable[[bytes], bytes] = pad_image_to_9_16,
    ) -> None:
        self._image_edit = image_edit
        self._background_video = background_video
        self._prepare_image = prepare_image

    def generate_background_image(self, product_image: bytes, scene_style: str | None = None) -> bytes:
        prepared_product = self._prepare_image(product_image)
        style_prompt = SCENE_STYLE_PROMPTS.get(scene_style or "", "浅色现代影棚，柔和光线，中央留出商品位置")
        prompt = f"{BACKGROUND_EDIT_PROMPT} 目标场景：{style_prompt}。"
        background = self._image_edit.edit(
            image_bytes=prepared_product,
            mime_type="image/png",
            prompt=prompt,
            negative_prompt=BACKGROUND_EDIT_NEGATIVE_PROMPT,
        )
        return self._prepare_image(background)

    def animate_background(self, *, background_image: bytes, prompt: str, duration_seconds: int) -> tuple[bytes, str]:
        prepared_background = self._prepare_image(background_image)
        return self._background_video.generate(
            image_bytes=prepared_background,
            prompt=f"{BACKGROUND_VIDEO_PROMPT}{prompt}",
            duration_seconds=duration_seconds,
        )
