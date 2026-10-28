"""合规报告领域对象（Phase 0 仅定义契约）。

Phase 5 会补齐三类检查：
- AIGC 标识（本地叠加优先，见总体方案 9.2.1）
- 广告违禁词 / 绝对化用语扫描（文案 + 字幕）
- 抖音 AI 电商平台规则（AI 对比测评类风险、数字人禁五类目、"亲测有效"红线）
"""
from __future__ import annotations

from dataclasses import dataclass, field

RULES_VERSION = "2026-10-ai-commerce-v1"
# 兼容旧名（Phase 0 曾用它标记"未评估"）
RULES_VERSION_PHASE0 = RULES_VERSION


@dataclass(frozen=True)
class BannedWordHit:
    word: str
    where: str
    index: int


@dataclass(frozen=True)
class PlatformWarning:
    id: str
    message: str


@dataclass(frozen=True)
class ComplianceReport:
    project_id: str
    evaluated: bool
    rules_version: str
    aigc_label_enabled: bool
    aigc_label_text: str
    aigc_label_position: str
    aigc_label_source: str
    banned_words: list[BannedWordHit] = field(default_factory=list)
    platform_warnings: list[PlatformWarning] = field(default_factory=list)
