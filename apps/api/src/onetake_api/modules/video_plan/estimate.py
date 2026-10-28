from __future__ import annotations

import math
from dataclasses import dataclass

from onetake_api.config import Settings
from onetake_api.integrations.product_scene.keyframe_integrated import (
    GRID_COLS,
    GRID_ROWS,
    MODE_GRID,
    MODE_INTEGRATED,
)
from onetake_api.modules.content_plan.generator import BEATS
from onetake_api.modules.video_plan.one_shot import group_beat_durations
from onetake_api.modules.video_plan.segment_plan import plan_segment_calls, split_durations
from onetake_api.modules.video_plan.domain import PATH_ONE_SHOT, PATH_SEGMENTED, PRODUCT_SCENE_TEMPLATES, VideoPlan


def _split_duration(duration_seconds: float, max_seconds: int) -> list[int]:
    """保留旧名，但**切分算法只有一份**（`segment_plan.split_durations`）。"""
    return split_durations(round(duration_seconds), max_seconds)


def _kf2v_available(settings: Settings) -> bool:
    """这一档"首尾帧"（kf2v）在当前配置下能不能用 —— 与生成器 `_default_pair_adapter` 同判据。

    预估的意义在于"预估 = 实际"，所以这里的判据必须跟真实适配器构造保持一致：
    开关 + 模型 + Key 三个都满足才认为会走 kf2v（mock 路径两档都提供，但它免费、不走计价分支）。
    """
    if not settings.video_kf2v_enabled:
        return False
    if settings.mock_providers:
        return True
    return bool(settings.wan_kf2v_model and settings.dashscope_api_key)


def _optional_price(value: float | str | None) -> float | None:
    if value is None or value == "":
        return None
    return float(value)


@dataclass(frozen=True)
class VideoGenerationEstimate:
    plan_id: str
    mode: str
    template_id: str | None
    duration_seconds: float
    is_paid: bool
    wan_clip_count: int
    wan_generated_seconds: int
    qwen_image_edit_calls: int
    shotstack_renders: int
    estimated_wan_cost: float
    estimated_known_cost: float
    estimated_cost_max: float | None
    currency: str
    estimated_minutes: float
    confirmation_threshold: float
    requires_confirmation: bool
    missing_price_config: list[str]
    price_notes: list[str]
    # ---- 商品入画链路扩展字段（Phase 0 契约；已在 VideoEstimateData 中同步声明）----
    path: str = "segmented"
    keyframe_calls: int = 0
    keyframe_images: int = 0
    i2v_clips: int = 0
    kf2v_clips: int = 0
    r2v_calls: int = 0
    r2v_seconds: int = 0
    composition: str = "shotstack"


