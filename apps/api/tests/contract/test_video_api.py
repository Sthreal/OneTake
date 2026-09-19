def test_video_plan_requires_audio_subtitle_confirmation(client) -> None:
    project = client.post("/api/v1/projects", json={"product_name": "视频前置"}).json()["data"]
    response = client.post(f"/api/v1/projects/{project['project_id']}/video-plan", json={"mode": "product", "template_id": "clean"})
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "VIDEO_CONFLICT"


def test_video_get_empty_state(client) -> None:
    project = client.post("/api/v1/projects", json={"product_name": "视频空状态"}).json()["data"]
    response = client.get(f"/api/v1/projects/{project['project_id']}/video")
    assert response.status_code == 200
    assert response.json()["data"]["plan"] is None


def test_video_estimate_requires_existing_plan(client) -> None:
    project = client.post("/api/v1/projects", json={"product_name": "视频预估"}).json()["data"]
    response = client.get(f"/api/v1/projects/{project['project_id']}/video-plan/vid_missing/estimate")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "VIDEO_NOT_FOUND"
