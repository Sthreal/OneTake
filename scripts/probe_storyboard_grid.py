"""批次 0 探测：九宫格小样验证（**默认 dry-run；加 --yes 才会真的调模型花钱**）。

用法（仓库根目录）：

    python scripts/probe_storyboard_grid.py                 # 只打印计划与预估费用
    python scripts/probe_storyboard_grid.py --yes           # 真跑（6 张图 ≈ ¥3，按你的单价配置）
    python scripts/probe_storyboard_grid.py --sizes 1440*2560,2160*3840 --runs 2 --yes
    python scripts/probe_storyboard_grid.py --mode 3x3 --yes

要回答的四个问题（对应 `docs/核心链路能力补齐方案.md` 批次 0 的 5 条判据 + 2026-10-14 的四项拍板）：

1. 生产同款模型（`IMAGE_EDIT_MODEL`）能否稳定输出**整图 9:16** 的等分网格？格与格之间有没有多余装饰？
2. 2x2 / 3x3 各自的**单格实际像素**是多少 → 要放大多少倍才到 1080x1920（越高越伤商品文字）？
3. 裁切后的单格能不能当关键帧：商品存在 / 商品匹配 / 文字清晰 —— 用**生产同一套** `keyframe_qa` 判据，
   以及**放大到 1080x1920 之后**再判一次（这是本切片新增的关键判据：九宫格的真实代价在放大）。
4. 格内有没有跨格串味（按 2% 内缩裁切后，抽检每条边的"贴边非背景像素"比例）。

为什么默认 dry-run：本脚本**不走产品入口**，因此也不经过 S8 的费用审批闸 —— 这类"工程探测"
必须由人显式点头，且脚本会把「调用次数 / 模型 / 预估费用」先打出来。真跑时每次调用的结果、
实际像素、逐格判定都会写进 `docs/九宫格小样验证记录.md`（该文档属"仅本地"，不上传）。

边界（与方案一致）：**不写产品代码**；裁切逻辑这里是探测用的临时实现，批次 3 落地时必须
收敛到唯一的 `product_scene/grid_split.py`（本脚本届时改为复用，不再自己算）。
"""
from __future__ import annotations

import argparse
import io
import os
import sys
from dataclasses import dataclass
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "apps" / "api" / "src"))

from PIL import Image  # noqa: E402

from onetake_api.config import get_settings  # noqa: E402
from onetake_api.integrations.product_scene.keyframe_qa import get_keyframe_qa  # noqa: E402
from onetake_api.integrations.qwen_image_edit.adapter import QwenImageEditAdapter  # noqa: E402

DEFAULT_PRODUCT = REPO_ROOT / "lipstick_white_bg.jpg"
DEFAULT_OUT = REPO_ROOT / "outputs" / "grid-probe"
RECORD_PATH = REPO_ROOT / "docs" / "九宫格小样验证记录.md"
INSET_RATIO = 0.02          # 每边内缩 2%，削掉分隔缝残渣（与参考实现同口径）
TARGET_W, TARGET_H = 1080, 1920


@dataclass(frozen=True)
class CellResult:
    index: int
    box: tuple[int, int, int, int]
    width: int
    height: int
    aspect_ok: bool
    product_present: bool | None
    product_match: float | None
    text_intact: bool | None
    product_match_after_upscale: float | None
    text_intact_after_upscale: bool | None
    edge_bleed_ratio: float


def _grid_prompt(rows: int, cols: int) -> str:
    """自己写的中文提示词（只借鉴方法，不照抄任何源码）。

    三条硬约束来自参考实现的实战经验：整图 9:16（格即 9:16）、极细分隔缝、**格内不许有文字/编号/边框**
    （格会被裁出来当关键帧，任何文字都会污染画面）。
    """
    total = rows * cols
    return "\n".join([
        f"一张 {rows}x{cols} 等分的分镜图（共 {total} 个格）；**整图必须是 9:16 竖版**，每格因此也是 9:16 竖构图。",
        "格与格之间只留一条极细的白色分隔缝（细到裁切时内缩 2% 即可去掉），不要粗边框、不要外框。",
        f"{total} 个格是同一支带货视频的不同镜头：同一商品、同一空间、同一光线方向与色调，商品外观与包装配色在各格间保持一致。",
        "每格是一个独立镜头的画面，构图按竖屏设计；每格都是该镜动作即将开始前一瞬的定格。",
        "画面里**不得出现任何文字、字幕、编号、数字、水印、边框装饰或分格线以外的线条**。",
        "商品实拍图见输入图 1：各格中的商品外观、配色与包装必须与其完全一致，不得变形、重绘或改色。",
    ])