def estimate_video_generation(
    plan: VideoPlan, settings: Settings, *, effective_seams: list[str | None] | None = None
) -> VideoGenerationEstimate:
    """`effective_seams`：按分段顺序的**段级接缝覆盖**（None = 继承方案级）。

    接缝决定这一镜有没有尾帧（pin → kf2v 对；tail/off → 单帧 i2v），而两档**单价不同** ——
    所以预估必须按段推演，否则「预估 = 实际」这条纪律立刻破
    （S6 只加了接缝模式却没接预估，本片修掉）。
    """
    # `product_scene_enabled` 开关已随 M4-03 提交 1 删除（它曾同时 gate「已废弃的整片路径」
    # 与这份估算）。真实分段 i2v 的判定口径保持原样（模板 + wan_i2v_provider），未在本提交改动。
    product_scene_real = (
        plan.mode == "product"
        and plan.template_id in PRODUCT_SCENE_TEMPLATES
       and settings.wan_i2v_provider == "real"
    )
    needs_video = not settings.mock_providers and product_scene_real
    is_paid = not settings.mock_providers and (
        settings.composition_provider == "shotstack"
       or product_scene_real
    )
    if not is_paid:
        return VideoGenerationEstimate(
            plan_id=plan.id,
            mode=plan.mode,
            template_id=plan.template_id,
            duration_seconds=plan.duration_seconds,
            is_paid=False,
            wan_clip_count=0,
            wan_generated_seconds=0,
            qwen_image_edit_calls=0,
            shotstack_renders=0,
            estimated_wan_cost=0.0,
            estimated_known_cost=0.0,
            estimated_cost_max=0.0,
            currency="CNY",
            estimated_minutes=0.0,
            confirmation_threshold=settings.video_estimate_confirmation_threshold,
            requires_confirmation=False,
            missing_price_config=[],
            price_notes=["Mock Provider 不产生费用"],
            path=getattr(plan, "path", PATH_SEGMENTED),
            i2v_clips=0,
            composition=settings.composition_provider,
        )


    wan_clip_count = 0
    wan_generated_seconds = 0
    estimated_wan_cost = 0.0
    i2v_clips = 0
    kf2v_clips = 0
    i2v_seconds = 0
    kf2v_seconds = 0
    known_costs: list[float] = []
    missing: list[str] = []
    notes: list[str] = []
    # 关键帧生成（商品入画）的**付费口径**（2026-10-15 修：`grid` 档曾被算成 0 次/¥0）：
    # - `integrated`：每镜 1 次调用（一次调用出 keyframe_candidates 张候选）→ 次数 = 分镜数；
    # - `erase_background`：走**本地素材**拼背景（`load_scene_keyframe`），不调供应商 → 0 次（与改动前一致）；
    # - `grid`：**1 次调用出一整张九宫格（GRID_ROWS×GRID_COLS 格）** → 次数 = ceil(分镜数 / 每张格数)；
    #   而服务层在"坏格过半"时会**整片回退单帧**，那一步要按 integrated 的次数再花一遍 →
    #   最坏情况 = 网格次数 + 分镜数，必须反映到 `estimated_cost_max`。
    # 为什么必须算进去：费用审批闸就是拿 `estimated_known_cost` 批钱的 —— 2026-10-14 漏算整笔关键帧
    # （4 次 × 0.5 = ¥2）已经证明"少报 = 硬约束失效"；grid 档被算成 0 是同一类缺陷。
    grid_cells = GRID_ROWS * GRID_COLS
    keyframe_calls = 0
    keyframe_calls_max = 0
    keyframe_images = 0
    if needs_video and plan.mode == "product":
        if settings.keyframe_mode == MODE_GRID:
            keyframe_calls = math.ceil(len(BEATS) / grid_cells)
            keyframe_calls_max = keyframe_calls + len(BEATS)   # 坏格过半 → 整片回退单帧
            keyframe_images = keyframe_calls * grid_cells
        elif settings.keyframe_mode == MODE_INTEGRATED:
            keyframe_calls = len(BEATS)
            keyframe_calls_max = keyframe_calls
            keyframe_images = keyframe_calls * max(1, settings.keyframe_candidates)
    r2v_calls = 0
    r2v_seconds = 0
    if needs_video and plan.mode == "product" and getattr(plan, "path", PATH_SEGMENTED) == PATH_ONE_SHOT:
        # 整片一次生成：按 15s 上限切分，调用次数与真实编排共用同一套分组规则
        groups = group_beat_durations(
            [beat["end"] - beat["start"] for beat in BEATS], max_seconds=settings.wan_r2v_max_seconds
        )
        r2v_calls = len(groups)
        r2v_seconds = int(round(sum(length for group in groups for length in group)))
        r2v_price = _optional_price(settings.wan_r2v_price_per_second)
        if r2v_price is None:
            missing.append("WAN_R2V_PRICE_PER_SECOND")
            notes.append("Wan R2V 整片生成费用待核算")
        else:
            estimated_wan_cost = round(r2v_seconds * r2v_price, 2)
            known_costs.append(estimated_wan_cost)
        notes.append(f"整片一次生成：{r2v_calls} 次调用 / {r2v_seconds} 秒")
    keyframe_fallback_cost = 0.0
    if keyframe_calls:
        keyframe_price = _optional_price(settings.qwen_image_price_per_call)
        if keyframe_price is None:
            missing.append("QWEN_IMAGE_PRICE_PER_CALL")
            notes.append("Qwen 关键帧生成费用待核算")
        else:
            # 网格档的"回退最坏情况"：坏格过半时服务层会整片改用单帧档，那 N 次要单独计。
            # 它不进 known_cost（不是必然发生），而是进 estimated_cost_max（上限口径）。
            keyframe_fallback_cost = round((keyframe_calls_max - keyframe_calls) * keyframe_price, 2)
            # 关键帧是**付费**的（Qwen 图片编辑按次计费）——必须并入 known_costs。
            # 曾经这里只检查"单价有没有配"、却不累加，于是预估**漏算整笔关键帧费用**
            # （实测：4 次 × 0.5 元 → 预估少报 2 元）。费用审批闸就是拿这个数来批的，
            # 少报等于让硬约束失效（批准的金额 < 实际花费）。
            keyframe_cost = round(keyframe_calls * keyframe_price, 2)
            known_costs.append(keyframe_cost)
            keyframe_note = f"关键帧：{keyframe_calls} 次 × {keyframe_price} 元 = {keyframe_cost} 元"
            if settings.keyframe_mode == MODE_GRID and keyframe_fallback_cost:
                keyframe_note += (
                    f"（九宫格档：每张 {grid_cells} 格；坏格过半会整片回退单帧 → 最坏再 +"
                    f"{keyframe_calls_max - keyframe_calls} 次 ≈ {keyframe_fallback_cost} 元）"
                )
            notes.append(keyframe_note)


    if needs_video and getattr(plan, "path", PATH_SEGMENTED) != PATH_ONE_SHOT:
        # 用**与生成器同一张计划表**推演：每一镜会调几次、每次多少秒、走 i2v 还是 kf2v。
        # 这样"预估 = 实际"（单价两档不同，混着按一档算必然偏）。
        beats = [beat["end"] - beat["start"] for beat in BEATS]
        pair_available = _kf2v_available(settings)
        plan_seam = getattr(plan, "seam_mode", "pin")
        seam_overrides = effective_seams or []
        stock_ready = bool(getattr(settings, "stock_enabled", False))
        stock_shots = 0
        stock_seconds = 0
        for index, beat_seconds in enumerate(beats):
            # 批次 4a：空镜（product_mode=absent）改由免 Key 素材填充 → 这一镜**不产生 i2v/kf2v 调用**，
            # 因此也必须从预估里扣掉（费用审批闸拿这个数批钱，多报会挡住用户、少报会让硬约束失效）。
            # 注意只扣分段生成这一刀：关键帧阶段（阶段一，商品入画）照常跑，本刀不省那一次调用。
            if stock_ready and BEATS[index].get("product_mode") == "absent":
                stock_shots += 1
                stock_seconds += int(round(beat_seconds))
                continue
            # 段级覆盖优先；没有覆盖就跟着方案级（只有 pin 用首尾帧对）
            seam = (seam_overrides[index] if index < len(seam_overrides) else None) or plan_seam
            # 最后一镜没有"下一镜关键帧"可当尾帧 → 只能用单帧 i2v
            has_tail = pair_available and seam == "pin" and index < len(beats) - 1
            for call in plan_segment_calls(
                duration_seconds=int(round(beat_seconds)),
                max_seconds=settings.wan_i2v_max_seconds,
                has_tail_frame=has_tail,
            ):
                if call.pair:
                    kf2v_clips += 1
                    kf2v_seconds += call.duration_seconds
                else:
                    i2v_clips += 1
                    i2v_seconds += call.duration_seconds
        wan_clip_count = i2v_clips + kf2v_clips
        wan_generated_seconds = i2v_seconds + kf2v_seconds
        i2v_price = _optional_price(settings.wan_i2v_price_per_second)
        kf2v_price = _optional_price(settings.wan_kf2v_price_per_second)
        if i2v_clips and i2v_price is None:
            missing.append("WAN_I2V_PRICE_PER_SECOND")
            notes.append("Wan I2V 费用待核算")
        if kf2v_clips and kf2v_price is None:
            missing.append("WAN_KF2V_PRICE_PER_SECOND")
            notes.append("Wan KF2V（首尾帧）费用待核算")
        video_cost = round(
            i2v_seconds * (i2v_price or 0.0) + kf2v_seconds * (kf2v_price or 0.0), 2
        )
        if video_cost:
            estimated_wan_cost = video_cost
            known_costs.append(video_cost)
        # 批次 5：逐镜 VLM 评分（付费）——开启时按"每镜一次调用"计入，缺单价如实进 missing
        if bool(getattr(settings, "segment_quality_enabled", False)):
            quality_calls = len(BEATS)
            quality_price = _optional_price(getattr(settings, "qwen_vl_price_per_call", None))
            if quality_price is None:
                missing.append("QWEN_VL_PRICE_PER_CALL")
                notes.append("逐镜 VLM 评分费用待核算")
            else:
                quality_cost = round(quality_calls * quality_price, 2)
                known_costs.append(quality_cost)
                notes.append(f"逐镜评分：{quality_calls} 次 × {quality_price} 元 = {quality_cost} 元")

        if stock_shots:
            notes.append(
                f"0 成本素材：{stock_shots} 镜/{stock_seconds}s 由免 Key 素材填充（不计费用；关键帧仍照常生成）"
            )
        if wan_clip_count:
            notes.append(
                f"分段：i2v {i2v_clips} 次/{i2v_seconds}s、kf2v {kf2v_clips} 次/{kf2v_seconds}s"
            )

    shotstack_renders = 1 if settings.composition_provider == "shotstack" else 0
    shotstack_price = _optional_price(settings.shotstack_render_price)
    if shotstack_renders:
        if shotstack_price is None:
            missing.append("SHOTSTACK_RENDER_PRICE")
            notes.append("Shotstack Stage 费用按订阅额度核算")
        else:
            known_costs.append(shotstack_price)

    estimated_known_cost = round(sum(known_costs), 2)
    estimated_minutes = round(
        settings.video_estimate_overhead_minutes + wan_clip_count * settings.video_estimate_minutes_per_clip,
        1,
    )
    return VideoGenerationEstimate(
        plan_id=plan.id,
        mode=plan.mode,
        template_id=plan.template_id,
        duration_seconds=plan.duration_seconds,
        is_paid=True,
        wan_clip_count=wan_clip_count,
        wan_generated_seconds=wan_generated_seconds,
        qwen_image_edit_calls=0,
        shotstack_renders=shotstack_renders,
        estimated_wan_cost=estimated_wan_cost,
        estimated_known_cost=estimated_known_cost,
        estimated_cost_max=None if missing else round(estimated_known_cost + keyframe_fallback_cost, 2),
        currency="CNY",
        estimated_minutes=estimated_minutes,
        confirmation_threshold=settings.video_estimate_confirmation_threshold,
        requires_confirmation=True,
        missing_price_config=missing,
        price_notes=notes,
        path=getattr(plan, "path", PATH_SEGMENTED),
        keyframe_calls=keyframe_calls,
        keyframe_images=keyframe_images,
        i2v_clips=i2v_clips,
        kf2v_clips=kf2v_clips,
        r2v_calls=r2v_calls,
        r2v_seconds=r2v_seconds,
        composition=settings.composition_provider,
    )