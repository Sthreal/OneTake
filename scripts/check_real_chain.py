"""真实供应商链路开跑前自检：配置齐不齐 + 费用预估（**不产生任何付费调用**）。

用法（在仓库根目录）：
    python scripts/check_real_chain.py

它回答三个问题：
1. 现在能不能跑真实链路？（`MOCK_PROVIDERS` 安全锁 + 各模型/密钥是否齐）
2. 缺什么？逐条列出需要写进 `.env` 的键（含预估里缺的单价）
3. 跑一次基准成片要花多少？（分段路径 vs 整片一次生成）

设计约束：只读配置、只做算术，不发起任何网络请求。

**2026-10-15 修复（此前本文件是坏的）**：原先它自己实现了一套费用算法 —— 把分段路径整个按 **i2v 一口价**算
（忽略 kf2v 归属，与 2026-10-14「预估按真实归属计价」那次修复相矛盾），并且引用了 M4-03 已删除的
`settings.product_scene_enabled` → **一跑就 AttributeError**。现在改为**直接调用生产估算函数**
`modules/video_plan/estimate.py::estimate_video_generation`（费用审批闸用的就是它），本脚本不再有第二处实现。
同时新增 `apps/api/tests/integration/test_check_real_chain_script.py` 防"再次腐烂"：跑一次脚本、不允许出现 Traceback。
"""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

# Windows 控制台默认 GBK，直接打印 ¥ 等字符会抛 UnicodeEncodeError
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "apps" / "api" / "src"))

from onetake_api.config import Settings  # noqa: E402
from onetake_api.modules.content_plan.generator import BEATS  # noqa: E402
from onetake_api.modules.video_plan.domain import PATH_ONE_SHOT, PATH_SEGMENTED  # noqa: E402
from onetake_api.modules.video_plan.estimate import estimate_video_generation  # noqa: E402

# 基准成片 = 既有 BEATS 的合计秒数（与 estimate.py 同口径）
BASE_DURATION_SECONDS = int(sum(beat["end"] - beat["start"] for beat in BEATS))
# 必须是 PRODUCT_SCENE_TEMPLATES（clean / dynamic / lifestyle）之一，否则生产估算会按"不产生费用"返回
BASE_TEMPLATE_ID = "clean"
_BASELINE_PATHS = ((PATH_SEGMENTED, "分段路径"), (PATH_ONE_SHOT, "整片一次生成"))


def _price(value) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _check(settings: Settings) -> tuple[list[str], list[str]]:
    missing: list[str] = []
    notes: list[str] = []

    if settings.mock_providers:
        notes.append("MOCK_PROVIDERS=true（安全锁开启）：真实调用不会发生，先改成 false 再跑真实链路")

    if not settings.dashscope_api_key:
        missing.append("DASHSCOPE_API_KEY")

    models = {
        "WAN_I2V_MODEL": settings.wan_i2v_model,
        "WAN_KF2V_MODEL": settings.wan_kf2v_model,
        "WAN_R2V_MODEL": settings.wan_r2v_model,
        "IMAGE_EDIT_MODEL": settings.image_edit_model,
    }
    for key, value in models.items():
        if not value:
            missing.append(key)

    prices = {
        "QWEN_IMAGE_PRICE_PER_CALL": settings.qwen_image_price_per_call,
        "WAN_I2V_PRICE_PER_SECOND": settings.wan_i2v_price_per_second,
        "WAN_KF2V_PRICE_PER_SECOND": settings.wan_kf2v_price_per_second,
        "WAN_R2V_PRICE_PER_SECOND": settings.wan_r2v_price_per_second,
    }
    for key, value in prices.items():
        if _price(value) is None:
            missing.append(key)

    if settings.composition_provider != "local":
        notes.append(f"COMPOSITION_PROVIDER={settings.composition_provider}（非 local，会产生云端合成费用）")
    if settings.gate_mode != "enforce":
        notes.append(f"GATE_MODE={settings.gate_mode}：交付门不拦不通过项（enforce 才拦）")
    return missing, notes


