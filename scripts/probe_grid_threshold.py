"""九宫格格子阈值标定（**默认 dry-run；加 --yes 才真花钱**）。

要回答的问题：`keyframe_qa` 的 `product_match` 阈值（0.55）是给**单张 1080×1920 关键帧**标定的，
而九宫格的格子经 1.56× 上采样后是否系统性更低？低多少？据此把网格档的下限**定死**（或改成相对口径）。

做法（每张商品图 **2 次调用**）：
1. 走**生产**的九宫格路径 `KeyframeGenerator.generate_grid_image()` → `grid_split.split_grid()`（含 1.56× 归一化）
   → 逐格 `keyframe_qa` → 记录 4 格的 `product_match` / `product_present` / `text_intact`；
2. 走**生产**的单帧路径 `KeyframeGenerator.generate(mode="integrated")` → 记录那 1 张的 `product_match`。

⚠️ 边界：本脚本**不走产品入口**，因此**不受费用审批闸保护** —— 必须由人显式 `--yes`，且会先打印
"几张图 / 几次调用 / 预估金额"。单帧基线用 `keyframe_pixel_lock_fallback=False`，避免"贴回原始像素"
把单帧的原始分数盖掉。

用法（仓库根目录）：
    python scripts/probe_grid_threshold.py --dir "D:\\download new\\ai_coding\\_stock_probe"      # dry-run
    python scripts/probe_grid_threshold.py --dir "D:\\download new\\ai_coding\\_stock_probe" --yes
"""
from __future__ import annotations

import argparse
import io
import sys
from dataclasses import dataclass
from pathlib import Path

from PIL import Image

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "apps" / "api" / "src"))

from onetake_api.config import get_settings  # noqa: E402
from onetake_api.integrations.product_scene import grid_split  # noqa: E402
from onetake_api.integrations.product_scene.keyframe_integrated import (  # noqa: E402
    GRID_COLS,
    GRID_ROWS,
    MODE_INTEGRATED,
    KeyframeGenerator,
)
from onetake_api.integrations.product_scene.keyframe_qa import get_keyframe_qa  # noqa: E402
from onetake_api.modules.content_plan.domain import ContentScene  # noqa: E402

RECORD_PATH = REPO_ROOT / "docs" / "九宫格格子阈值标定记录.md"
SUFFIXES = {".jpg", ".jpeg", ".png", ".webp"}
SEED = 1001


@dataclass
class SampleResult:
    name: str
    frame_match: float
    frame_passed: bool
    cell_matches: list[float]
    cell_present: list[bool]
    cell_intact: list[bool]
    grid_size: tuple[int, int]
    cell_size: tuple[int, int]
    seam_detected: bool

    @property
    def cell_mean(self) -> float:
        return sum(self.cell_matches) / max(1, len(self.cell_matches))

    @property
    def ratio(self) -> float:
        return self.cell_mean / self.frame_match if self.frame_match else 0.0


def _scene() -> ContentScene:
    """一个中性的 product_reveal 场景（与生产同口径的 prompt/风格）。"""
    return ContentScene(
        scene_id="scene_probe", order=1, purpose="selling_point", script_excerpt="（探针）",
        start_seconds=0.0, end_seconds=4.0, shot_type="product_reveal", prompt="展示商品主体",
        overlay_product=True, product_position="center", background_style="clean", template_id="clean",
        subtitle_segment_ids=[1], qa_rules=[], visual_goal="product_reveal",
        subject_action="缓慢推近", camera_move="push_in", product_mode="overlay", transition="fade",
    )


