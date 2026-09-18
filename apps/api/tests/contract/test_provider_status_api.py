from onetake_api.config import Settings
from onetake_api.modules.provider.service import get_provider_statuses


def test_provider_status_api_defaults_to_mock(client) -> None:
    response = client.get("/api/v1/providers/status")
    assert response.status_code == 200
    data = response.json()["data"]
    assert [item["capability"] for item in data] == ["recognition", "image_edit", "matting", "script", "voice", "composition"]
    assert all(item["effective_mode"] == "mock" for item in data)
    assert "api_key" not in response.text.lower()


def test_real_provider_without_key_is_not_ready() -> None:
    settings = Settings(
        mock_providers=False,
        recognition_provider="real",
        image_edit_provider="mock",
        matting_provider="mock",
        script_provider="mock",
        dashscope_api_key="",
        photoroom_api_key="",
    )
    recognition = next(item for item in get_provider_statuses(settings) if item.capability == "recognition")
    assert recognition.configured is False
    assert recognition.effective_mode == "mock"
    assert recognition.ready is False
    assert recognition.reason is not None

def test_provider_switches_are_independent() -> None:
    settings = Settings(
        mock_providers=False,
        recognition_provider="real",
        image_edit_provider="mock",
        matting_provider="mock",
        script_provider="mock",
        dashscope_api_key="configured",
        photoroom_api_key="",
    )
    statuses = {item.capability: item for item in get_provider_statuses(settings)}
    assert statuses["recognition"].effective_mode == "real"
    assert statuses["image_edit"].effective_mode == "mock"
    assert statuses["matting"].effective_mode == "mock"
    assert statuses["script"].effective_mode == "mock"


def test_aliyun_matting_requires_access_key() -> None:
    settings = Settings(
        mock_providers=False,
        recognition_provider="mock",
        image_edit_provider="mock",
        matting_provider="aliyun",
        script_provider="mock",
        alibaba_cloud_access_key_id="",
        alibaba_cloud_access_key_secret="",
    )
    matting = next(item for item in get_provider_statuses(settings) if item.capability == "matting")
    assert matting.configured is False
    assert matting.configured_provider == "aliyun-imageseg-segmentcommodity"
    assert matting.effective_mode == "mock"
    assert matting.ready is False



def test_shotstack_composition_requires_key() -> None:
    settings = Settings(
        mock_providers=False,
        composition_provider="shotstack",
        shotstack_api_key="",
    )
    composition = next(item for item in get_provider_statuses(settings) if item.capability == "composition")
    assert composition.configured is False
    assert composition.configured_provider == "shotstack-stage"
    assert composition.effective_mode == "mock"
    assert composition.ready is False
    assert composition.reason is not None
