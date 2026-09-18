from __future__ import annotations

from dataclasses import dataclass

from onetake_api.config import Settings, get_settings


@dataclass(frozen=True)
class ProviderStatus:
    capability: str
    configured_mode: str
    effective_mode: str
    configured_provider: str
    effective_provider: str
    configured: bool
    ready: bool
    reason: str | None


_MOCK_NAMES = {
    "recognition": "mock-recognition",
    "image_edit": "mock-qwen-image-edit-plus",
    "matting": "mock-photoroom",
    "script": "mock-qwen-vl-plus",
    "voice": "mock-cosyvoice-v2",
    "composition": "mock-ffmpeg",
}
_REAL_NAMES = {
    "recognition": "qwen-vl-plus",
    "image_edit": "qwen-image-edit-plus",
    "matting": "photoroom",
    "matting_aliyun": "aliyun-imageseg-segmentcommodity",
    "script": "qwen-vl-plus",
    "voice": "cosyvoice-v2",
    "composition": "shotstack-stage",
}


def _provider_name(settings: Settings, capability: str, mode: str) -> str:
    if capability == "matting" and mode == "aliyun":
        return _REAL_NAMES["matting_aliyun"]
    if capability == "composition" and mode == "shotstack":
        return f"shotstack-{settings.shotstack_env}"
    return _REAL_NAMES[capability] if mode in {"real", "aliyun"} else _MOCK_NAMES[capability]


def _real_configured(settings: Settings, capability: str) -> bool:
    if capability in {"recognition", "image_edit", "script", "voice"}:
        return bool(settings.dashscope_api_key)
    if capability == "composition":
        return bool(settings.shotstack_api_key)
    if capability == "matting":
        if settings.matting_provider == "aliyun":
            return bool(settings.alibaba_cloud_access_key_id and settings.alibaba_cloud_access_key_secret)
        return bool(settings.photoroom_api_key)
    return False


def get_provider_statuses(settings: Settings | None = None) -> list[ProviderStatus]:
    settings = settings or get_settings()
    statuses: list[ProviderStatus] = []
    for capability in ("recognition", "image_edit", "matting", "script", "voice", "composition"):
        configured_mode = getattr(settings, f"{capability}_provider")
        configured = configured_mode == "mock" or _real_configured(settings, capability)
        if settings.mock_providers:
            effective_mode = "mock"
            reason = "MOCK_PROVIDERS 全局安全锁已开启"
        elif configured_mode == "mock":
            effective_mode = "mock"
            reason = None
        elif configured:
            effective_mode = configured_mode
            reason = None
        else:
            effective_mode = "mock"
            reason = "真实 Provider 已选择但缺少 API Key"
        statuses.append(
            ProviderStatus(
                capability=capability,
                configured_mode=configured_mode,
                effective_mode=effective_mode,
                configured_provider=_provider_name(settings, capability, configured_mode),
                effective_provider=_provider_name(settings, capability, effective_mode),
                configured=configured,
                ready=configured and (effective_mode != "mock" or configured_mode == "mock"),
                reason=reason,
            )
        )
    return statuses
