"""`GET /api/v1/projects/{id}/repairs` 的契约（S11 验收 4）。

两条硬要求：
1. 每个动作都带**可用的既有端点**（在 app 的 openapi 路径里能找到）；
2. 动作的端点集合 ⊆ **既有端点白名单** —— 证明本切片没新增任何写路径。
"""
from __future__ import annotations

from onetake_api.main import app
from onetake_api.modules.content_qa.repair_plan import REPAIR_ACTIONS

# 既有端点白名单（S11 只能指向这些；新增一个都要在这里显式加，逼人思考）
KNOWN_ENDPOINT_TEMPLATES = {
    "/api/v1/projects/{project_id}/video/segments/{target_ref}/retake",
    "/api/v1/projects/{project_id}/video/segments/{target_ref}/candidates",
    "/api/v1/projects/{project_id}/video/keyframes/{target_ref}/candidates",
    "/api/v1/projects/{project_id}/compose",
    "/api/v1/projects/{project_id}/voice",
    "/api/v1/projects/{project_id}/subtitle",
    "/api/v1/projects/{project_id}/video/gate",
}


def _template_matches_openapi(template: str, run_id: str) -> bool:
    """把具体 id 还原成型参，再看 openapi 里有没有这条路径。"""
    candidate = template.replace(run_id, "{project_id}") if "{project_id}" not in template else template
    # 端点里的目标 id 在真实路径中已被替换 → 逐段比较（把具体段替换回通配）
    for path in app.openapi()["paths"]:
        expected = path.replace("{project_id}", "{project_id}")
        actual_parts = candidate.split("/")
        path_parts = expected.split("/")
        if len(actual_parts) != len(path_parts):
            continue
        if all(
            a == b or (b.startswith("{") and not a.startswith("{"))
            for a, b in zip(actual_parts, path_parts)
        ):
            return True
    return False


def test_repairs_returns_plan_with_existing_endpoints_only(client) -> None:
    project = client.post("/api/v1/projects", json={"product_name": "修复闭环"}).json()["data"]
    project_id = project["project_id"]

    response = client.get(f"/api/v1/projects/{project_id}/repairs")
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["project_id"] == project_id
    assert data["gate_status"] in {"ok", "warn", "fail"}
    assert isinstance(data["download_allowed"], bool)

    actions = data["actions"]
    assert actions, "没有任何产物的项目至少应有「质检报告缺失」这条动作"
    for action in actions:
        assert action["action"] in REPAIR_ACTIONS, action
        assert action["action_label"], action
        assert action["severity"] in {"warn", "fail"}, action

    # 每条动作的端点都必须是**既有**端点（白名单）+ 在 openapi 里真实存在
    endpoints = {action["execute_endpoint"] for action in actions}
    for endpoint in endpoints:
        assert endpoint, "动作必须带可用端点（human_ack 指向只读的交付门视图）"
        suffix = endpoint.split("/api/v1/projects/", 1)[1]
        assert suffix.startswith(project_id + "/"), endpoint
        template = "/api/v1/projects/{project_id}/" + suffix.split("/", 1)[1]
        assert template in KNOWN_ENDPOINT_TEMPLATES, template
        assert _template_matches_openapi(endpoint, project_id), template