def _baseline_plan(path: str, *, duration_seconds: int = BASE_DURATION_SECONDS) -> SimpleNamespace:
    """基准方案：只喂估算函数真正读的字段（id / mode / template_id / duration_seconds / path）。"""
    return SimpleNamespace(
        id=f"estimate-baseline-{path}", mode="product", template_id=BASE_TEMPLATE_ID,
        duration_seconds=duration_seconds, path=path,
    )


def _estimate(settings: Settings) -> tuple[list[str], list[str]]:
    """两条路径各花多少 —— **全部由生产估算函数给出**，缺的单价如实上报。"""
    lines: list[str] = []
    missing_prices: list[str] = []
    for path, label in _BASELINE_PATHS:
        estimate = estimate_video_generation(_baseline_plan(path), settings)
        if not estimate.is_paid:
            lines.append(f"{label}：不产生费用（is_paid=false：mock 或 wan_i2v_provider 不是 real）")
            continue
        detail = (
            f"关键帧 {estimate.keyframe_calls} 次 / {estimate.keyframe_images} 张、"
            f"i2v {estimate.i2v_clips} 次、kf2v {estimate.kf2v_clips} 次、"
            f"r2v {estimate.r2v_calls} 次 / {estimate.r2v_seconds}s"
        )
        cost = "单价未配齐（见下面 missing）" if estimate.missing_price_config else f"合计 {estimate.estimated_known_cost} 元"
        lines.append(f"{label}：{detail} → {cost}")
        for note in estimate.price_notes:
            lines.append(f"      · {note}")
        for key in estimate.missing_price_config:
            if key not in missing_prices:
                missing_prices.append(key)
    lines.append("合计 = 关键帧 + 视频生成 + 逐镜评分（供应商费用）；本地合成（COMPOSITION_PROVIDER=local）不产生按次费用。")
    return lines, missing_prices


def main() -> int:
    settings = Settings()  # 读取仓库根 .env（脚本会先切到仓库根）
    missing, notes = _check(settings)
    estimate_lines, missing_prices = _estimate(settings)
    for key in missing_prices:
        if key not in missing:
            missing.append(key)

    print("=" * 72)
    print("真实供应商链路自检")
    print("=" * 72)
    print(f"生成路径默认值：{settings.generation_path_default}")
    print(f"关键帧模式：{settings.keyframe_mode}｜候选数：{settings.keyframe_candidates}")
    print(f"合成方式：{settings.composition_provider}｜去 AI 味：{'开' if settings.native_feel_enabled else '关'}")
    print(f"kf2v：{'开' if settings.video_kf2v_enabled else '关'}｜r2v 模型：{settings.wan_r2v_model or '（未配置）'}")
    print(f"保留模型原声：{'开' if settings.video_keep_model_audio else '关'}｜交付门：{settings.gate_mode}")
    print(
        f"逐镜评分：{'开' if settings.segment_quality_enabled else '关'}｜"
        f"空镜素材：{'开' if settings.stock_enabled else '关'}｜BGM：{'开' if settings.bgm_enabled else '关'}"
    )
    print("-" * 72)
    print(f"{BASE_DURATION_SECONDS} 秒无人成片的费用预估（estimate_video_generation 原样输出）：")
    for line in estimate_lines:
        print("  · " + line)
    print("-" * 72)
    if missing:
        print("❌ 还不能开跑，需要你在 .env 里补齐：")
        for key in missing:
            print(f"  - {key}")
    else:
        print("✅ 配置齐全，可以跑真实链路")
    for note in notes:
        print(f"⚠️  {note}")
    print("=" * 72)
    return 1 if missing else 0


if __name__ == "__main__":
    import os

    os.chdir(REPO_ROOT)
    raise SystemExit(main())
