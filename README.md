# Miniclaw

<p align="center">
  <strong>自托管、Pi Agent 驱动的多渠道智能体工作台</strong><br />
  把 Agent、工作区、记忆、工具、渠道与自动化任务组织在同一个可控的运行环境中。
</p>

<p align="center">
  <a href="https://github.com/helsome/miniclaw">GitHub</a> ·
  <a href="docs/API.md">API</a> ·
  <a href="docs/ACL-MATRIX.md">权限模型</a> ·
  <a href="SECURITY.md">安全策略</a>
</p>

> 一句话：聊天界面让你向 Agent 提问；Miniclaw 让 Agent 拥有长期运行的工作区、可审计的能力边界，以及能够被 Web、桌面端和消息渠道共同使用的运行时。

Miniclaw 采用智能体优先工作模型：Agent 是一级产品身份，Workspace 是其文件、会话、记忆与渠道运行的隔离边界。

## 产品定位

Miniclaw 是一个面向个人与团队的自托管 AI Agent 工作台。它不是一个只保存聊天记录的对话框，而是把以下对象放在同一个产品模型中：

- Agent 身份、模型策略与能力配置。
- Workspace 文件、执行环境、权限和渠道绑定。
- 持久化 Session、流式输出、取消、恢复和后台运行。
- Workspace 级 Memory、Skills、MCP、Plugins 与 Subagents。
- Web、Electron Desktop、飞书、Telegram、QQ、钉钉、微信、Discord、WhatsApp 等入口。
- Cron、间隔和一次性任务，以及任务运行历史、通知与恢复。

Miniclaw 采用本地优先和显式集成的思路：数据库、工作区元数据、会话状态和配置由自己的服务管理；模型、消息渠道、Docker 与外部工具都作为可配置边界接入。

## 核心功能

### Agent 与 Workspace

- 用 Agent Profile 保存身份、模型、思考级别、Skills、MCP 与执行策略。
- 每个 Workspace 拥有独立的文件、Session、Memory、渠道绑定和执行边界。
- Home Workspace 与自定义 Agent 分层管理，支持创建、重命名、重建、清空和删除。
- 支持 Host 与 Docker 两种执行方式；需要隔离的任务可以在 Agent Runner 容器中运行。

### Pi Agent Runtime

- 基于 Pi Agent Runtime 提供 prompt、流式输出、工具调用、Session 持久化与恢复。
- 支持 abort、follow-up、原生 compaction 和持久化 JSONL Session。
- 复用 Miniclaw 已有的 MCP capability handler，并映射为稳定的 `mcp__miniclaw__*` 工具。
- Subagents 通过 Pi extension 与显式的 spawn/stop 生命周期桥接。
- Runtime 不会静默假装拥有缺失能力；尚未接入 Pi 的 Web Search/Web Fetch 能力会保持明确不可用。

### Memory 与上下文

- Memory 按 Workspace 隔离，不在不同工作区之间隐式共享。
- 支持事实、偏好、决策和经验等知识类型，以及搜索、编辑、忘记和版本历史。
- 写入使用 revision 与 compare-and-set，避免并发编辑覆盖彼此的修改。
- 每条 Memory 可记录来源 Session、来源类型、观察时间和变更历史，便于回溯 provenance。
- Runtime 只注入当前 Workspace 允许使用的记忆，不把平台身份约束当作普通用户记忆。

### Skills、MCP 与 Plugins

- 内置、宿主机、项目、用户、Workspace 和 Plugin 层级的 Skills 统一解析。
- 能力库集中展示 Skills、MCP 与 Plugins 的可用状态、依赖和能力预览。
- Plugin Catalog 支持扫描、导入、版本快照和用户启用配置。
- Agent 运行前会计算有效能力 Manifest，并把 Skills、MCP、Memory、Workspace 与渠道上下文按策略注入。
- 路径穿越、符号链接逃逸、越权 Workspace 与未授权 capability 会在边界层拒绝。

### 渠道与自动化

- 支持将消息渠道绑定到指定 Workspace 或 Session，并按用户、群聊、话题和 owner 规则进行 ACL 判断。
- 支持飞书、Telegram、QQ、钉钉、微信、Discord、WhatsApp 等消息入口。
- Scheduler 支持 Cron、固定间隔和一次性任务，提供立即运行、暂停、取消、运行历史和结果投递。
- 后台任务、Subagent 和渠道回复都沿用同一套 Workspace、Session、owner 与权限上下文。

### Electron Desktop

- Electron 只是 Desktop Shell，复用现有 Web Client，不在 Renderer 中承载数据库、文件系统、凭证、Docker 或 shell/process 权限。
- Main Process 负责窗口生命周期、外部链接、菜单和受限 IPC；Preload 只暴露白名单 API。
- 默认提供 macOS arm64 打包配置，并保留 Windows、Linux 目标配置。
- 同一套 Renderer 可以连接本地 Backend，也可以通过 `MINICLAW_SERVER_URL` 连接远程 Miniclaw 服务。

