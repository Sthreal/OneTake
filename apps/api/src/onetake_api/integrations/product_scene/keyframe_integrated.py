"""关键帧「商品入画」生成（Phase 1）。

职责边界：本模块**只负责生成与质检**，不落库、不写对象存储（由应用服务负责），
便于单测与 mock 端到端。

两条路径：
- real：qwen-image-2.0-pro 多图融合（图1=商品主图，图2=场景参考，图3=上一镜关键帧做一致性锚）
- mock：确定性背景 + 原始商品像素合成，等价于"商品入画"的离线结果，不产生任何付费调用

质检不通过且开关打开时，自动走 pixel-lock 把原始商品像素贴回（保真三级降级的第二级）。
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace

from onetake_api.config import Settings, get_settings
from onetake_api.integrations.media.image_utils import image_dimensions, pad_image_to_9_16
from onetake_api.integrations.product_scene import grid_split
from onetake_api.integrations.product_scene.multi_view import generate_multi_view_sheet
from onetake_api.integrations.product_scene.keyframe_qa import KeyframeQaPort, KeyframeQaResult, get_keyframe_qa
from onetake_api.integrations.product_scene.pixel_lock import lock_product_pixels
from onetake_api.integrations.product_scene.scene_assets import load_scene_keyframe
from onetake_api.integrations.product_scene.style_profiles import StyleProfile, apply_style_to_keyframe, get_style_profile
from onetake_api.modules.content_plan.domain import ContentScene
from onetake_api.modules.content_plan.prompt_schema import (
    build_keyframe_negative_prompt,
    build_keyframe_prompt,
    build_storyboard_grid_prompt,
)
from onetake_api.platform.errors import DomainError

MODE_INTEGRATED = "integrated"
MODE_ERASE = "erase_background"
# 批次 3：九宫格（一张整图出 4 格）。格数写死 2×2 —— 本仓 4 镜，3×3 会白留 5 格且上采样从 1.56× 恶化到 2.34×
MODE_GRID = "grid"
GRID_ROWS = 2
GRID_COLS = 2


class KeyframeGenerationError(DomainError):
    code = "KEYFRAME_GENERATION_FAILED"
    http_status = 502
    retryable = True


@dataclass(frozen=True)
class GeneratedKeyframe:
    image_bytes: bytes
    mode: str
    seed: int | None
    provider: str
    qa: KeyframeQaResult
    width: int
    height: int
    # None 表示直接生成通过；"pixel_lock" 表示质检不通过后走了像素锁定兜底
    fallback: str | None = None
    issues: list[str] = field(default_factory=list)


def _build_image_edit(settings: Settings):
    from onetake_api.integrations.qwen_image_edit.adapter import QwenImageEditAdapter

    if not settings.dashscope_api_key:
        raise KeyframeGenerationError("关键帧生成缺少 DASHSCOPE_API_KEY")
    return QwenImageEditAdapter(
        api_key=settings.dashscope_api_key,
        endpoint=settings.image_edit_endpoint,
        model=settings.image_edit_model,
    )


def _target_size(settings: Settings) -> tuple[int, int]:
    """目标关键帧规格（production 固定 1080×1920；解析 `W*H` 字符串，解析不了就用默认）。"""
    raw = str(getattr(settings, "keyframe_image_size", "") or "")
    try:
        width, height = (int(part) for part in raw.split("*"))
        return width, height
    except (TypeError, ValueError):
        return grid_split.TARGET_WIDTH, grid_split.TARGET_HEIGHT

class KeyframeGenerator:
    def __init__(
        self,
        *,
        settings: Settings | None = None,
        image_edit=None,
        qa: KeyframeQaPort | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._image_edit = image_edit
        self._qa = qa

    @property
    def settings(self) -> Settings:
        return self._settings

    @property
    def mode(self) -> str:
        return self._settings.keyframe_mode

    @property
    def qa(self) -> KeyframeQaPort:
        if self._qa is None:
            self._qa = get_keyframe_qa(self._settings)
        return self._qa

    def generate(
        self,
        *,
        scene: ContentScene,
        product_png: bytes,
        style_profile: StyleProfile | None = None,
        mode: str | None = None,
        n: int | None = None,
        seed: int | None = None,
        scene_reference: bytes | None = None,
        character_png: bytes | None = None,
    ) -> list[GeneratedKeyframe]:
        """`character_png`：出镜人母版（**有就一定要传**）。

        为什么：本仓此前只喂商品 → 首帧必然没有人 → 后面所有生成都顺着"商品在台上"演。
        现在把人像当第二张输入图喂进去，并在提示词里要求"这个人手持这个商品"（见 prompt_schema）。
        """
        resolved_mode = mode or self.mode
        if resolved_mode not in {MODE_INTEGRATED, MODE_ERASE, MODE_GRID}:
            raise KeyframeGenerationError("关键帧模式必须是 integrated / erase_background / grid")
        count = max(1, min(6, n or self._settings.keyframe_candidates))
        style = style_profile or get_style_profile(scene.template_id or None)

        if self._settings.mock_providers or not self._settings.dashscope_api_key:
            return [self._mock_candidate(scene=scene, product_png=product_png, style=style, mode=resolved_mode, seed=seed)]

        if resolved_mode == MODE_ERASE:
            return [self._erase_candidate(scene=scene, product_png=product_png, style=style, seed=seed)]

        raw_images = self._generate_images(
            scene=scene, product_png=product_png, style=style, count=count, seed=seed,
            scene_reference=scene_reference, character_png=character_png,
        )
        return [
            self._qa_candidate(image, scene=scene, product_png=product_png, mode=resolved_mode, seed=seed,
                               provider=self._provider_name())
            for image in raw_images
        ]

    # ---- 批次 3：九宫格路径 ----

    def generate_grid_image(
        self, *, scenes: list[ContentScene], product_png: bytes, seed: int | None = None,
        scene_reference: bytes | None = None, character_png: bytes | None = None,
    ) -> bytes:
        """生成**一张**九宫格整图（mock 时用确定性拼图，让离线链路也能跑通）。

        只调一次模型 → 这是本批"省调用"的来源；同一张网格在计划内复用（跨镜一致）。
        """
        style = get_style_profile(scenes[0].template_id if scenes else None)
        if self._settings.mock_providers or not self._settings.dashscope_api_key:
            return self._render_mock_grid(scenes=scenes, product_png=product_png, style=style)
        adapter = self._image_edit or _build_image_edit(self._settings)
        images: list[tuple[bytes, str]] = []
        if scene_reference:
            images.append((pad_image_to_9_16(scene_reference), "image/png"))
        images.append((product_png, "image/png"))
        product_ref = len(images)
        character_ref: int | None = None
        if character_png:
            images.append((pad_image_to_9_16(character_png), "image/png"))
            character_ref = len(images)
        # 「一次调用出一张 2×2 整图」这一段是**共享实现**（出镜人四视角母版走同一个函数）——
        # 见 multi_view.py；这里只提供商品侧的提示词/尺寸/错误类型。
        return generate_multi_view_sheet(
            adapter=adapter,
            images=images,
            prompt=build_storyboard_grid_prompt(
                GRID_ROWS, GRID_COLS, character_ref=character_ref, product_ref=product_ref
            ),
            negative_prompt="文字、字幕、编号、水印、粗边框、格线以外的装饰"
            + ("、第二个人、换脸、多出来的手、拼贴感" if character_ref is not None else ""),
            size=self._settings.keyframe_grid_image_size,
            seed=seed,
            error_cls=KeyframeGenerationError,
            failure_message="九宫格整图生成失败",
            empty_message="九宫格生成返回空结果",
        )

    def grid_cell_verdicts(self, *, grid_image: bytes, product_png: bytes) -> list[KeyframeQaResult]:
        """把整图切成格并**逐格质检**，返回每格的 verdict（供服务层判断"整张网格可不可用"）。

        为什么要有这个方法：某一片的网格**整体不可用**时（2026-10-15 用户肉眼复核：四格 match 0.488~0.498 那一档，
        右上格标签文字变乱码、且四格不是同一瓶），逐格回退会变成"1 次网格 + 4 次单帧"，比两条路都贵。
        服务层用这里的 verdict 做**片级判断**：坏格过半 → 整片改用单帧档，不再逐格补救。
        """
        payloads, _split = grid_split.split_grid(
            grid_image, rows=GRID_ROWS, cols=GRID_COLS,
            target_width=_target_size(self._settings)[0], target_height=_target_size(self._settings)[1],
        )
        floor = self._grid_floor()
        # 逐格套**同一套网格档门槛**（`_grid_cell_ok`）—— 服务层判"坏格过半"和这里判"这一格能不能用"
        # 必须是同一个判据，否则会出现"片级说过半坏、逐格却全采用"的自相矛盾。
        return [
            replace(verdict, passed=self._grid_cell_ok(verdict, floor=floor))
            for verdict in (self.qa.evaluate(image_bytes=payload, product_png=product_png) for payload in payloads)
        ]

    def _grid_floor(self) -> float:
        """网格档的相似度下限（单帧档用 keyframe_qa 的 0.55；格子经过裁切+上采样，分数系统性偏低）。"""
        return float(getattr(self._settings, "keyframe_grid_match_floor", 0.52))

    @staticmethod
    def _grid_cell_ok(verdict: KeyframeQaResult, *, floor: float) -> bool:
        """网格档单格硬门槛：**结构信号（商品入画 + 文字清晰）+ 相似度下限**。

        为什么相似度仍是硬门槛（2026-10-15 由用户肉眼复核定案）：瓶子那档四格 match 0.488~0.498 时，
        人眼看到的是「**右上格标签文字变成诡异符号 + 四格不是同一瓶**」，而同商品单帧（0.784）清晰完整、
        文字可认 → **低分确实对应坏格**。（上一轮我只有数字、没人看图，据此推断"指标太苛刻"并把它降级为
        警示线，已被这次复核推翻。）
        """
        return bool(verdict.product_present and verdict.text_intact and float(verdict.product_match) >= floor)

    def candidates_from_grid(
        self,
        *,
        grid_image: bytes,
        scene: ContentScene,
        scenes: list[ContentScene],
        product_png: bytes,
        seed: int | None = None,
    ) -> list[GeneratedKeyframe]:
        """从整图里取**该镜那一格**并质检；该格不过线时**只重生成这一格**（退回单帧路径）。

        批次 0 的实测结论：2×2 有约 1/3 概率出现 1 格偏色 → 所以"逐格质检 + 只重做坏格"是必需的，
        而不是"整图不过就整张重来"。
        """
        payloads, split = grid_split.split_grid(
            grid_image, rows=GRID_ROWS, cols=GRID_COLS,
            target_width=_target_size(self._settings)[0], target_height=_target_size(self._settings)[1],
        )
        index = max(0, min(len(payloads) - 1, max(1, scene.order) - 1))
        cell_qa = self._qa_candidate(
            payloads[index], scene=scene, product_png=product_png, mode=MODE_GRID,
            seed=seed, provider=f"{self._provider_name()}-grid",
        )
        detail = (
            f"九宫格：整图 {split.grid_size[0]}x{split.grid_size[1]}，第 {index + 1} 格 "
            f"{split.cells[index].width}x{split.cells[index].height}→{_target_size(self._settings)[0]}x{_target_size(self._settings)[1]}，"
            f"白缝{'命中' if split.seam_detected else '未命中（按名义等分退化）'}"
        )
        floor = self._grid_floor()
        if self._grid_cell_ok(cell_qa.qa, floor=floor):
            return [replace(cell_qa, issues=[
                *cell_qa.issues,
                f"{detail}；相似度 {float(cell_qa.qa.product_match):.3f}（网格档门槛 {floor}）",
            ])]
        # 该格不过线 → 只重生成这一格（单帧路径），并把原因如实带上
        fallback = self.generate(
            scene=scene, product_png=product_png, mode=MODE_INTEGRATED, seed=seed, n=1,
        )
        return [
            replace(item, issues=[*item.issues, detail, "九宫格该格质检未过 → 已只重生成这一格（单帧路径）"])
            for item in fallback
        ]

    def _render_mock_grid(self, *, scenes: list[ContentScene], product_png: bytes, style: StyleProfile) -> bytes:
        """mock 九宫格：4 张确定性 mock 关键帧拼成 2×2，并画极细白缝（离线也能验证裁切与逐格质检）。"""
        from io import BytesIO

        from PIL import Image, ImageDraw

        cells = [
            self._render_mock_keyframe(scene=scene, product_png=product_png, style=style)
            for scene in scenes[: GRID_ROWS * GRID_COLS]
        ]
        if not cells:
            cells = [self._render_mock_keyframe(scene=scene, product_png=product_png, style=style) for scene in scenes] or []
        if not cells:
            raise KeyframeGenerationError("九宫格 mock 缺少分镜")
        with Image.open(BytesIO(cells[0])) as first:
            cell_width, cell_height = first.size
        width, height = cell_width * GRID_COLS, cell_height * GRID_ROWS
        canvas = Image.new("RGB", (width, height), (255, 255, 255))
        draw = ImageDraw.Draw(canvas)
        for index in range(GRID_ROWS * GRID_COLS):
            row, column = divmod(index, GRID_COLS)
            if index < len(cells):
                with Image.open(BytesIO(cells[index])) as cell:
                    canvas.paste(cell.convert("RGB"), (column * cell_width, row * cell_height))
            else:
                draw.rectangle(
                    (column * cell_width, row * cell_height, (column + 1) * cell_width - 1, (row + 1) * cell_height - 1),
                    fill=(240, 240, 240),
                )
        draw.line([(cell_width, 0), (cell_width, height)], fill=(255, 255, 255), width=2)
        draw.line([(0, cell_height), (width, cell_height)], fill=(255, 255, 255), width=2)
        buffer = BytesIO()
        canvas.save(buffer, format="PNG")
        return buffer.getvalue()
    # ---- 真实路径 ----

    def _generate_images(
        self,
        *,
        scene: ContentScene,
        product_png: bytes,
        style: StyleProfile,
        count: int,
        seed: int | None,
        scene_reference: bytes | None,
        character_png: bytes | None = None,
    ) -> list[bytes]:
        adapter = self._image_edit or _build_image_edit(self._settings)
        images: list[tuple[bytes, str]] = []
        if scene_reference:
            images.append((pad_image_to_9_16(scene_reference), "image/png"))
        images.append((product_png, "image/png"))
        product_ref = len(images)
        character_ref: int | None = None
        if character_png:
            # qwen-image-edit 最多 3 张输入图 → [上一镜?, 商品, 人物] 正好占满，多了会直接报错
            images.append((pad_image_to_9_16(character_png), "image/png"))
            character_ref = len(images)
        try:
            results = adapter.generate(
                images=images,
                prompt=build_keyframe_prompt(
                    scene, style, character_ref=character_ref, product_ref=product_ref
                ),
                negative_prompt=build_keyframe_negative_prompt(
                    scene, style, with_character=character_ref is not None
                ),
                n=count,
                seed=seed,
                size=self._settings.keyframe_image_size,
            )
        except DomainError:
            raise
        except Exception as exc:  # noqa: BLE001 - 统一转成领域错误
            raise KeyframeGenerationError("关键帧生成失败") from exc
        if not results:
            raise KeyframeGenerationError("关键帧生成返回空结果")
        return [pad_image_to_9_16(item) for item in results]

    def _erase_candidate(
        self, *, scene: ContentScene, product_png: bytes, style: StyleProfile, seed: int | None
    ) -> GeneratedKeyframe:
        """旧路径（保留兜底）：只生成空背景，商品由合成层叠加。"""
        background = apply_style_to_keyframe(load_scene_keyframe(scene.visual_goal or "product_reveal"), style)
        width, height = image_dimensions(background)
        qa = self.qa.evaluate(image_bytes=background, product_png=product_png)
        return GeneratedKeyframe(
            image_bytes=background, mode=MODE_ERASE, seed=seed, provider=self._provider_name(),
            qa=qa, width=width, height=height, issues=["空背景路径：商品由合成层叠加"],
        )

    # ---- Mock 路径（MOCK_PROVIDERS=true 时端到端可用）----

    def _mock_candidate(
        self, *, scene: ContentScene, product_png: bytes, style: StyleProfile, mode: str, seed: int | None
    ) -> GeneratedKeyframe:
        if mode == MODE_ERASE:
            return self._erase_candidate(scene=scene, product_png=product_png, style=style, seed=seed)
        return self._qa_candidate(
            self._render_mock_keyframe(scene=scene, product_png=product_png, style=style),
            scene=scene, product_png=product_png, mode=MODE_INTEGRATED, seed=seed, provider="mock-keyframe",
        )

    def _render_mock_keyframe(self, *, scene: ContentScene, product_png: bytes, style: StyleProfile) -> bytes:
        background = apply_style_to_keyframe(load_scene_keyframe(scene.visual_goal or "product_reveal"), style)
        return lock_product_pixels(scene_image=background, product_png=product_png)

    # ---- 质检 + 像素锁定兜底 ----

    def _qa_candidate(
        self, image: bytes, *, scene: ContentScene, product_png: bytes, mode: str, seed: int | None, provider: str
    ) -> GeneratedKeyframe:
        qa = self.qa.evaluate(image_bytes=image, product_png=product_png)
        fallback: str | None = None
        final_image = image
        if not qa.passed and self._settings.keyframe_pixel_lock_fallback:
            locked = lock_product_pixels(scene_image=image, product_png=product_png)
            locked_qa = self.qa.evaluate(image_bytes=locked, product_png=product_png)
            if locked_qa.passed or locked_qa.product_match >= qa.product_match:
                final_image = locked
                fallback = "pixel_lock"
                qa = locked_qa
        width, height = image_dimensions(final_image)
        return GeneratedKeyframe(
            image_bytes=final_image, mode=mode, seed=seed, provider=provider, qa=qa,
            width=width, height=height, fallback=fallback, issues=list(qa.issues),
        )

    def _provider_name(self) -> str:
        adapter = self._image_edit
        return getattr(adapter, "provider_name", None) or self._settings.image_edit_model or "qwen-image-edit"