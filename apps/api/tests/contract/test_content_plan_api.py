def test_content_plan_empty_state(client) -> None:
    project = client.post("/api/v1/projects", json={"product_name": "分镜空状态"}).json()["data"]
    response = client.get(f"/api/v1/projects/{project['project_id']}/content-plan")
    assert response.status_code == 200
    assert response.json()["data"] is None


def test_content_plan_requires_confirmed_audio_subtitle(client) -> None:
    project = client.post("/api/v1/projects", json={"product_name": "分镜前置"}).json()["data"]
    response = client.post(f"/api/v1/projects/{project['project_id']}/content-plan")
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "CONTENT_PLAN_CONFLICT"