## 工作原理

```text
Web Client / Electron Desktop / Message Channels
                         │ HTTP + WebSocket / Channel Adapters
                         ▼
                Miniclaw Backend
        Auth · API · Queue · Scheduler · ACL
                         │
        ┌────────────────┼─────────────────┐
        ▼                ▼                 ▼
   Workspace         Capability         Channel
   Session           Registry            Binding
   Memory            Skills/MCP          Delivery
                         │
                         ▼
                 Pi Agent Runner
                   Host / Docker
                         │
                         ▼
                Pi Agent Runtime
          Tools · Extensions · Subagents
```

核心边界保持清晰：Backend 负责认证、持久化、队列、调度、渠道和授权；Pi Runner 负责 Agent 执行；Workspace 决定文件与运行边界；Electron Renderer 只负责界面和受限的桌面桥接。

## 快速开始

### 环境要求

- Node.js 20 或更高版本
- npm
- GNU Make
- 如果使用容器执行模式，需要 Docker

### 启动 Backend 与 Web Client

```bash
git clone https://github.com/helsome/miniclaw.git
cd miniclaw

npm install
npm --prefix web install
npm --prefix container/agent-runner install

# 首次安装或依赖更新后构建 Backend、Web 与 Agent Runner
npm run build:all

# 启动生产式本地服务
npm start
```

默认地址：<http://127.0.0.1:3000>

开发模式可以按用途选择启动方式。

只运行 One Take 产品后端（内部由 MiniClaw Backend Runtime 提供）：

```bash
npm run dev:backend
```


```bash
```

首次进入时完成管理员初始化和 Provider 配置即可。Provider/渠道接入步骤现在可以选择“稍后设置”，跳过后仍可进入工作台，之后在设置中补齐模型和渠道配置。

Agent 容器镜像默认使用 `helsome/miniclaw-agent:latest`，可以通过 `MINICLAW_CONTAINER_IMAGE` 或 `CONTAINER_IMAGE` 覆盖。

## 常用命令

| 命令 | 说明 |
| --- | --- |
| `npm run dev:backend` | 只启动 Backend，供 One Take 前端使用 |
| `npm run dev:all` | 启动 Backend 与 One Take 产品 Web |
| `npm run build:all` | 构建 Backend、One Take Web 与 Agent Runner |
| `npm run typecheck` | 检查 Backend TypeScript |
| `make typecheck` | 执行 Backend、Web、Agent Runner 的完整类型与文档检查 |
| `npm test -- --run` | 运行 Vitest 测试 |
| `npm run desktop:typecheck` | 检查 Electron Main/Preload 类型 |
| `npm run desktop:build` | 构建 Electron Main/Preload bundle |
| `npm run desktop:package:dir` | 构建并生成目录形式的桌面应用 |
| `npm run desktop:package` | 构建并打包桌面应用 |
| `make backup` | 创建运行时数据备份 |
| `make restore FILE=...` | 恢复指定备份 |
| `make status` | 查看 Backend、日志和 Docker 状态 |
| `make stop` | 停止当前端口上的 Miniclaw 服务 |

## 配置入口

| 环境变量 | 用途 | 默认值 |
| --- | --- | --- |
| `MINICLAW_SERVER_URL` | Electron 要连接的 Backend 地址 | `http://127.0.0.1:3000` |
| `MINICLAW_RENDERER_URL` | Electron 要加载的 Renderer 地址，适合本地 Vite 开发 | 与 Server URL 相同 |
| `MINICLAW_CONTAINER_IMAGE` | Agent Runner 使用的容器镜像 | `helsome/miniclaw-agent:latest` |
| `CONTAINER_IMAGE` | 容器镜像的兼容覆盖项 | 同上 |
| `WEB_PORT` | Makefile 启动 Backend 使用的端口 | `3000` |
| `ONETAKE_MCP_URL` | One Take MCP HTTP 地址 | `http://127.0.0.1:8010/mcp` |
| `ONETAKE_MCP_TOKEN` | One Take MCP Bearer Token | 无 |
| `ONETAKE_MCP_APPROVAL_TOKEN` | One Take 人工审批 Token，仅后端使用 | 无 |
| `ONETAKE_EDITOR_URL` | One Take 产品前端地址 | `http://127.0.0.1:5173` |
| `ONETAKE_API_URL` | MiniClaw 后端访问 One Take API 的地址 | `http://127.0.0.1:8000` |

不要把 API Key、Session Cookie 或其他凭证写入命令行历史、截图或提交到仓库。远程部署时使用 HTTPS/WSS，并为反向代理、Cookie 和访问控制配置独立的安全边界。

## One Take 集成

仓库包含开发版只读插件：

```text
integrations/miniclaw/onetake-readonly/
```

插件通过 HTTP MCP 读取 One Take 的项目、Provider、Pipeline、视频和费用预估。当前只读，不允许 Agent 创建项目、确认付费步骤或修改任务。

