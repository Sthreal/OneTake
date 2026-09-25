# One Take Read-only Plugin

Development-only MiniClaw plugin that registers the One Take read-only MCP server.

The default MCP token is `onetake-mcp-dev-token`, matching the local Docker Compose default. Change it before any shared or remote deployment.

- MCP URL from host: `http://localhost:8010/mcp`
- MCP URL from Agent container: `http://host.docker.internal:8010/mcp`
- Tools: provider status, projects, pipeline, video, cost estimate
Controlled writes are hidden unless One Take MCP enables them. Paid voice/video generation requires a one-time approval created by the MiniClaw administrator action.
