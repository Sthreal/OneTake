from onetake_api.modules.script.service import ScriptProviderConfigurationError, _adapter as script_adapter
import pytest

from onetake_api.config import Settings
from onetake_api.modules.image_edit.service import ImageEditApplicationService, ImageEditProviderConfigurationError
from onetake_api.modules.matting.service import MattingApplicationService, MattingProviderConfigurationError


def test_image_edit_real_requires_dashscope_key(monkeypatch) -> None:
    monkeypatch.setattr(
        "onetake_api.modules.image_edit.service.get_settings",
        lambda: Settings(mock_providers=False, image_edit_provider="real", dashscope_api_key=""),
    )
    with pytest.raises(ImageEditProviderConfigurationError):
        ImageEditApplicationService().ensure_ready()


def test_matting_real_requires_photoroom_key(monkeypatch) -> None:
    monkeypatch.setattr(
        "onetake_api.modules.matting.service.get_settings",
        lambda: Settings(mock_providers=False, matting_provider="real", photoroom_api_key=""),
    )
    with pytest.raises(MattingProviderConfigurationError):
        MattingApplicationService().ensure_ready()


def test_aliyun_matting_real_requires_access_key(monkeypatch) -> None:
    monkeypatch.setattr(
        "onetake_api.modules.matting.service.get_settings",
        lambda: Settings(mock_providers=False, matting_provider="aliyun", alibaba_cloud_access_key_id="", alibaba_cloud_access_key_secret=""),
    )
    with pytest.raises(MattingProviderConfigurationError):
        MattingApplicationService().ensure_ready()


def test_script_real_requires_dashscope_key(monkeypatch) -> None:
    monkeypatch.setattr(
        "onetake_api.modules.script.service.get_settings",
        lambda: Settings(mock_providers=False, script_provider="real", dashscope_api_key=""),
    )
    with pytest.raises(ScriptProviderConfigurationError):
        script_adapter()

