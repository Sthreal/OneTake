"""商品段运镜滤镜（zoompan 能力提取）—— 档案 M4-02 / 聊天内代号 S14。

**为什么存在**：商品段的运镜此前内联在 `render_base_video()` 的 `dynamic` 分支里，只有
一种（缓慢推近）。一旦出现"某一段不叠商品图层、但商品仍要有运镜"的需求，就只能再写一份
zoompan —— 本模块把这份能力提取成**参数化**的纯函数，差异一律走参数。

**口径**（与档案 M4-02 第六节 11 项定稿参数逐条对应）：

- **六种运镜**：`zoom_in_slow` / `zoom_out_slow` / `pan_left` / `pan_right` / `ken_burns` / `static`
- **分辨率无关**：本模块只接收画布尺寸，**不决定放大多少**。放大倍数由调用方
  （`renderer.py` 顶部的那个常量）决定，并以**已放大**的尺寸作为 `width` / `height` 传入。
  这样"要不要超采样"这个决定只有一处，运镜模块不含画布策略。
  （本模块**故意不出现那个常量名**——验收口径要求画布策略只在 `renderer.py` 一处，
  由 `tests/unit/test_motion_filters.py::test_motion_module_does_not_decide_supersampling` 永久强制。）
- **平移统一走"每帧速率"口径**：`on * (iw * PAN_RATE)`，即每帧位移 = 画布宽度 × 系数。
  不使用"按时长归一"的写法（那会让同一模块里存在两套语义）。
- **`static` 也用 `zoompan`（`z='1'`）**，使六种运镜的滤镜图形状一致，拼接路径无需特判。
- **非法运镜键回退 `DEFAULT_MOTION`**，不抛错、不返回空串（避免上游静默丢帧）。
- **线性**，不引入 ease-out —— 本切片的安全属性是"零行为变更"（`zoom_in_slow` 的输出必须
  与改造前逐字相同，由 `test_mock_video_renderer.py` 锁定整串）。
- 纯字符串生成、不调 FFmpeg，便于单测。

**滤镜图形状约定**：纯缩放类（`zoom_in_slow` / `zoom_out_slow` / `static`）**不写 x/y**，
沿用 zoompan 的居中默认；平移类与 `ken_burns` 显式给出 x/y。
"""
from __future__ import annotations

DEFAULT_MOTION = "zoom_in_slow"

# 六种运镜的键清单（顺序即 UI 展示顺序）
MOTIONS: tuple[str, ...] = (
    "zoom_in_slow",
    "zoom_out_slow",
    "pan_left",
    "pan_right",
    "ken_burns",
    "static",
)

# 推近/拉远的幅度上限（自 renderer.py 迁入：它本就属于运镜参数，不属于渲染画布策略）
ZOOM_MAX_SCALE = 1.05
ZOOM_SCALE_RANGE = ZOOM_MAX_SCALE - 1

# 平移类运镜的每帧速率系数：每帧位移 = 画布宽度 × 该系数。
#
# 标定推导（档案 M4-02 第 6 项「按本项目标定（1080 宽 + 5 秒）」）：
#   平移需要 zoom>1 才有行程可用；取 z=ZOOM_MAX_SCALE 时可用行程 = (1 - 1/1.05) × 宽度
#   = 0.047619 × 宽度。按「1080 宽 + 5 秒 + 30fps 走满行程」反推每帧速率：
#   0.047619 / (5 × 30) = 0.00031746 → 取 0.000317。
# 不照搬外部项目的 iw*0.00046 —— 那依赖对方的画布与时长假设。
PAN_RATE = 0.000317

# 纯缩放类运镜：z 表达式模板（线性，不缓动）
_PURE_ZOOM = {"zoom_in_slow", "zoom_out_slow", "static"}


def _zoom_step(fps: int, duration_seconds: float) -> float:
    """每帧的缩放增量（线性）。与改造前 renderer.py 的算式完全相同。"""
    total_frames = max(1.0, duration_seconds * fps)
    return ZOOM_SCALE_RANGE / total_frames


def _zoom_expressions(motion: str, *, fps: int, duration_seconds: float) -> tuple[str, str | None, str | None]:
    """返回 (z 表达式, x 表达式或 None, y 表达式或 None)。"""
    step = _zoom_step(fps, duration_seconds)
    if motion == "zoom_in_slow":
        return f"min(1+{step:.8f}*on,{ZOOM_MAX_SCALE})", None, None
    if motion == "zoom_out_slow":
        return f"max({ZOOM_MAX_SCALE}-{step:.8f}*on,1)", None, None
    if motion == "static":
        return "1", None, None
    # 平移类与 ken_burns：z 固定为 ZOOM_MAX_SCALE 以留出可平移的行程
    # （x 会夹在有效行程内，越界不会报错、也不会把画面推出画布）
    room = "iw-iw/zoom"
    centered_y = "(ih-ih/zoom)/2"
    if motion == "pan_left":
        # 取景窗从右端向左移动 → 观感上画面向右移动（即镜头向左摇）
        return f"{ZOOM_MAX_SCALE}", f"max({room}-on*(iw*{PAN_RATE}),0)", centered_y
    if motion == "pan_right":
        return f"{ZOOM_MAX_SCALE}", f"min(on*(iw*{PAN_RATE}),{room})", centered_y
    # ken_burns：缓慢推近 + 同时右移（经典肯·伯恩斯效果）
    return f"min(1+{step:.8f}*on,{ZOOM_MAX_SCALE})", f"min(on*(iw*{PAN_RATE}),iw-iw/zoom)", centered_y


def build_motion_filter(
    motion: str,
    *,
    width: int,
    height: int,
    fps: int,
    duration_seconds: float,
) -> str:
    """生成一段 `zoompan=...` 滤镜（不含尾逗号），供调用方拼进滤镜链。

    - `width` / `height` 是**画布尺寸**，本函数不做任何放大（超采样由调用方决定）。
    - 非法 `motion` 回退 `DEFAULT_MOTION`，绝不抛错、绝不返回空串。
    """
    key = motion if motion in MOTIONS else DEFAULT_MOTION
    z_expr, x_expr, y_expr = _zoom_expressions(key, fps=fps, duration_seconds=duration_seconds)
    parts = [f"zoompan=z='{z_expr}'"]
    if x_expr is not None:
        parts.append(f"x='{x_expr}'")
    if y_expr is not None:
        parts.append(f"y='{y_expr}'")
    parts.append(f"d=1:s={width}x{height}:fps={fps}")
    return ":".join(parts)