def _plan_cells(width: int, height: int, rows: int, cols: int) -> list[tuple[int, int, int, int]]:
    cell_w, cell_h = width / cols, height / rows
    dx, dy = cell_w * INSET_RATIO, cell_h * INSET_RATIO
    boxes = []
    for r in range(rows):
        for c in range(cols):
            x = round(c * cell_w + dx)
            y = round(r * cell_h + dy)
            boxes.append((x, y, round(x + cell_w - 2 * dx), round(y + cell_h - 2 * dy)))
    return boxes


def _edge_bleed(image: Image.Image) -> float:
    """贴边像素比例：四边各取 2px 带，统计"明显不是白缝"的像素占比，用来发现跨格串味。"""
    gray = image.convert("L")
    w, h = gray.size
    band = 2
    pixels = []
    px = gray.load()
    for x in range(w):
        for y in list(range(band)) + list(range(h - band, h)):
            pixels.append(px[x, y])
    for y in range(h):
        for x in list(range(band)) + list(range(w - band, w)):
            pixels.append(px[x, y])
    if not pixels:
        return 0.0
    return round(sum(1 for v in pixels if v < 220) / len(pixels), 4)


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="批次 0：九宫格小样验证（默认 dry-run）")
    parser.add_argument("--mode", choices=("2x2", "3x3", "both"), default="both")
    parser.add_argument("--runs", type=int, default=3, help="每种网格跑几次（每次 1 张图）")
    parser.add_argument("--sizes", default="1440*2560", help="整图尺寸候选，逗号分隔，如 1440*2560,2160*3840")
    parser.add_argument("--product", default=str(DEFAULT_PRODUCT), help="商品实拍图（默认仓库根的口红图）")
    parser.add_argument("--out", default=str(DEFAULT_OUT), help="产物目录（默认 outputs/grid-probe，已被 gitignore）")
    parser.add_argument("--yes", action="store_true", help="真的发起调用（会产生费用）")
    args = parser.parse_args(argv[1:])

    settings = get_settings()
    product_path = Path(args.product)
    if not product_path.is_file():
        print(f"❌ 商品图不存在：{product_path}（用 --product 指定）")
        return 2
    product_png = product_path.read_bytes()

    modes = [("2x2", 2, 2), ("3x3", 3, 3)] if args.mode == "both" else [((args.mode), int(args.mode[0]), int(args.mode[2]))]
    sizes = [s.strip() for s in args.sizes.split(",") if s.strip()]
    calls = len(modes) * len(sizes) * max(1, args.runs)
    unit = settings.qwen_image_price_per_call
    est = None
    if unit not in (None, ""):
        est = round(calls * float(unit), 2)

    print("=== 批次 0：九宫格小样验证（默认 dry-run）===")
    print(f"  模型           : {settings.image_edit_model}（生产同款：关键帧走的就是它）")
    print(f"  endpoint       : {'已配置' if settings.image_edit_endpoint else '缺失'}")
    print(f"  API Key        : {'已配置' if settings.dashscope_api_key else '缺失（真实调用会失败）'}")
    print(f"  网格 x 尺寸    : {[m[0] for m in modes]} x {sizes}")
    print(f"  每种组合跑     : {args.runs} 次 → 共 **{calls} 张图 / {calls} 次调用**")
    print(f"  预估费用       : {est if est is not None else '未知（QWEN_IMAGE_PRICE_PER_CALL 未配置）'} 元"
          f"{'（按你 .env 里的单价）' if est is not None else ''}")
    print(f"  产物           : {args.out}")
    print(f"  记录           : {RECORD_PATH.relative_to(REPO_ROOT)}")
    print(f"  Mock 安全锁    : MOCK_PROVIDERS={settings.mock_providers}")
    if settings.mock_providers:
        print("  ⚠️ 当前 MOCK_PROVIDERS=true → 本脚本仍会直连真实接口（它不走产品入口、不受安全锁保护）。")
    if not args.yes:
        print("\n（dry-run：没有发起任何调用。确认无误后加 --yes 真跑。）")
        return 0
    if not settings.dashscope_api_key:
        print("❌ 缺少 DASHSCOPE_API_KEY，无法真跑。")
        return 2

    adapter = QwenImageEditAdapter(
        api_key=settings.dashscope_api_key,
        endpoint=settings.image_edit_endpoint,
        model=settings.image_edit_model,
    )
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    qa = get_keyframe_qa(settings)   # 与生产同一条 QA 判据（rules 档零成本）
    rows_md: list[str] = []

    for name, rows, cols in modes:
        for size in sizes:
            for run in range(1, max(1, args.runs) + 1):
                seed = 1000 + run
                print(f"\n--- {name} / {size} / run{run}（seed={seed}）→ 调用模型…", flush=True)
                try:
                    results = adapter.generate(
                        images=[(product_png, "image/png")],
                        prompt=_grid_prompt(rows, cols),
                        negative_prompt="文字、字幕、编号、水印、粗边框、格线以外的装饰",
                        n=1,
                        seed=seed,
                        size=size,
                    )
                except Exception as exc:  # noqa: BLE001 - 探测脚本要把真实错误原样带出来
                    print(f"    ❌ 调用失败：{type(exc).__name__}: {exc}")
                    rows_md.append(f"| {name} | {size} | run{run} | ❌ 调用失败 | {type(exc).__name__} | — | — | — |")
                    continue
                if not results:
                    print("    ❌ 返回空结果")
                    rows_md.append(f"| {name} | {size} | run{run} | ❌ 空结果 | — | — | — | — |")
                    continue

                grid_bytes = results[0]
                grid_path = out_dir / f"grid-{name}-{size.replace('*', 'x')}-run{run}.png"
                grid_path.write_bytes(grid_bytes)
                with Image.open(io.BytesIO(grid_bytes)) as grid:
                    gw, gh = grid.size
                    aspect = gw / gh if gh else 0
                    aspect_ok = abs(aspect - 9 / 16) <= 0.02
                    boxes = _plan_cells(gw, gh, rows, cols)
                    cells: list[CellResult] = []
                    for index, box in enumerate(boxes, start=1):
                        cell = grid.crop(box).convert("RGB")
                        cw, ch = cell.size
                        cell_path = out_dir / f"cell-{name}-{size.replace('*', 'x')}-run{run}-{index}.png"
                        cell.save(cell_path, format="PNG")
                        verdict = qa.evaluate(image_bytes=cell_path.read_bytes(), product_png=product_png)
                        # 放大到生产关键帧规格后再判一次（九宫格的真实代价就在这里）
                        upscaled = cell.resize((TARGET_W, TARGET_H), Image.LANCZOS)
                        up_path = out_dir / f"cell-{name}-{size.replace('*', 'x')}-run{run}-{index}-1080x1920.png"
                        upscaled.save(up_path, format="PNG")
                        up_verdict = qa.evaluate(image_bytes=up_path.read_bytes(), product_png=product_png)
                        cells.append(CellResult(
                            index=index, box=box, width=cw, height=ch,
                            aspect_ok=abs((cw / ch if ch else 0) - 9 / 16) <= 0.03,
                            product_present=getattr(verdict, "product_present", None),
                            product_match=getattr(verdict, "product_match", None),
                            text_intact=getattr(verdict, "text_intact", None),
                            product_match_after_upscale=getattr(up_verdict, "product_match", None),
                            text_intact_after_upscale=getattr(up_verdict, "text_intact", None),
                            edge_bleed_ratio=_edge_bleed(cell),
                        ))
                keep = [c for c in cells if (c.text_intact_after_upscale is not False)]
                print(f"    整图 {gw}x{gh}（9:16={aspect_ok}）| 单格 {cells[0].width}x{cells[0].height}"
                      f"| 上采样 {TARGET_W / max(1, cells[0].width):.2f}x"
                      f"| 放大后仍清晰 {len(keep)}/{len(cells)} 格")
                rows_md.append(
                    f"| {name} | {size} | run{run} | ✅ {gw}x{gh}（9:16={aspect_ok}）| "
                    f"{cells[0].width}x{cells[0].height}（9:16={cells[0].aspect_ok}）| "
                    f"{TARGET_W / max(1, cells[0].width):.2f}x | {len(keep)}/{len(cells)} |"
                )

    record = [
        "# 九宫格小样验证记录（批次 0）", "",
        f"> 运行时间：{__import__('datetime').datetime.now().strftime('%Y-%m-%d %H:%M')}"
        f" ｜ 模型：`{settings.image_edit_model}` ｜ 商品图：`{product_path.name}`",
        "> **仅本地文档，禁止推送 GitHub**（本仓 `docs/` 下的方案与记录一律不上传）。", "",
        "## 逐次结果", "",
        "| 网格 | 整图请求尺寸 | 次 | 实际整图 | 单格 | 放大到 1080x1920 | 放大后仍清晰 |",
        "|---|---|---|---|---|---|---|", *rows_md, "",
        "## 判定与结论（人工填）", "",
        "- 判据 1 真的 3x3/2x2 等分（偏差 <2%）：",
        "- 判据 2 每格都有商品：",
        "- 判据 3 商品跨格一致：",
        "- 判据 4 格内无跨格串味：",
        "- 判据 5 裁切后单格可用（含**放大到 1080x1920 后**文字是否仍清晰）：",
        "- 结论分支：全通过 → 批次 3 按九宫格；部分通过 → 只取空间同源；不通过 → 批次 3 不做。", "",
        f"产物目录：`{out_dir.relative_to(REPO_ROOT)}`（含整图与逐格裁切、以及放大后的副本）", "",
    ]
    RECORD_PATH.parent.mkdir(parents=True, exist_ok=True)
    RECORD_PATH.write_text("\n".join(record), encoding="utf-8")
    print(f"\n✅ 记录已写：{RECORD_PATH.relative_to(REPO_ROOT)}")
    print(f"✅ 产物：{out_dir}（整图 / 逐格 / 放大后副本）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))