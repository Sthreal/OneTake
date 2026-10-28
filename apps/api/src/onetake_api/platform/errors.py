from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from onetake_api.platform.request_context import get_request_id

logger = logging.getLogger(__name__)


# 失败分类与恢复动作的**取值域**（S8/S9/S10 的推进器据此决定下一步）。
# 新增取值时先改这里，再改推进器的阶段目录 —— 两处是同一份契约。
ERROR_CLASSES = frozenset({"transient", "permanent", "policy", "budget"})
RECOVER_ACTIONS = frozenset({"retry", "retry_with_fallback", "skip_stage", "require_human", "abort"})

DEFAULT_ERROR_CLASS = "permanent"
DEFAULT_RECOVER_ACTION = "require_human"

# 「错误码 → (分类, 恢复动作)」的**唯一一份策略**。
#
# ⚠️ **为什么不直接从既有的 `retryable` 推导**：`retryable` 是**面向客户端**的语义
# ——"用户做完某个动作后可以重试这个请求"。推进器需要的是"**机器**能不能自己重试"。
# 两者在一整族码上正好相反：`*_CONFLICT`（如"请先确认视频分镜"）与 `ASSET_NOT_UPLOADED`
# 都是 retryable=True，但机器盲目重试只会再撞一次墙，必须交人工。
# 曾经按 `retryable` 推导过一版，实测把 11 个"等人做动作"的码误判成可自动重试，故改为这张显式表。
#
# **未列出的码一律走最保守默认**（permanent / require_human）——"没登记就是不许机器自己动"。
ERROR_POLICY: dict[str, tuple[str, str]] = {
    # ---- 瞬时故障：外部调用或 IO 的临时失败，机器可以自己重试 ----
    "COMPOSITION_PROVIDER_ERROR": ("transient", "retry"),
    "CONTENT_PLAN_PROVIDER_ERROR": ("transient", "retry"),
    "CONTENT_QA_PROVIDER_ERROR": ("transient", "retry"),
    "DASHSCOPE_UPLOAD_ERROR": ("transient", "retry"),
    "IMAGE_EDIT_PROVIDER_ERROR": ("transient", "retry"),
    "MATTING_PROVIDER_ERROR": ("transient", "retry"),
    "RECOGNITION_PROVIDER_ERROR": ("transient", "retry"),
    "SCRIPT_PROVIDER_ERROR": ("transient", "retry"),
    "VOICE_PROVIDER_ERROR": ("transient", "retry"),
    "VIDEO_PROVIDER_ERROR": ("transient", "retry"),
    "WAN_R2V_ERROR": ("transient", "retry"),
    "SCRIPT_GENERATION_ERROR": ("transient", "retry"),
    "KEYFRAME_GENERATION_FAILED": ("transient", "retry"),
    "VIDEO_SEGMENT_GENERATION_FAILED": ("transient", "retry"),
    "MAIN_IMAGE_PROCESSING_ERROR": ("transient", "retry"),
    "VIDEO_PROCESSING_ERROR": ("transient", "retry"),
    "VIDEO_POSTPROCESS_ERROR": ("transient", "retry"),
    "VIDEO_FRAME_EXTRACTION_FAILED": ("transient", "retry"),
    "VIDEO_QC_PROBE_FAILED": ("transient", "retry"),
    "CONTACT_SHEET_FAILED": ("transient", "retry"),
    # 契约不符：换一次生成可能就符合了（有重试上限兜底）
    "VIDEO_CONTRACT_VIOLATION": ("transient", "retry"),
    # 抓取失败：网络问题，重试有意义
    "URL_FETCH_FAILED": ("transient", "retry"),
    # ---- 策略/合规：机器重试无用，必须人看 ----
    "AIGC_LABEL_CHECK_FAILED": ("policy", "require_human"),
}


def resolve_error_policy(code: str) -> tuple[str, str]:
    """错误码 → (分类, 恢复动作)。未登记的走最保守默认。"""
    return ERROR_POLICY.get(code, (DEFAULT_ERROR_CLASS, DEFAULT_RECOVER_ACTION))


class DomainError(Exception):
    code = "DOMAIN_ERROR"
    http_status = 400
    retryable = False

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message

    # ---- 失败分类与恢复动作（S10 地基）----
    #
    # **刻意不维护一张"错误码 → 分类"的硬编码表**：那会与 69 个错误码的既有实现形成第二处真相。
    # 默认口径由**既有的 `retryable`** 推导 —— 可重试的即瞬时故障（重试），否则一律交人工。
    # 只有真正特殊的类别才在子类上显式覆盖这两个属性（例如预算超限 → policy/budget）。
    #
    # 这样做的好处：既有 69 个子类**零改动**即获得分类；而"什么算瞬时"这件事本来就只由
    # `retryable` 一个字段表达 —— 分类只是把它翻译成推进器听得懂的话。
    # 完整对照表（71 个码）落在 `docs/方案档案.md` S8+S9+S10 的「错误码 → 分类 → 动作」章节，
    # 便于审阅；权威实现只有上面那张 `ERROR_POLICY`。
    @property
    def error_class(self) -> str:
        return resolve_error_policy(self.code)[0]

    @property
    def recover_action(self) -> str:
        return resolve_error_policy(self.code)[1]


class FeatureNotImplementedError(DomainError):
    """契约已定义、能力尚未上线的显式错误。

    用于 Phase 0 提前冻结的接口：路由与数据结构先落地，调用时明确报 501，
    绝不返回伪造的成功结果（对齐项目"失败不假装完成"的原则）。
    """

    code = "FEATURE_NOT_IMPLEMENTED"
    http_status = 501
    retryable = False


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(DomainError)
    async def handle_domain_error(_: Request, exc: DomainError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.http_status,
            content={
                "error": {
                    "code": exc.code,
                    "message": exc.message,
                    "retryable": exc.retryable,
                },
                "request_id": get_request_id(),
            },
        )

    @app.exception_handler(Exception)
    async def handle_unexpected_error(_: Request, exc: Exception) -> JSONResponse:
        logger.exception("unhandled error", exc_info=exc)
        return JSONResponse(
            status_code=500,
            content={
                "error": {
                    "code": "INTERNAL_ERROR",
                    "message": "服务器内部错误",
                    "retryable": False,
                },
                "request_id": get_request_id(),
            },
        )