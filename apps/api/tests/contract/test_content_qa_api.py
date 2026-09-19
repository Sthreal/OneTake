def test_content_quality_empty_state(client) -> None:
    project = client.post("/api/v1/projects", json={"product_name": "质检空状态"}).json()["data"]
    response = client.get(f"/api/v1/projects/{project['project_id']}/content-quality")
    assert response.status_code == 200
    assert response.json()["data"] is None
