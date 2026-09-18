def test_subtitle_get_empty_state(client) -> None:
    project = client.post("/api/v1/projects", json={"product_name": "字幕空状态"}).json()["data"]
    response = client.get(f"/api/v1/projects/{project['project_id']}/subtitle")
    assert response.status_code == 200
    assert response.json()["data"]["version"] is None


def test_audio_subtitle_get_empty_state(client) -> None:
    project = client.post("/api/v1/projects", json={"product_name": "音频字幕空状态"}).json()["data"]
    response = client.get(f"/api/v1/projects/{project['project_id']}/audio-subtitle")
    assert response.status_code == 200
    assert response.json()["data"]["voice"]["run"] is None
    assert response.json()["data"]["subtitle"]["version"] is None
