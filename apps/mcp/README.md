# One Take MCP Bridge

只读 MCP 服务，把 One Take HTTP API 包装成 MiniClaw 可调用的工具。

## 工具

- `onetake_get_provider_status`
- `onetake_list_projects`
- `onetake_get_project`
- `onetake_get_pipeline`
- `onetake_get_video`
- `onetake_estimate_video_cost`

当前阶段禁止写操作、付费调用和直接数据库访问。

## 环境变量

```env
ONETAKE_API_BASE_URL=http://api:8000
ONETAKE_MCP_TOKEN=change-me
ONETAKE_MCP_REQUEST_TIMEOUT_SECONDS=10
```

`ONETAKE_MCP_TOKEN` 必须配置，客户端通过 `Authorization: Bearer <ONETAKE_MCP_TOKEN>` 访问 `/mcp`。

## 启动

```powershell
docker compose up -d --build mcp
```

MCP 地址：

```text
http://localhost:8010/mcp
```

## 测试

```powershell
docker compose run --rm --no-deps mcp pytest -q
```

## 回退

```powershell
docker compose stop mcp
docker compose rm -f mcp
```

停止 MCP 不影响 One Take API、Worker 和 MinIO。