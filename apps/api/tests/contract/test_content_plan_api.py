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


def test_scene_camera_payload_is_validated_before_anything_else(client) -> None:
    """逐镜运镜端点：空值 / 超长 / 缺字段在 schema 层就被拒（422），与项目是否存在无关。"""
    url = "/api/v1/projects/prj_not_needed/content-plan/scene/scene_1/camera"
    assert client.patch(url, json={"camera_move": ""}).status_code == 422
    assert client.patch(url, json={"camera_move": "x" * 201}).status_code == 422
    assert client.patch(url, json={}).status_code == 422