def _images(directory: Path) -> list[Path]:
    return sorted(p for p in directory.iterdir() if p.is_file() and p.suffix.lower() in SUFFIXES)


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="九宫格格子阈值标定（默认 dry-run）")
    parser.add_argument("--dir", required=True, help="商品图目录（白底/透明底）")
    parser.add_argument("--yes", action="store_true", help="真的发起调用（会产生费用）")
    parser.add_argument("--seed", type=int, default=SEED)
    parser.add_argument("--save-images", action="store_true", help="把整图/单帧/逐格落盘（默认只记数值）")
    args = parser.parse_args(argv[1:])

    directory = Path(args.dir).expanduser()
    if not directory.is_dir():
        print(f"❌ 目录不存在：{directory}")
        return 2
    images = _images(directory)
    if not images:
        print(f"❌ 目录里没有图片（支持：{', '.join(sorted(SUFFIXES))}）")
        return 2

    settings = get_settings()
    unit = settings.qwen_image_price_per_call
    calls = len(images) * 2
    estimate = round(calls * float(unit), 2) if unit not in (None, "") else None
    print("=== 九宫格格子阈值标定（默认 dry-run）===")
    print(f"  模型            : {settings.image_edit_model}（生产同款）")
    print(f"  MOCK_PROVIDERS  : {settings.mock_providers}"
          f"{'（⚠️ 仍会直连真实接口：本脚本不走产品入口）' if settings.mock_providers else ''}")
    print(f"  商品图          : {len(images)} 张 → {[p.name for p in images]}")
    print(f"  每张            : 九宫格 1 次 + 单帧 1 次 = 2 次 → 共 **{calls} 次调用**")
    print(f"  预估费用        : {estimate if estimate is not None else '未知（QWEN_IMAGE_PRICE_PER_CALL 未配置）'} 元")
    print(f"  记录            : {RECORD_PATH.relative_to(REPO_ROOT)}")
    if not args.yes:
        print("\n（dry-run：没有发起任何调用。确认无误后加 --yes 真跑。）")
        return 0
    if not settings.dashscope_api_key:
        print("❌ 缺少 DASHSCOPE_API_KEY，无法真跑。")
        return 2

    # 单帧基线的口径：关掉 pixel_lock 兜底，避免"贴回原始像素"盖掉原始分数
    baseline_settings = settings.model_copy(update={"keyframe_pixel_lock_fallback": False})
    generator = KeyframeGenerator(settings=baseline_settings)
    qa = get_keyframe_qa(settings)
    scene = _scene()
    results: list[SampleResult] = []
    out_dir = REPO_ROOT / "outputs" / "grid-probe" / "threshold-probe"
    if args.save_images:
        out_dir.mkdir(parents=True, exist_ok=True)

    for index, path in enumerate(images, start=1):
        png = path.read_bytes()
        print(f"\n--- [{index}/{len(images)}] {path.name} → 九宫格 + 单帧（各 1 次）…", flush=True)
        grid_image = generator.generate_grid_image(scenes=[scene], product_png=png, seed=args.seed)
        if args.save_images:
            (out_dir / f"{path.stem}-grid.png").write_bytes(grid_image)
        payloads, split = grid_split.split_grid(grid_image, rows=GRID_ROWS, cols=GRID_COLS)
        cell_matches, cell_present, cell_intact = [], [], []
        for cell_index, payload in enumerate(payloads, start=1):
            if args.save_images:
                (out_dir / f"{path.stem}-cell{cell_index}.png").write_bytes(payload)
            verdict = qa.evaluate(image_bytes=payload, product_png=png)
            cell_matches.append(float(verdict.product_match))
            cell_present.append(bool(verdict.product_present))
            cell_intact.append(bool(verdict.text_intact))
        generated = generator.generate(
            scene=scene, product_png=png, mode=MODE_INTEGRATED, n=1, seed=args.seed,
        )
        if args.save_images:
            (out_dir / f"{path.stem}-frame.png").write_bytes(generated[0].image_bytes)
        frame = generated[0]
        sample = SampleResult(
            name=path.name, frame_match=float(frame.qa.product_match), frame_passed=bool(frame.qa.passed),
            cell_matches=cell_matches, cell_present=cell_present, cell_intact=cell_intact,
            grid_size=split.grid_size, cell_size=(split.cells[0].width, split.cells[0].height),
            seam_detected=split.seam_detected,
        )
        results.append(sample)
        print(f"    单帧 match={sample.frame_match:.3f}（passed={sample.frame_passed}）｜"
              f"四格 match={[round(v, 3) for v in sample.cell_matches]} 均值={sample.cell_mean:.3f}｜"
              f"比值={sample.ratio:.3f}")

    lines = [
        "# 九宫格格子阈值标定记录", "",
        f"> 商品图目录：`{directory}`（{len(images)} 张）｜模型：`{settings.image_edit_model}`｜seed：{args.seed}",
        "> **仅本地文档，禁止推送 GitHub**。",
        f"> 调用：{len(images)} 张 × 2 次 = **{calls} 次**（九宫格 + 单帧）≈ {estimate} 元"
        f"（单价 `QWEN_IMAGE_PRICE_PER_CALL`）", "",
        "## 逐图结果", "",
        "| 商品图 | 单帧 match | 单帧 passed | 四格 match | 格均值 | **格/单帧** | 整图 | 格 | 白缝 |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for item in results:
        lines.append(
            f"| {item.name} | {item.frame_match:.3f} | {'✅' if item.frame_passed else '❌'} | "
            f"{', '.join(f'{v:.3f}' for v in item.cell_matches)} | {item.cell_mean:.3f} | "
            f"**{item.ratio:.3f}** | {item.grid_size[0]}x{item.grid_size[1]} | "
            f"{item.cell_size[0]}x{item.cell_size[1]} | {'命中' if item.seam_detected else '未命中'} |"
        )
    ratios = [item.ratio for item in results]
    cells = [v for item in results for v in item.cell_matches]
    frames = [item.frame_match for item in results]
    lines += [
        "", "## 汇总", "",
        f"- 单帧 match：{min(frames):.3f} ~ {max(frames):.3f}（均值 {sum(frames)/len(frames):.3f}）",
        f"- 格子 match：{min(cells):.3f} ~ {max(cells):.3f}（均值 {sum(cells)/len(cells):.3f}）",
        f"- **格子/单帧 比值**：{min(ratios):.3f} ~ {max(ratios):.3f}（均值 {sum(ratios)/len(ratios):.3f}）",
        "", "## 判定（人工/后处理填）", "",
        "- 结论 A（绝对值口径）：网格档下限取 ____________",
        "- 结论 B（相对口径）：格子 ≥ ______ × 单帧基线 —— 比值区间是否够窄？____________",
        "- 单帧低于 0.55 的样本怎么处理（要不要也降级/人工复核）：____________",
        "", "产物：`outputs/grid-probe/threshold-probe/`（若需原图请让脚本落盘，当前只记录数值）", "",
    ]
    RECORD_PATH.parent.mkdir(parents=True, exist_ok=True)
    RECORD_PATH.write_text("\n".join(lines), encoding="utf-8")
    print(f"\n✅ 记录已写：{RECORD_PATH.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))