from __future__ import annotations

from dataclasses import dataclass
from math import ceil

from onetake_api.config import Settings
from onetake_api.modules.video_plan.domain import VideoPlan


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


def estimate_video_generation(plan: VideoPlan, settings: Settings) -> VideoGenerationEstimate:
    is_paid = not settings.mock_providers and (
        settings.wan_i2v_provider == "real"
        or settings.composition_provider == "shotstack"
        or settings.product_scene_enabled
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
        )

    needs_wan = settings.wan_i2v_provider == "real" and (
        plan.mode == "avatar"
        or (plan.mode == "product" and plan.template_id == "dynamic" and settings.product_scene_enabled)
    )
    needs_image_edit = (
        settings.product_scene_enabled
        and plan.mode == "product"
        and plan.template_id == "dynamic"
        and settings.image_edit_provider == "real"
    )
    shotstack_renders = 1 if settings.composition_provider == "shotstack" else 0
    clip_seconds = max(1, settings.wan_i2v_max_seconds)
    wan_clip_count = max(1, ceil(plan.duration_seconds / clip_seconds)) if needs_wan else 0
    wan_generated_seconds = wan_clip_count * clip_seconds
    estimated_wan_cost = round(wan_generated_seconds * settings.wan_i2v_price_per_second, 2)

    known_costs = [estimated_wan_cost] if needs_wan else []
    missing: list[str] = []
    notes: list[str] = []
    qwen_price = _optional_price(settings.qwen_image_edit_price_per_call)
    shotstack_price = _optional_price(settings.shotstack_render_price)
    if needs_image_edit:
        if qwen_price is None:
            missing.append("QWEN_IMAGE_EDIT_PRICE_PER_CALL")
            notes.append("Qwen 图像编辑费用待核算")
        else:
            known_costs.append(qwen_price)
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
        qwen_image_edit_calls=1 if needs_image_edit else 0,
        shotstack_renders=shotstack_renders,
        estimated_wan_cost=estimated_wan_cost,
        estimated_known_cost=estimated_known_cost,
        estimated_cost_max=None if missing else estimated_known_cost,
        currency="CNY",
        estimated_minutes=estimated_minutes,
        confirmation_threshold=settings.video_estimate_confirmation_threshold,
        requires_confirmation=True,
        missing_price_config=missing,
        price_notes=notes,
    )
