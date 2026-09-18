from onetake_api.config import get_settings
from onetake_api.integrations.mock_video.composition import MockCompositionAdapter
from onetake_api.integrations.shotstack.adapter import ShotstackCompositionAdapter
from onetake_api.modules.composition.port import CompositionPort
from onetake_api.platform.errors import DomainError


class CompositionConfigurationError(DomainError):
    code = "COMPOSITION_PROVIDER_NOT_CONFIGURED"
    http_status = 422


def get_composition_provider() -> CompositionPort:
    settings = get_settings()
    if settings.mock_providers or settings.composition_provider == "mock":
        return MockCompositionAdapter()
    if not settings.shotstack_api_key:
        raise CompositionConfigurationError("真实合成缺少 SHOTSTACK_API_KEY")
    return ShotstackCompositionAdapter(
        api_key=settings.shotstack_api_key,
        environment=settings.shotstack_env,
        api_base=settings.shotstack_api_base,
        poll_interval_seconds=settings.shotstack_poll_interval_seconds,
        poll_timeout_seconds=settings.shotstack_poll_timeout_seconds,
    )
