"""九宫格裁切（批次 3）：**唯一的切分算法**。

批次 0 的实测结论直接决定了这里的三条写法：
1. **格数用 2×2**（本仓 4 镜；3×3 会白留 5 格且上采样从 1.56× 恶化到 2.34×）；
2. **裁切按实测白缝定位**（缝内缘 + 2px），**不用**固定 2% 内缩 —— 实测白缝宽度在 6~26px 之间，
   固定 2%（1080 宽下 13.8px）只是"刚好"躲开最宽的那种；
3. 单格要**上采样到生产关键帧规格**（1440×2560 的 2×2 → 单格 692×1228 → 1.56× 到 1080×1920）；
   放大后必须**再判一次**质量（放大是九宫格的真实代价）。

找不到白缝时退化为"名义等分 + 2% 内缩"（并把 `seam_detected=False` 如实带出来）。
"""
from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO

from PIL import Image, ImageOps

from onetake_api.platform.errors import DomainError

NEAR_WHITE_THRESHOLD = 235
SEAM_COVERAGE_RATIO = 0.92
# 按实测缝定位时，**最多**允许往格内让出这么多（相对单格尺寸）。
# 为什么需要这个上限：白底商品/白墙这类"大块白区"会和细缝连成一条长条，
# 若不加限制就会一口气切掉十几 % 的画面内容。批次 0 实测真实缝宽 6~26px（远小于 5%），
# 所以这个上限只在"白区与缝粘连"的病态情况下起作用 —— 那时"少切一点内容"比"留下一条缝"或"切掉 12%"都更可取。
MAX_SEAM_TRIM_RATIO = 0.05
# 单格必须是 9:16（整图 9:16 + 等分 → 格本来就是 9:16）。裁缝之后如果安全区不是 9:16，
# 就在安全区**内部**取最大的居中 9:16 框 —— 宁可少留一点边缘内容，也不要拉伸变形或留下缝。
CELL_ASPECT = 9 / 16
DEFAULT_SEAM_INSET_PX = 2
FALLBACK_INSET_RATIO = 0.02
TARGET_WIDTH = 1080
TARGET_HEIGHT = 1920


class GridSplitError(DomainError):
    code = "GRID_SPLIT_FAILED"
    http_status = 502
    retryable = True


@dataclass(frozen=True)
class GridCell:
    index: int                 # 0 基
    row: int
    column: int
    box: tuple[int, int, int, int]
    width: int
    height: int


@dataclass(frozen=True)
class GridSplitResult:
    cells: list[GridCell]
    vertical_seams: list[tuple[int, int]]
    horizontal_seams: list[tuple[int, int]]
    seam_detected: bool
    grid_size: tuple[int, int]


def _near_white_runs(values: list[bool], *, coverage: float) -> list[tuple[int, int]]:
    runs: list[tuple[int, int]] = []
    start: int | None = None
    for index, flag in enumerate(values):
        if flag and start is None:
            start = index
        elif not flag and start is not None:
            runs.append((start, index - 1))
            start = None
    if start is not None:
        runs.append((start, len(values) - 1))
    return runs


def detect_seams(image: Image.Image) -> tuple[list[tuple[int, int]], list[tuple[int, int]]]:
    """扫出近白长条（行/列）——即格与格之间的分隔缝。"""
    gray = image.convert("L")
    width, height = gray.size
    pixels = gray.load()
    column_coverage: list[bool] = []
    for x in range(width):
        white = sum(1 for y in range(height) if pixels[x, y] >= NEAR_WHITE_THRESHOLD)
        column_coverage.append(white / height >= SEAM_COVERAGE_RATIO)
    row_coverage: list[bool] = []
    for y in range(height):
        white = sum(1 for x in range(width) if pixels[x, y] >= NEAR_WHITE_THRESHOLD)
        row_coverage.append(white / width >= SEAM_COVERAGE_RATIO)
    return (
        _near_white_runs(column_coverage, coverage=SEAM_COVERAGE_RATIO),
        _near_white_runs(row_coverage, coverage=SEAM_COVERAGE_RATIO),
    )


def _fit_aspect(box: tuple[int, int, int, int], *, aspect: float = CELL_ASPECT) -> tuple[int, int, int, int]:
    """在 box 内部取最大的居中 `aspect` 矩形（不放大、只裁小）。"""
    left, top, right, bottom = box
    width, height = right - left, bottom - top
    if width <= 0 or height <= 0:
        raise GridSplitError("九宫格裁切框非法（宽或高为 0）")
    if width / height > aspect:
        target_width = max(1, int(round(height * aspect)))
        offset = (width - target_width) // 2
        return (left + offset, top, left + offset + target_width, bottom)
    target_height = max(1, int(round(width / aspect)))
    offset = (height - target_height) // 2
    return (left, top + offset, right, top + offset + target_height)