本地默认 MCP 地址：

```text
http://host.docker.internal:8010/mcp
```

默认 token 仅用于本地开发，共享或远程部署前必须更换。

写工具由 One Take MCP 侧的 `ONETAKE_MCP_WRITE_ENABLED` 控制；真实配音和视频生成还需要 `ONETAKE_MCP_PAID_ENABLED=true`，并由本页面人工确认。

### One Take 产品模式

One Take Web 是唯一产品前端。One Take 产品后端（基于 MiniClaw Runtime）只运行 Backend，通过 MCP 调用 One Take，并向 One Take Agent 面板提供认证、会话、Memory 和调度能力。


### Web 目录

- `web/`：One Take 产品前端，正式构建产物由 One Take 产品后端提供。
- One Take 原仓库保留为回退镜像，P6-05 未删除其 `apps/web/`。
## 执行与安全边界

- Backend 由 Node.js 运行，负责认证、API、WebSocket、队列、调度、渠道连接、Provider、用量和 SQLite 持久化。
- Docker 只隔离 Agent 执行环境，不承载 Desktop UI，也不替代 Backend 的授权层。
- Electron BrowserWindow 使用 `contextIsolation`、关闭 `nodeIntegration` 和 sandbox。
- Renderer 不直接读取文件、数据库或凭据；需要本机能力时只通过受限 Preload IPC 调用。
- 外部链接由 Main Process 校验协议后打开；Renderer 导航限制在允许的 Backend/Renderer origin 内。
- Workspace ACL、owner、用户角色、系统权限和 Host 执行策略在服务端共同判定，不能因为拥有某一层权限就自动越过其他边界。
- Memory、Skills、MCP、Plugins 和 Scheduler 任务都继承用户、Agent、Workspace 与 Session 上下文。

更多权限约束见 [`docs/ACL-MATRIX.md`](docs/ACL-MATRIX.md)，安全问题请参考 [`SECURITY.md`](SECURITY.md)。

## 项目状态

Miniclaw 当前处于持续开发阶段。仓库已经包含：

- Pi Agent Runtime 生产执行路径与 runtime-neutral contract。
- Web Client 与 Electron Desktop Shell。
- Agent Profile、Workspace、Session、Memory、Skills、MCP、Plugins 和 Subagents。
- 多用户认证、ACL、owner 生命周期、调度任务、用量和渠道接入。
- Host/Docker 双执行边界，以及 macOS arm64 的 Electron 打包配置。

真实模型调用、Docker 执行、渠道连接和远程部署仍然依赖本地凭证、服务配置与运行环境；没有外部 Provider 时，可以先启动 UI、完成本地初始化，并在设置中稍后补齐配置。

## 路线图

### 近期

- 补充 Pi Runtime 的 Web Search/Web Fetch 等能力适配。
- 完善渠道 onboarding、运行监控和失败恢复提示。
- 增加更多 Electron 打包、签名和发布验证路径。
- 持续收敛 Workspace、Memory、Skills 与 Scheduler 的产品文档。

### 长期

- 更完整的跨平台桌面构建。
- 更丰富的 Agent/Plugin/Provider 扩展模型。
- 可视化的运行轨迹、证据链与成本分析。
- 面向贡献者的能力注册、Skill 开发和渠道适配指南。

## 文档

- [`docs/API.md`](docs/API.md) — HTTP API、认证和主要资源接口
- [`docs/ACL-MATRIX.md`](docs/ACL-MATRIX.md) — 用户、Workspace、Channel、Host 与任务权限矩阵
- [`docs/workspace-memory-v2.md`](docs/workspace-memory-v2.md) — Workspace Memory 的数据模型、版本与交互边界
- [`docs/runtime-migration.md`](docs/runtime-migration.md) — 从旧运行时到 Pi Agent Runtime 的迁移记录
- [`docs/PROMPT-SKILL-RUNTIME-TEST-PLAN.md`](docs/PROMPT-SKILL-RUNTIME-TEST-PLAN.md) — Prompt、Skill、Runtime 与 Agent Builder 验证计划
- [`docs/miniclaw-migration-cleanup.md`](docs/miniclaw-migration-cleanup.md) — 品牌和运行时命名迁移记录
- [`SECURITY.md`](SECURITY.md) — 安全问题报告与处理策略

## 参与贡献

欢迎提交 Issue 与 Pull Request。提交前建议运行：

```bash
make typecheck
npm test -- --run
npm run build:all
npm run desktop:typecheck
npm run desktop:build
```

如果改动了 UI、桌面窗口或交互流程，请附上截图或简短的视觉 QA 说明。新增桌面能力优先放在 Main/Preload，并保持 Renderer 不接触 SQLite、filesystem、credentials、Docker 和 shell/process。

## License

Miniclaw 使用 MIT License，详见 [`LICENSE`](LICENSE)。
