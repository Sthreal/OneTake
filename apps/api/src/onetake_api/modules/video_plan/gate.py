"""交付门（Phase 5）：把客观质检、合规检查与 AIGC 标识断言汇总成一个可执行的结论。

语义（与总体方案 §9.4 一致）：
- `fail`  → 有客观坏片或平台风险，**不允许交付**
- `warn`  → 需要人来判断（抽帧拼图、合规提示）；**逐条确认后**才允许下载
- `ok`    → 自动检查未发现阻断项

`download_allowed` 是给前端的唯一判据，避免前端自己拼规则。
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from onetake_api.config import get_settings
from onetake_api.modules.compliance.labels import LabelCheckError, assert_aigc_label
from onetake_api.modules.compliance.public import CompliancePublicService
from onetake_api.modules.content_qa.caption_check import SEVERITY_INFO, SEVERITY_WARN, check_captions
from onetake_api.modules.content_qa.public import ContentQaPublicService
from onetake_api.modules.video_plan.gate_ack_repository import GateAckRepository

LEVEL_OK = "ok"
LEVEL_WARN = "warn"
LEVEL_FAIL = "fail"
_ORDER = {LEVEL_OK: 0, LEVEL_WARN: 1, LEVEL_FAIL: 2}
MAX_WORD_HITS = 5
# 只有本地合成器会烧录 AIGC 标识（见总体方案 §9.2.1）
LOCAL_COMPOSER_PROVIDER = "local-ffmpeg"
# 批次 4a：免 Key 素材填充的分段候选，provider 形如 `stock:wikimedia`
STOCK_PROVIDER_PREFIX = "stock:"
STOCK_ATTRIBUTION_SUFFIX = "/stock-attribution.json"


@dataclass(frozen=True)
class GateCheckView:
    id: str
    level: str
    label: str
    message: str
    at_seconds: list[float] = field(default_factory=list)


@dataclass(frozen=True)
class GateReportView:
    project_id: str
    status: str
    mode: str
    checks: list[GateCheckView]
    contact_sheet_url: str | None = None
    acknowledged: list[str] = field(default_factory=list)
    download_allowed: bool = True


def _worst(levels: list[str]) -> str:
    if not levels:
        return LEVEL_OK
    return max(levels, key=lambda item: _ORDER.get(item, 0))


def segment_quality_check(*, report) -> GateCheckView | None:
    """逐镜评分结论（批次 5）：**有报告才出这条**；低分/有问题 → warn（不阻断，交人看）。

    没有报告就是"没跑过"，不是"通过了" —— 这里返回 None，让门里根本没有这一条，
    避免把"未运行"伪装成"检查通过"。
    """
    if report is None:
        return None
    from onetake_api.modules.content_qa.segment_quality import LOW_SCORE_THRESHOLD

    low = report.low_scores
    if not low and not report.issues:
        return GateCheckView(
            id="segment_quality", level=LEVEL_OK, label="逐镜评分",
            message=f"{len(report.segments)} 个分段已评分（{report.provider}/{report.model}），均不低于 {LOW_SCORE_THRESHOLD} 分",
        )
    # 消息要**可执行**：既说哪一镜多少分（低于门槛），也带上模型给出的具体问题
    parts: list[str] = [issue for issue in report.issues[:2]]
    if low:
        parts.append(
            f"低于门槛（{LOW_SCORE_THRESHOLD} 分）的镜头："
            + "、".join(f"第 {item.order_index} 镜 {item.overall} 分" for item in low[:3])
        )
    detail = "；".join(parts)
    return GateCheckView(id="segment_quality", level=LEVEL_WARN, label="逐镜评分", message=detail)


def _segment_quality(project_id: str) -> GateCheckView | None:
    """读最近一次逐镜评分（**读不到不影响交付门结论**）。"""
    try:
        from onetake_api.modules.content_qa import segment_quality

        return segment_quality_check(report=segment_quality.read_report(project_id))
    except Exception:  # noqa: BLE001
        return None

def download_allowed_for(session: Session, project_id: str) -> tuple[bool, str | None]:
    """交付门的"能不能下载/导出"判据（**唯一来源**，导出端点与下载共用，避免两处各判一次）。

    返回 `(allowed, blocking_reason)`。没有落库结论时**保守拦截**（导出是"把片子拿出去"的动作，
    宁可让用户先看到交付门结论，也不要在没有结论时放行）。
    """
    from onetake_api.modules.video_plan.public import VideoPlanPublicService

    plan = getattr(VideoPlanPublicService().latest(session, project_id), "plan", None)
    payload = getattr(plan, "gate_report", None) if plan is not None else None
    if not payload:
        return False, "尚未生成交付门结论（请先出成片）"
    acknowledged = GateAckRepository().list_for_project(session, project_id)
    pending = [
        str(check.get("id"))
        for check in payload.get("checks", [])
        if check.get("level") == LEVEL_WARN and check.get("id") not in acknowledged
    ]
    if payload.get("status") == LEVEL_FAIL:
        return False, "交付门判定为不可交付（fail）：请先修复阻断项"
    if pending:
        return False, "还有未确认的警告项：" + "、".join(pending)
    return True, None

def stock_sources_check(*, segments, storage) -> GateCheckView | None:
    """免 Key 素材的**来源与署名**（CC 要求）→ 一条 `ok` 级检查。

    素材候选旁边有 sidecar JSON（`segment_service` 写入）；读不到就跳过这一条，
    **不阻断、也不伪装** —— 署名是"提醒用户发布时写上"，不是"片子能不能交付"的判据。
    """
    attributions: list[str] = []
    for segment in segments or []:
        for candidate in getattr(segment, "candidates", []) or []:
            provider = getattr(candidate, "provider", "") or ""
            if not provider.startswith(STOCK_PROVIDER_PREFIX):
                continue
            key = (getattr(candidate, "video_object_key", "") or "").replace("/video.mp4", STOCK_ATTRIBUTION_SUFFIX)
            if not key:
                continue
            try:
                payload = json.loads(b"".join(storage.read_object(object_key=key)).decode("utf-8"))
            except Exception:  # noqa: BLE001 - 读不到就当没有（附加信息）
                continue
            line = str(payload.get("attribution") or "").strip()
            if line:
                attributions.append(f"{line}（{provider}）")
    if not attributions:
        return None
    return GateCheckView(
        id="stock_sources", level=LEVEL_OK, label="素材来源与署名",
        message="本片使用了免 Key 素材，发布时请按许可署名：" + "；".join(attributions[:3]),
    )


def _stock_sources(session: Session, project_id: str) -> GateCheckView | None:
    """从最近一次视频方案的候选里收集素材署名（**任何异常都不影响交付门结论**）。"""
    try:
        from onetake_api.integrations.object_storage.dependencies import get_object_storage
        from onetake_api.modules.video_plan.keyframe_repository import VideoKeyframeCandidateRepository  # noqa: F401
        from onetake_api.modules.video_plan.public import VideoPlanPublicService
        from onetake_api.modules.video_plan.segment_repository import VideoSegmentRepository

        plan_view = VideoPlanPublicService().latest(session, project_id)
        plan = getattr(plan_view, "plan", None)
        if plan is None:
            return None
        segments = VideoSegmentRepository().list_for_plan(session, plan.id)
        return stock_sources_check(segments=segments, storage=get_object_storage())
    except Exception:  # noqa: BLE001
        return None

def _caption_safety_check(
    *, session_settings, srt_bytes: bytes, video_bytes: bytes | None, width: int, height: int
) -> GateCheckView:
    """字幕安全区：布局估算 + 像素探针。探针自身出错不能让交付门整体挂掉（降级为 warn 并写明原因）。"""
    try:
        findings = check_captions(
            width=width, height=height, srt_bytes=srt_bytes, video_bytes=video_bytes,
            style=session_settings.caption_style,
            label_position=session_settings.aigc_label_position,
            label_size_ratio=session_settings.aigc_label_size_ratio,
            label_margin_ratio=session_settings.aigc_label_safe_margin_ratio,
            avoid_subtitle=session_settings.aigc_label_avoid_subtitle,
        )
    except Exception as exc:  # noqa: BLE001 - 探针失败如实降级为 warn，不冒充通过
        return GateCheckView(
            id="caption_safety", level=LEVEL_WARN, label="字幕安全区",
            message=f"字幕安全区检查未执行（{type(exc).__name__}）：请人工确认字幕未被裁切",
        )
    warns = [finding for finding in findings if finding.severity == SEVERITY_WARN]
    infos = [finding for finding in findings if finding.severity == SEVERITY_INFO]
    if warns:
        return GateCheckView(
            id="caption_safety", level=LEVEL_WARN, label="字幕安全区",
            message="；".join(finding.message for finding in warns[:3]),
            at_seconds=sorted({seconds for finding in warns for seconds in finding.at_seconds}),
        )
    detail = f"字幕安全区检查通过（另有 {len(infos)} 条会自动折行的提示）" if infos else "字幕安全区检查通过"
    return GateCheckView(id="caption_safety", level=LEVEL_OK, label="字幕安全区", message=detail)


def build_gate_report(
    session: Session,
    *,
    project_id: str,
    video_bytes: bytes | None = None,
    contact_sheet_url: str | None = None,
    width: int = 1080,
    height: int = 1920,
    composition_provider: str | None = None,
    # 批次 1b：字幕安全区检查要按"实际烧上去的那份 SRT"算，所以成片路径要把它传进来
    srt_bytes: bytes | None = None,
) -> GateReportView:
    settings = get_settings()
    checks: list[GateCheckView] = []

    # ---- 客观质检（来自最近一次质检报告，含黑帧/静音/冻结/响度/时长信号）----
    report = ContentQaPublicService().latest(session, project_id)
    if report is None:
        checks.append(GateCheckView(
            id="quality_report", level=LEVEL_WARN, label="质检报告",
            message="尚未生成质检报告，无法给出交付结论",
        ))
    else:
        for item in report.checks:
            level = LEVEL_OK
            if not item.passed:
                level = LEVEL_FAIL if item.critical else LEVEL_WARN
            checks.append(GateCheckView(
                id=item.check_id, level=level, label=item.label, message=item.message,
                at_seconds=list(getattr(item, "at_seconds", []) or []),
            ))

    # ---- 合规 ----
    compliance = CompliancePublicService().report(session, project_id=project_id)
    if compliance.banned_words:
        shown = compliance.banned_words[:MAX_WORD_HITS]
        detail = "、".join(f"{hit.word}（{hit.where}）" for hit in shown)
        checks.append(GateCheckView(
            id="ad_words", level=LEVEL_WARN, label="违禁词",
            message=f"命中 {len(compliance.banned_words)} 处绝对化/违禁表述：{detail}",
        ))
    for warning in compliance.platform_warnings:
        checks.append(GateCheckView(id=warning.id, level=LEVEL_WARN, label="平台规则", message=warning.message))

    if not settings.aigc_label_enabled:
        checks.append(GateCheckView(
            id="aigc_label", level=LEVEL_WARN, label="AIGC 标识",
            message="未启用 AIGC 标识，发布前需自行确认平台要求",
        ))
    elif video_bytes and composition_provider not in {None, LOCAL_COMPOSER_PROVIDER}:
        # 只有真正会烧录标识的合成器才做硬断言；其余合成方式如实标为"未烧录"警告，
        # 而不是让它冒充通过（也不因为它把整条 mock 链路判死）
        checks.append(GateCheckView(
            id="aigc_label", level=LEVEL_WARN, label="AIGC 标识",
            message=f"当前合成方式（{composition_provider}）不烧录 AIGC 标识，发布前请自行确认平台要求",
        ))
    elif video_bytes:
        try:
            present, message = assert_aigc_label(
                video_bytes, width=width, height=height,
                position=settings.aigc_label_position, size_ratio=settings.aigc_label_size_ratio,
                margin_ratio=settings.aigc_label_safe_margin_ratio,
                avoid_subtitle=settings.aigc_label_avoid_subtitle,
            )
        except LabelCheckError as exc:
            present, message = False, f"标识校验失败：{exc.message}"
        checks.append(GateCheckView(
            id="aigc_label", level=LEVEL_OK if present else LEVEL_FAIL, label="AIGC 标识", message=message,
        ))

    # 抽帧拼图是"人看一眼再交付"的唯一入口：缺失时必须让用户知道
    if video_bytes and contact_sheet_url is None:
        checks.append(GateCheckView(
            id="contact_sheet", level=LEVEL_WARN, label="抽帧复核",
            message="抽帧拼图不可用，请改用逐帧检查或重新生成",
        ))

    # ---- 字幕安全区（批次 1b：渲染前估算 + 渲染后探针；**warn 不阻断**，与 contact_sheet 同思路）----
    if srt_bytes:
        checks.append(_caption_safety_check(
            session_settings=settings, srt_bytes=srt_bytes, video_bytes=video_bytes, width=width, height=height,
        ))

    # ---- 逐镜 VLM 评分（批次 5：ok/warn，不阻断）----
    quality_check = _segment_quality(project_id)
    if quality_check is not None:
        checks.append(quality_check)

    # ---- 免 Key 素材的来源与署名（批次 4a：ok 级，不阻断）----
    stock_check = _stock_sources(session, project_id)
    if stock_check is not None:
        checks.append(stock_check)

    acknowledged = GateAckRepository().list_for_project(session, project_id)
    status = _worst([check.level for check in checks])
    if settings.gate_mode == "warn_only" and status == LEVEL_FAIL:
        status = LEVEL_WARN
        checks.append(GateCheckView(
            id="gate_mode", level=LEVEL_WARN, label="交付门模式",
            message="GATE_MODE=warn_only：失败项已降级为警告",
        ))
    else:
        status = _worst([check.level for check in checks])

    pending = [check.id for check in checks if check.level == LEVEL_WARN and check.id not in acknowledged]
    download_allowed = status != LEVEL_FAIL and not pending
    return GateReportView(
        project_id=project_id, status=status, mode=settings.gate_mode, checks=checks,
        contact_sheet_url=contact_sheet_url, acknowledged=acknowledged, download_allowed=download_allowed,
    )