def plan_cells(
    width: int, height: int, *, rows: int, cols: int,
    vertical_seams: list[tuple[int, int]] | None = None,
    horizontal_seams: list[tuple[int, int]] | None = None,
) -> list[GridCell]:
    """算出每格的裁切框：有实测白缝就用缝内缘 + 2px，没有就退化为名义等分 + 2% 内缩。"""

    def _boundaries(size: int, count: int, seams: list[tuple[int, int]] | None) -> list[tuple[int, int]]:
        """返回 count+1 个边界（起点/终点用 0/size；内部边界用实测缝或名义位置）。"""
        bounds: list[tuple[int, int]] = [(0, 0)]
        for index in range(1, count):
            nominal = index * size / count
            if seams:
                nearest = min(seams, key=lambda run: abs((run[0] + run[1]) / 2 - nominal))
                if abs((nearest[0] + nearest[1]) / 2 - nominal) <= size / count / 2:
                    # 语义：元组第一位是"左/上格的**右/下边界**"，第二位是"右/下格的**左/上边界**" →
                    # 左格停在缝**之前**、右格从缝**之后**开始（批次 0 实测 26px 缝，必须整条排除），
                    # 且让出的距离受 MAX_SEAM_TRIM_RATIO 限制（防"白区与缝粘连"把画面切掉一大块）
                    limit = size / count * MAX_SEAM_TRIM_RATIO
                    bounds.append((
                        max(0, nearest[0] - DEFAULT_SEAM_INSET_PX, nominal - limit),
                        min(size, nearest[1] + DEFAULT_SEAM_INSET_PX, nominal + limit),
                    ))
                    continue
            inset = size / count * FALLBACK_INSET_RATIO
            bounds.append((round(nominal - inset), round(nominal + inset)))
        bounds.append((size, size))
        return bounds

    columns = _boundaries(width, cols, vertical_seams)
    rows_bounds = _boundaries(height, rows, horizontal_seams)
    cells: list[GridCell] = []
    index = 0
    for row in range(rows):
        for column in range(cols):
            left = max(0, columns[column][1])
            right = min(width, columns[column + 1][0])
            top = max(0, rows_bounds[row][1])
            bottom = min(height, rows_bounds[row + 1][0])
            if right - left <= 0 or bottom - top <= 0:
                raise GridSplitError("九宫格裁切框非法（宽或高为 0）")
            fitted = _fit_aspect((left, top, right, bottom))
            cells.append(GridCell(
                index=index, row=row, column=column, box=fitted,
                width=fitted[2] - fitted[0], height=fitted[3] - fitted[1],
            ))
            index += 1
    return cells


def split_grid(
    grid_bytes: bytes, *, rows: int, cols: int,
    target_width: int = TARGET_WIDTH, target_height: int = TARGET_HEIGHT,
) -> tuple[list[bytes], GridSplitResult]:
    """把整图切成 cells 张**已归一化到目标规格**的 PNG（逐格 LANCZOS 放大）。"""
    if not grid_bytes:
        raise GridSplitError("九宫格输入为空")
    try:
        with Image.open(BytesIO(grid_bytes)) as source:
            grid = ImageOps.exif_transpose(source).convert("RGB")
    except (OSError, ValueError) as exc:
        raise GridSplitError("九宫格图片无法解析") from exc
    width, height = grid.size
    vertical_seams, horizontal_seams = detect_seams(grid)
    cells = plan_cells(
        width, height, rows=rows, cols=cols,
        vertical_seams=vertical_seams, horizontal_seams=horizontal_seams,
    )
    payloads: list[bytes] = []
    for cell in cells:
        cropped = grid.crop(cell.box)
        if (cropped.width, cropped.height) != (target_width, target_height):
            cropped = cropped.resize((target_width, target_height), Image.LANCZOS)
        buffer = BytesIO()
        cropped.save(buffer, format="PNG")
        payloads.append(buffer.getvalue())
    result = GridSplitResult(
        cells=cells, vertical_seams=vertical_seams, horizontal_seams=horizontal_seams,
        seam_detected=bool(vertical_seams) and bool(horizontal_seams), grid_size=(width, height),
    )
    return payloads, result