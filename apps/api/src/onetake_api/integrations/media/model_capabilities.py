"""模型能力预检（S6 6e）：**数据源是我们自己的适配器契约**，不是厂商文档的转述。

每一条能力都写清出处，避免"凭印象填一张表"：

| 模型 | 首帧 | 尾帧 | 参考图 | 参考视频 | 单次时长上限 | 出处 |
|---|---|---|---|---|---|---|
| `wan-i2v` | ✅ | ❌ | ❌ | ❌ | 见 `wan_i2v_max_seconds` 配置 | `integrations/wan_i2v/adapter.py`（单图 + prompt + duration） |
| `wan-kf2v` | ✅ | ✅ | ❌ | ❌ | 同上 | `integrations/wan_kf2v/adapter.py`（`generate_pair(first,last)`） |
| `wan-r2v` | ✅ | ❌ | ✅（≤4） | ✅ | **15s** | `video_plan/one_shot.py`：`MAX_CALL_SECONDS` / `MAX_MEDIA_ITEMS`（r2v 官方硬约束） |
| `wan-s2v` | — | — | 声音参考 | — | — | 已下线调用点（保留适配器）；**不在预检覆盖内** |

预检**只报事实与降级码**，不阻断：真正拦人的是费用闸与交付门。
"""
from __future__ import annotations

from dataclasses import dataclass

from onetake_api.modules.video_plan.domain import PATH_ONE_SHOT, SEAM_PIN

MODEL_I2V = "wan-i2v"
MODEL_KF2V = "wan-kf2v"
MODEL_R2V = "wan-r2v"


@dataclass(frozen=True)
class ModelCapabilities:
    key: str
    label: str
    first_frame: bool
    last_frame: bool
    reference_images: int          # 可用参考图上限；0 = 不支持
    reference_video: bool
    max_call_seconds: int | None   # None = 由配置决定（分段路径会自行切分）
    source: str


CAPABILITIES: dict[str, ModelCapabilities] = {
    MODEL_I2V: ModelCapabilities(MODEL_I2V, "图生视频（单帧）", True, False, 0, False, None, "integrations/wan_i2v/adapter.py"),
    MODEL_KF2V: ModelCapabilities(MODEL_KF2V, "首尾帧（钉帧转场）", True, True, 0, False, None, "integrations/wan_kf2v/adapter.py"),
    MODEL_R2V: ModelCapabilities(MODEL_R2V, "参考生视频（一次出整片）", True, False, 4, True, 15, "video_plan/one_shot.py 的 MAX_CALL_SECONDS/MAX_MEDIA_ITEMS"),
}


@dataclass(frozen=True)
class PreflightCheck:
    code: str
    level: str      # ok | warn
    message: str


def resolve_model_kind(*, path: str, seam_mode: str) -> str:
    """按生成路径 + 接缝模式推出"这一次会走哪个模型"（与 `_resolve_anchor` 的分支一致）。"""
    if path == PATH_ONE_SHOT:
        return MODEL_R2V
    if seam_mode == SEAM_PIN:
        return MODEL_KF2V      # 钉帧 = 首尾帧对
    return MODEL_I2V           # 续拍 / 关：都用单帧 i2v


def preflight(
    *, model_kind: str, duration_seconds: float, shot_count: int, seam_mode: str, path: str | None = None
) -> list[PreflightCheck]:
    """给"当前参数 × 该模型能力"出一份预检（ok/warn 混合，不做阻断决策）。"""
    caps = CAPABILITIES.get(model_kind)
    checks: list[PreflightCheck] = []
    if caps is None:
        return [PreflightCheck("unknown-model", "warn", f"未知模型 {model_kind}：保持当前参数，不提前阻断")]

    checks.append(PreflightCheck(
        "capabilities", "ok",
        f"{caps.label}：首帧={'支持' if caps.first_frame else '不支持'}、尾帧={'支持' if caps.last_frame else '不支持'}、"
        f"参考图上限={caps.reference_images or '不支持'}、参考视频={'支持' if caps.reference_video else '不支持'}",
    ))

    if caps.max_call_seconds is not None and duration_seconds > caps.max_call_seconds:
        checks.append(PreflightCheck(
            "duration-split-required", "warn",
            f"成片 {duration_seconds:.0f}s 超过单次调用上限 {caps.max_call_seconds}s：会被拆成多次调用再拼接"
            "（接缝风险随之上升）",
        ))

    if model_kind == MODEL_R2V:
        limit = caps.reference_images + 1     # first_frame 占 1 个名额
        if shot_count > limit:
            checks.append(PreflightCheck(
                "media-over-limit", "warn",
                f"{shot_count} 个分镜关键帧超过单次可传素材上限（{limit}）：需要减少参考素材或拆分调用",
            ))

    # 接缝只对**分段路径**有意义：整片一次生成没有"这一段接下一段"的概念，
    # 因此不要在 one_shot 上报接缝相关告警（否则是噪声，会误导导演模式）。
    seam_applies = path != PATH_ONE_SHOT
    if seam_applies and seam_mode == SEAM_PIN and not caps.last_frame:
        checks.append(PreflightCheck(
            "last-frame-unsupported", "warn",
            f"{caps.label} 不接收尾帧：钉帧转场会退化为独立生成（画面衔接由合成侧负责）",
        ))
    if seam_applies and seam_mode == "tail" and model_kind != MODEL_I2V:
        checks.append(PreflightCheck(
            "tail-needs-single-frame", "warn",
            "续拍需要「单帧续写」（首帧=上一段尾帧），当前模型组合不支持该形态",
        ))
    return checks
