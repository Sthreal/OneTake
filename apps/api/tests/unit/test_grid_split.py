"""批次 3 单测：九宫格裁切 + 逐格质检 + 单帧回退 + 网格复用。

裁切用**合成图**验证（每个象限涂不同颜色 → 裁出来的格子颜色必须对得上），
不需要真实模型调用；生成器部分走 mock（确定性拼图），所以整条网格链路离线可跑。
"""
from __future__ import annotations

import io
from types import SimpleNamespace

import pytest
from PIL import Image, ImageDraw

from onetake_api.config import Settings
from onetake_api.integrations.product_scene import grid_split
from onetake_api.integrations.product_scene.keyframe_integrated import (
    GRID_COLS,
    GRID_ROWS,
    MODE_GRID,
    KeyframeGenerator,
)
from onetake_api.integrations.product_scene.keyframe_qa import KeyframeQaResult
from onetake_api.integrations.product_scene.pixel_lock import product_box
from onetake_api.modules.content_plan.domain import ContentScene
from onetake_api.modules.video_plan.keyframe_service import VideoKeyframeApplicationService

QUADRANT_COLOURS = [(200, 60, 60), (60, 160, 90), (60, 90, 200), (200, 170, 60)]


def _grid_image(*, width: int = 1440, height: int = 2560, seam: int = 6) -> bytes:
    """合成 2×2 九宫格：四象限不同颜色 + 指定宽度的白缝。"""
    canvas = Image.new("RGB", (width, height), (255, 255, 255))
    draw = ImageDraw.Draw(canvas)
    half_w, half_h = width // 2, height // 2
    boxes = [
        (0, 0, half_w - seam // 2, half_h - seam // 2),
        (half_w + seam // 2, 0, width, half_h - seam // 2),
        (0, half_h + seam // 2, half_w - seam // 2, height),
        (half_w + seam // 2, half_h + seam // 2, width, height),
    ]
    colours = [QUADRANT_COLOURS[0], QUADRANT_COLOURS[1], QUADRANT_COLOURS[2], QUADRANT_COLOURS[3]]
    for box, colour in zip(boxes, colours):
        draw.rectangle(box, fill=colour)
    buffer = io.BytesIO()
    canvas.save(buffer, format="PNG")
    return buffer.getvalue()


def test_detect_seams_finds_white_separators() -> None:
    with Image.open(io.BytesIO(_grid_image(seam=8))) as image:
        vertical, horizontal = grid_split.detect_seams(image.convert("RGB"))
    assert len(vertical) == 1 and len(horizontal) == 1
    assert abs((vertical[0][0] + vertical[0][1]) / 2 - 720) <= 8
    assert abs((horizontal[0][0] + horizontal[0][1]) / 2 - 1280) <= 8


def test_plan_cells_excludes_wide_seam_entirely() -> None:
    """批次 0 的实测：白缝最宽到 26px —— 裁切必须把整条缝排除，而不是"刚好擦过"。"""
    with Image.open(io.BytesIO(_grid_image(seam=26))) as image:
        vertical, horizontal = grid_split.detect_seams(image.convert("RGB"))
    cells = grid_split.plan_cells(1440, 2560, rows=2, cols=2, vertical_seams=vertical, horizontal_seams=horizontal)
    seam_start, seam_end = vertical[0]
    assert cells[0].box[2] <= seam_start                     # 左格右边界在缝之前
    assert cells[1].box[0] >= seam_end                       # 右格左边界在缝之后
    assert cells[2].box[1] >= horizontal[0][1]               # 下格上边界在缝之后


def test_plan_cells_falls_back_to_nominal_division() -> None:
    cells = grid_split.plan_cells(1440, 2560, rows=2, cols=2, vertical_seams=[], horizontal_seams=[])
    assert cells[0].box[2] < 720 and cells[1].box[0] > 720   # 名义等分 + 2% 内缩
    assert cells[0].height < 1280 and cells[2].box[1] > 1280


def test_split_grid_maps_each_cell_to_the_right_quadrant() -> None:
    """裁切几何的正确性证明：每格的主色必须等于对应象限的颜色。"""
    payloads, result = grid_split.split_grid(_grid_image(seam=8), rows=GRID_ROWS, cols=GRID_COLS)
    assert len(payloads) == 4
    assert result.seam_detected is True
    assert result.grid_size == (1440, 2560)
    for payload, expected in zip(payloads, QUADRANT_COLOURS):
        with Image.open(io.BytesIO(payload)) as cell:
            assert cell.size == (1080, 1920)                 # 已归一化到生产关键帧规格
            sample = cell.convert("RGB").getpixel((cell.width // 2, cell.height // 2))
        assert all(abs(a - b) <= 6 for a, b in zip(sample, expected)), (sample, expected)


def test_split_grid_rejects_empty_input() -> None:
    with pytest.raises(grid_split.GridSplitError):
        grid_split.split_grid(b"", rows=GRID_ROWS, cols=GRID_COLS)


# ---- 生成器（mock：确定性拼图，离线跑通整条网格链路）----


def _scene(order: int) -> ContentScene:
    return ContentScene(
        scene_id=f"scene_{order}", order=order, purpose="hook", script_excerpt="文案",
        start_seconds=float((order - 1) * 4), end_seconds=float(order * 4), shot_type="medium",
        prompt="场景", overlay_product=True, product_position="center", background_style="clean",
        template_id="clean", subtitle_segment_ids=[order], qa_rules=[], visual_goal="product_reveal",
        subject_action="缓慢推进", camera_move="slow_push_in", product_mode="overlay", transition="fade",
    )


def _settings(**overrides) -> Settings:
    base = {"mock_providers": True, "keyframe_mode": MODE_GRID, "keyframe_grid_image_size": "1440*2560"}
    base.update(overrides)
    return Settings(**base)


def _product_png(size: int = 400) -> bytes:
    """与 `test_keyframe_generation.py` **同口径**的商品主图：透明底 + 圆角色块 + 一条白带。

    口径一致很重要：质检（`keyframe_qa`）与像素锁定都按"透明底 + 可见 bbox"算几何，
    用不透明方块会让 mock 结果偏离真实输入（我第一版就是这么踩的）。
    """
    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((40, 80, size - 40, size - 60), radius=32, fill=(196, 42, 42, 255))
    draw.rectangle((60, 120, size - 60, 150), fill=(255, 255, 255, 255))
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def test_generator_mock_grid_path_produces_per_cell_candidates() -> None:
    scenes = [_scene(index + 1) for index in range(4)]
    generator = KeyframeGenerator(settings=_settings())
    grid = generator.generate_grid_image(scenes=scenes, product_png=_product_png())
    with Image.open(io.BytesIO(grid)) as image:
        assert image.width == image.height * 9 / 16 or abs(image.width / image.height - 9 / 16) < 0.02

    candidates = generator.candidates_from_grid(
        grid_image=grid, scene=scenes[2], scenes=scenes, product_png=_product_png(), seed=7,
    )
    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate.mode == MODE_GRID and (candidate.width, candidate.height) == (1080, 1920)
    assert any("九宫格：整图" in issue for issue in candidate.issues)
    assert any("第 3 格" in issue for issue in candidate.issues)          # 镜号与格号对应（1 基）


class _FailingGridQa:
    """把"九宫格那一格"判为不过线，用来验证"只重生成这一格"的回退。"""

    provider_name = "fake-qa"
    model_name = "fake-qa"

    def __init__(self) -> None:
        self.calls: list[str] = []

    def evaluate(self, *, image_bytes: bytes, product_png: bytes) -> KeyframeQaResult:
        # 单帧路径（integrated）在 mock 下渲染出来的是 1080x1920 的白底合成图；这里按"是否来自网格"区分：
        # 网格格子在 issues 里会被标注（见 candidates_from_grid），但 QA 只看像素 —— 所以用尺寸无关的规则：
        # 第一次调用（网格格）判失败，之后（单帧回退）判通过。
        self.calls.append("grid" if len(self.calls) == 0 else "fallback")
        passed = len(self.calls) > 1
        return KeyframeQaResult(
            passed=passed, product_present=True, product_match=0.9 if passed else 0.2,
            text_intact=passed, issues=[] if passed else ["商品区域与主图颜色差异过大"],
        )


def test_failing_cell_falls_back_to_single_frame_generation() -> None:
    """批次 0 结论：2×2 有约 1/3 概率出现 1 格偏色 → **只重生成那一格**，不整张重来。"""
    scenes = [_scene(index + 1) for index in range(4)]
    qa = _FailingGridQa()
    # 关掉像素锁定兜底：否则 `_qa_candidate` 会先用"贴回原始商品像素"再判一次（那是另一条兜底路径），
    # 这里的用例要测的是"整格不过线 → 只重生成这一格"
    generator = KeyframeGenerator(settings=_settings(keyframe_pixel_lock_fallback=False), qa=qa)
    grid = generator.generate_grid_image(scenes=scenes, product_png=_product_png())
    candidates = generator.candidates_from_grid(
        grid_image=grid, scene=scenes[0], scenes=scenes, product_png=_product_png(), seed=3,
    )
    assert qa.calls == ["grid", "fallback"]                     # 先判网格格、再判单帧回退
    assert candidates[0].mode in {MODE_GRID, "integrated"}      # 回退后走的是单帧路径
    assert any("只重生成这一格" in issue for issue in candidates[0].issues)


# ---- 网格复用（服务层）----


class _FakeStorage:
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}
        self.reads: list[str] = []

    def read_object(self, *, object_key: str):
        self.reads.append(object_key)
        if object_key not in self.objects:
            raise FileNotFoundError(object_key)
        return [self.objects[object_key]]

    def put_bytes(self, *, object_key: str, content: bytes, mime_type: str) -> None:
        self.objects[object_key] = content


class _FakeGenerator:
    def __init__(self, *, verdicts_passed: bool = True) -> None:
        self.grid_calls = 0
        self.cell_calls = 0
        self.verdict_calls = 0
        self.generate_calls = 0
        self._verdicts_passed = verdicts_passed

    def grid_cell_verdicts(self, *, grid_image, product_png):
        """服务层片级判断要用：返回 4 格 verdict（验证 "坏格过半 → 整片回退"）。"""
        self.verdict_calls += 1
        return [
            SimpleNamespace(
                passed=self._verdicts_passed,
                product_match=0.7 if self._verdicts_passed else 0.47,
                product_present=True,
                text_intact=True,
                issues=[] if self._verdicts_passed else ["商品区域与主图颜色差异过大"],
            )
            for _ in range(4)
        ]

    def generate_grid_image(self, **kwargs) -> bytes:
        self.grid_calls += 1
        self.grid_kwargs = kwargs
        return _grid_image(seam=8)

    def generate(self, *, scene, product_png, mode, seed, n, character_png=None):
        """单帧档：整片网格被判"不可用"时，服务层直接走这里。"""
        self.generate_calls += 1
        self.last_character_png = character_png
        return [
            SimpleNamespace(
                mode=mode, image_bytes=_grid_image(seam=8), seed=seed, width=1080, height=1920,
                fallback=None, issues=[f"single {scene.order}"],
                qa=SimpleNamespace(passed=True, issues=[], product_match=0.9),
            )
        ]

    def candidates_from_grid(self, *, grid_image: bytes, scene, scenes, product_png, seed):
        self.cell_calls += 1
        return [SimpleNamespace(mode=MODE_GRID, image_bytes=grid_image, seed=seed, width=1080, height=1920,
                                fallback=None, issues=[f"cell {scene.order}"], qa=SimpleNamespace(
                                    passed=True, issues=[], product_match=0.9))]


def test_grid_is_generated_once_and_reused_for_other_scenes() -> None:
    storage = _FakeStorage()
    generator = _FakeGenerator()
    service = VideoKeyframeApplicationService(storage=storage, generator=generator)
    variant = SimpleNamespace(scenes=[_scene(index + 1) for index in range(4)])
    content_plan = SimpleNamespace(id="cpl_x")

    for order in (1, 2, 3):
        service._generate_grid_candidates(
            content_plan=content_plan, variant=variant, scene=_scene(order),
            product_png=_product_png(), project_id="prj_x", seed=11,
        )

    assert generator.grid_calls == 1                             # 只调一次模型
    assert generator.cell_calls == 3                              # 每镜各取自己的格
    assert generator.generate_calls == 0                          # 好网格不走单帧档
    assert "projects/prj_x/keyframes/grid/cpl_x/grid-2x2.png" in storage.objects
    assert not any(key.endswith(".unusable") for key in storage.objects)   # 好网格不落"整片不可用"标记


class _FixedQa:
    """返回固定质检结果，用来验证"网格档下限"这条标定策略。"""

    provider_name = "fixed-qa"
    model_name = "fixed-qa"

    def __init__(self, *, match: float, text_intact: bool = True) -> None:
        self._match = match
        self._text_intact = text_intact
        self.calls = 0

    def evaluate(self, *, image_bytes: bytes, product_png: bytes) -> KeyframeQaResult:
        self.calls += 1
        passed = self._match >= 0.55          # 单帧档的阈值口径（与 keyframe_qa 一致）
        return KeyframeQaResult(
            passed=passed, product_present=True, product_match=self._match,
            text_intact=self._text_intact, issues=[] if passed else ["商品区域与主图颜色差异过大"],
        )


def test_grid_cell_low_match_falls_back() -> None:
    """`product_match` 对网格档**仍是硬门槛**（2026-10-15 用户肉眼复核推翻了"降级为警示线"的旧判断）。

    依据：瓶子那档四格 0.488~0.498 时，人眼看到"右上格标签文字变成诡异符号 + 四格不是同一瓶"，
    而同商品单帧 0.784 清晰完整 → **低分确实对应坏格**，该格应退回单帧路径。
    """
    scenes = [_scene(index + 1) for index in range(4)]
    qa = _FixedQa(match=0.47)
    generator = KeyframeGenerator(settings=_settings(keyframe_pixel_lock_fallback=False), qa=qa)
    grid = generator.generate_grid_image(scenes=scenes, product_png=_product_png())
    candidates = generator.candidates_from_grid(
        grid_image=grid, scene=scenes[0], scenes=scenes, product_png=_product_png(), seed=1,
    )
    assert qa.calls >= 2                       # 网格判一次 + 单帧回退再判
    assert any("只重生成这一格" in issue for issue in candidates[0].issues)

def test_grid_cell_without_product_still_falls_back() -> None:
    """硬门槛是**结构信号**：商品区域是空的（没入画）→ 仍然只重做那一格。"""
    scenes = [_scene(index + 1) for index in range(4)]

    class _NoProductQa(_FixedQa):
        def evaluate(self, *, image_bytes: bytes, product_png: bytes) -> KeyframeQaResult:
            self.calls += 1
            return KeyframeQaResult(passed=False, product_present=False, product_match=0.47,
                                    text_intact=True, issues=["商品位置是空背景，商品未入画"])

    qa = _NoProductQa(match=0.47)
    generator = KeyframeGenerator(settings=_settings(keyframe_pixel_lock_fallback=False), qa=qa)
    grid = generator.generate_grid_image(scenes=scenes, product_png=_product_png())
    candidates = generator.candidates_from_grid(
        grid_image=grid, scene=scenes[0], scenes=scenes, product_png=_product_png(), seed=1,
    )
    assert qa.calls >= 2                       # 网格判一次 + 单帧回退再判
    assert any("只重生成这一格" in issue for issue in candidates[0].issues)


def test_bad_majority_grid_falls_back_whole_slice_and_marks_unusable() -> None:
    """坏格过半 → **整片改用单帧档**，并落 `整片不可用` 标记。

    依据（2026-10-15 用户肉眼复核）：瓶子那档四格 match 0.488~0.498，人眼看到"右上格标签文字变成诡异符号 +
    四格不是同一瓶"。逐格补救会变成"1 次网格 + 4 次单帧"（比直接走单帧档还贵），所以片级就放弃这片网格。
    """
    storage = _FakeStorage()
    generator = _FakeGenerator(verdicts_passed=False)
    service = VideoKeyframeApplicationService(storage=storage, generator=generator)
    variant = SimpleNamespace(scenes=[_scene(index + 1) for index in range(4)])
    content_plan = SimpleNamespace(id="cpl_x")

    service._generate_grid_candidates(
        content_plan=content_plan, variant=variant, scene=_scene(1),
        product_png=_product_png(), project_id="prj_x", seed=11,
    )

    grid_key = "projects/prj_x/keyframes/grid/cpl_x/grid-2x2.png"
    assert generator.grid_calls == 1                       # 网格只生成这一次（已经花过的钱）
    assert generator.cell_calls == 0                       # 不逐格取用
    assert generator.generate_calls == 1                   # 这一镜直接走单帧档
    assert grid_key not in storage.objects                 # 坏网格不落盘
    assert grid_key + ".unusable" in storage.objects       # 落"整片不可用"标记（带原因）

    # 同一片的后续分镜：不再调模型生成网格，直接单帧
    service._generate_grid_candidates(
        content_plan=content_plan, variant=variant, scene=_scene(2),
        product_png=_product_png(), project_id="prj_x", seed=11,
    )
    assert generator.grid_calls == 1                       # 没重复生成
    assert generator.verdict_calls == 1                    # 没重复逐格质检（那也是费用）
    assert generator.generate_calls == 2                   # 第二镜也是单帧

class _CharacterAwareGenerator(_FakeGenerator):
    def grid_cell_verdicts(self, *, grid_image, product_png):
        return super().grid_cell_verdicts(grid_image=grid_image, product_png=product_png)


def test_service_passes_the_character_sheet_into_keyframe_generation(monkeypatch) -> None:
    """2026-10-16：服务层必须把**项目绑定的出镜人母版**传给关键帧生成（这是"人物×商品"的入口）。

    没绑人 → 一个字节都不传（老项目行为逐字不变）。
    """
    storage = _FakeStorage()
    generator = _FakeGenerator()
    service = VideoKeyframeApplicationService(storage=storage, generator=generator)
    variant = SimpleNamespace(scenes=[_scene(index + 1) for index in range(4)])
    content_plan = SimpleNamespace(id="cpl_x")
    character_bytes = _product_png(size=200)

    monkeypatch.setattr(service, "_character_reference", lambda session, project_id: character_bytes, raising=False)
    service._generate_grid_candidates(
        content_plan=content_plan, variant=variant, scene=_scene(1),
        product_png=_product_png(), project_id="prj_x", seed=7, character_png=character_bytes,
    )
    assert generator.grid_kwargs.get("character_png") == character_bytes

    service._single_frame_generate(scene=_scene(1), product_png=_product_png(), seed=7, character_png=None)
    assert generator.last_character_png is None  # 没绑人时不传（兼容老签名）