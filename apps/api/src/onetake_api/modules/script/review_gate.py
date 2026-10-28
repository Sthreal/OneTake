"""花钱前审稿闸的纯函数。

闸门状态放在既有 `facts.review_gate` 里，不新加表。
`passed` 只认「对当前这份口播」做过 apply 或 ack；审稿失败、等长违规、
生成阶段的静默降级都不算过闸。
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

from onetake_api.modules.script.content import (
    NormalizedScript,
    ScriptGenerationError,
    normalize_generated,
    spoken_character_count,
)
from onetake_api.modules.script.domain import ScriptDraft, ScriptInput, ScriptVersion

GATE_OFF = "off"
GATE_WARN = "warn"
GATE_ENFORCE = "enforce"
GATE_MODES = (GATE_OFF, GATE_WARN, GATE_ENFORCE)

STATUS_PENDING = "pending"
STATUS_REVIEWED = "reviewed"
STATUS_FAILED = "failed"
STATUS_PASSED = "passed"

FACTS_KEY = "review_gate"
LENGTH_TOLERANCE = 0.20
_REWRITABLE_FIELDS = ("hook", "pain_point", "usage_scenario", "cta")


def inline_review_enabled(*, enabled: bool, gate: str) -> bool:
    """生成任务里的自动审稿只在闸门关闭时保留。

    warn / enforce 把审稿留给 POST /script/review。否则审稿失败被静默退回原稿，
    看起来像生成成功，付费视频却没有人点过 apply 或 ack。
    """
    return bool(enabled) and gate == GATE_OFF


def field_within_tolerance(before: str, after: str, *, tolerance: float = LENGTH_TOLERANCE) -> bool:
    """单字段口播字数相对原稿落在 ±tolerance 内。空原稿只允许仍为空。"""
    before_count = spoken_character_count(before)
    after_count = spoken_character_count(after)
    if before_count == 0:
        return after_count == 0
    low = before_count * (1 - tolerance)
    high = before_count * (1 + tolerance)
    return (low - 1e-6) <= after_count <= (high + 1e-6)


def length_violations(original: ScriptDraft, revised: ScriptDraft) -> list[str]:
    violations: list[str] = []
    for name in _REWRITABLE_FIELDS:
        if not field_within_tolerance(getattr(original, name), getattr(revised, name)):
            violations.append(name)
    before_points = [str(item) for item in original.selling_points]
    after_points = [str(item) for item in revised.selling_points]
    if len(before_points) != len(after_points):
        violations.append("selling_points")
        return violations
    for index, (before, after) in enumerate(zip(before_points, after_points, strict=True)):
        if not field_within_tolerance(before, after):
            violations.append(f"selling_points[{index}]")
    return violations


@dataclass(frozen=True)
class RevisionAssessment:
    length_errors: tuple[str, ...]
    normalized: NormalizedScript | None
    failure_code: str | None
    failure_message: str | None

    @property
    def ok(self) -> bool:
        return self.failure_code is None and self.normalized is not None


def assess_revision(
    original: ScriptDraft,
    revised: ScriptDraft,
    script_input: ScriptInput,
) -> RevisionAssessment:
    """等长（单字段 ±20%）和全文 45–72 一起看。任一失败，整次审稿失败。"""
    errors = tuple(length_violations(original, revised))
    try:
        normalized = normalize_generated(revised, script_input)
    except ScriptGenerationError as exc:
        if errors or "文案长度需为" in exc.message:
            return RevisionAssessment(errors, None, "SCRIPT_REVIEW_LENGTH", exc.message)
        return RevisionAssessment(errors, None, "SCRIPT_REVIEW_FAILED", exc.message)
    if errors:
        return RevisionAssessment(errors, None, "SCRIPT_REVIEW_LENGTH", "改写超出原稿 ±20% 字数")
    return RevisionAssessment((), normalized, None, None)


def draft_from_version(version: ScriptVersion) -> ScriptDraft:
    return ScriptDraft(
        hook=version.hook,
        pain_point=version.pain_point,
        selling_points=tuple(version.selling_points),
        usage_scenario=version.usage_scenario,
        cta=version.cta,
    )


def draft_to_dict(draft: ScriptDraft) -> dict:
    return {
        "hook": draft.hook,
        "pain_point": draft.pain_point,
        "selling_points": [str(item) for item in draft.selling_points],
        "usage_scenario": draft.usage_scenario,
        "cta": draft.cta,
    }


def draft_from_mapping(payload: dict) -> ScriptDraft:
    points = payload.get("selling_points") or []
    return ScriptDraft(
        hook=str(payload.get("hook") or ""),
        pain_point=str(payload.get("pain_point") or ""),
        selling_points=tuple(str(item) for item in points),
        usage_scenario=str(payload.get("usage_scenario") or ""),
        cta=str(payload.get("cta") or ""),
    )


def script_fingerprint(version: ScriptVersion) -> str:
    payload = {
        "hook": version.hook,
        "pain_point": version.pain_point,
        "selling_points": list(version.selling_points),
        "usage_scenario": version.usage_scenario,
        "offer": version.offer,
        "cta": version.cta,
        "full_text": version.full_text,
    }
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def stored_gate(facts: dict | None) -> dict:
    if not isinstance(facts, dict):
        return {}
    raw = facts.get(FACTS_KEY)
    return dict(raw) if isinstance(raw, dict) else {}


def facts_with_gate(facts: dict, gate: dict) -> dict:
    updated = dict(facts)
    updated[FACTS_KEY] = gate
    return updated


def facts_without_gate(facts: dict) -> dict:
    return {key: value for key, value in facts.items() if key != FACTS_KEY}


def is_review_passed(version: ScriptVersion) -> bool:
    gate = stored_gate(version.facts)
    return gate.get("status") == STATUS_PASSED and gate.get("fingerprint") == script_fingerprint(version)


def effective_gate_status(version: ScriptVersion) -> str:
    gate = stored_gate(version.facts)
    current = script_fingerprint(version)
    if gate.get("status") == STATUS_PASSED and gate.get("fingerprint") == current:
        return STATUS_PASSED
    if gate.get("attempted") and gate.get("source_fingerprint") == current:
        status = str(gate.get("status") or "")
        if status in {STATUS_REVIEWED, STATUS_FAILED}:
            return status
    return STATUS_PENDING
