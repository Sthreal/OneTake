"""合规检查服务（Phase 5）：违禁词 + 平台规则；AIGC 标识的存在性由交付门在成片上断言。"""
from __future__ import annotations

from sqlalchemy.orm import Session

from onetake_api.config import get_settings
from onetake_api.modules.compliance import ad_words, platform_rules
from onetake_api.modules.compliance.domain import RULES_VERSION, ComplianceReport
from onetake_api.modules.content_plan.public import ContentPlanPublicService
from onetake_api.modules.project.public import ProjectPublicService
from onetake_api.modules.script.public import ScriptPublicService
from onetake_api.modules.subtitle.public import SubtitlePublicService


class ComplianceApplicationService:
    def report(self, session: Session, *, project_id: str) -> ComplianceReport:
        project = ProjectPublicService().get_project(session, project_id=project_id)
        settings = get_settings()
        script_view = ScriptPublicService().latest(session, project_id)
        script = getattr(script_view, "version", None)
        subtitle = SubtitlePublicService().latest(session, project_id)
        plan = ContentPlanPublicService().latest(session, project_id)
        # 延迟导入：video_plan.gate 依赖本模块，模块级导入会形成循环
        from onetake_api.modules.video_plan.public import VideoPlanPublicService

        video_plan = VideoPlanPublicService().latest(session, project_id).plan

        copy_text = _script_text(script)
        subtitle_text = "".join(str(item.get("text", "")) for item in (getattr(subtitle, "segments", None) or []))
        style = None
        if plan is not None and plan.variants:
            style = plan.variants[plan.selected_variant_index].style

        hits = ad_words.scan(copy_text, where="script") + ad_words.scan(subtitle_text, where="subtitle")
        warnings = platform_rules.evaluate(
            style=style,
            product_text=f"{getattr(project, 'product_name', '')} {getattr(project, 'product_note', '') or ''}",
            copy_text=copy_text + subtitle_text,
        )
        return ComplianceReport(
            project_id=project_id,
            evaluated=True,
            rules_version=RULES_VERSION,
            aigc_label_enabled=settings.aigc_label_enabled,
            aigc_label_text=settings.aigc_label_text,
            aigc_label_position=settings.aigc_label_position,
            aigc_label_source=settings.aigc_label_source,
            banned_words=hits,
            platform_warnings=warnings,
        )


def _script_text(script) -> str:
    if script is None:
        return ""
    parts = [
        getattr(script, "hook", "") or "",
        getattr(script, "pain_point", "") or "",
        " ".join(getattr(script, "selling_points", []) or []),
        getattr(script, "usage_scenario", "") or "",
        getattr(script, "offer", "") or "",
        getattr(script, "cta", "") or "",
    ]
    return " ".join(part for part in parts if part)