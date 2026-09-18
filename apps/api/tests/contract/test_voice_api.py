from onetake_api.modules.voice.service import VoiceApplicationService
from onetake_api.platform.database import SessionLocal


def test_voice_get_empty_state(client) -> None:
    project = client.post("/api/v1/projects", json={"product_name": "语音空状态"}).json()["data"]
    response = client.get(f"/api/v1/projects/{project['project_id']}/voice")
    assert response.status_code == 200
    assert response.json()["data"]["run"] is None


def test_voice_api_requires_confirmed_script(client) -> None:
    project = client.post("/api/v1/projects", json={"product_name": "语音前置"}).json()["data"]
    response = client.post(
        f"/api/v1/projects/{project['project_id']}/voice",
        json={"enabled": True, "voice_id": "female", "language": "zh", "speed": 1.0},
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "VOICE_CONFLICT"
