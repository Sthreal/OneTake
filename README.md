# One Take

One Take 是面向电商商品场景的 AI 视频生成平台。它把商品素材处理、商品识别、文案生成、配音、字幕、视频方案、Agent 协作和成片渲染组织在一条可追踪的生产流水线中。

本仓库是 One Take 的唯一发布仓库。Agent Runtime、Memory、Workspace 和 Scheduler 等能力以内部平台的形式包含在 `platform/one-take-backend/`，不再作为独立产品仓库发布。

## 仓库结构

```text
OneTake/
├─ apps/
│  ├─ api/                         # One Take 核心 FastAPI 服务
│  ├─ worker/                      # RQ Worker 与媒体处理任务
│  ├─ mcp/                         # One Take 受控 MCP Bridge
│  └─ web/                         # 已冻结的旧版 Web，仅用于回退
├─ platform/
│  └─ one-take-backend/            # One Take 产品后端与 Agent Runtime
│     ├─ src/                      # Agent、Workspace、Memory、Scheduler、渠道
│     ├─ container/                # Agent Runner 与容器运行层
│     ├─ web/                      # 当前产品 Web 宿主
│     ├─ integrations/             # One Take 集成能力
│     └─ tests/                    # 产品后端与 Agent 测试
├─ docs/                           # 架构、方案档案和验收报告
├─ infra/                          # 数据库与基础设施配置
├─ scripts/                        # 开发和验收脚本
└─ docker-compose.yml              # One Take 核心服务编排
```

## 产品组成

### One Take Core

- FastAPI API、RQ Worker、PostgreSQL、Redis、MinIO。
- 素材上传、商品识别、图片编辑、去背、文案、配音、字幕和视频方案。
- Wan S2V、Qwen、Photoroom、阿里云和 Shotstack 等 Provider Adapter。
- 1080×1920、18–25 秒、30 fps、H.264/AAC 成片规格卡口。
- Mock 全流程验收，默认不调用付费 AI 接口。

### One Take Agent Platform

- 基于修复和扩展后的 MiniClaw Runtime。
- 每个 One Take 项目绑定一个独立 Workspace。
- 提供项目级 Agent 会话、Memory、Scheduler、MCP、Skills 和后台任务。
- 作为 `platform/one-take-backend/` 的内部能力层工作，不作为第二个产品前端。
- 对外名称统一为“One Take 产品后端”；内部目录和环境变量暂时保留 MiniClaw 命名，降低升级成本。

## 架构

```text
One Take Web
    │
    ├─ /api/*              → One Take Core API
    ├─ /miniclaw-api/*     → One Take 产品后端
    └─ /miniclaw-ws/*      → One Take 产品后端事件流

One Take Core API
    ├─ PostgreSQL          项目、素材、Pipeline、Outbox
    ├─ Redis / RQ          Worker 队列与异步任务
    ├─ MinIO               媒体对象存储
    ├─ Provider Adapters   AI、渲染、配音和字幕能力
    └─ MCP Bridge          受控的只读与人工审批写工具
```

## 快速启动

### 1. 启动 One Take Core

```powershell
Copy-Item .env.example .env
docker compose up -d --build api worker mcp
```

### 2. 启动 One Take 产品后端

另开一个 PowerShell：

```powershell
cd platform/one-take-backend
npm install
$env:ONETAKE_MCP_URL = "http://127.0.0.1:8010/mcp"
$env:ONETAKE_MCP_TOKEN = "<与 One Take MCP 配置一致>"
$env:ONETAKE_API_URL = "http://127.0.0.1:8000"
npm run dev:backend
```

### 3. 启动产品 Web

再开一个 PowerShell：

```powershell
cd platform/one-take-backend
npm --prefix web install
npm --prefix web run dev
```

默认地址：

- Web：http://localhost:5173
- API：http://localhost:8000/docs
- Provider 状态：http://localhost:8000/api/v1/providers/status
- MCP：http://localhost:8010/mcp
- MinIO Console：http://localhost:9001

## 测试

One Take Core：

```powershell
docker compose exec -T api pytest -q
```

One Take 产品后端：

```powershell
cd platform/one-take-backend
npm run typecheck
npm test -- --run
```

产品 Web：

```powershell
cd platform/one-take-backend
npm --prefix web run test:run
npm --prefix web run build
```

## Provider 模式

默认启用 Mock，不产生付费调用。真实 Provider 必须在 `.env` 中显式关闭安全锁并配置凭据。密钥不得提交到 Git。

```env
MOCK_PROVIDERS=true
RECOGNITION_PROVIDER=mock
IMAGE_EDIT_PROVIDER=mock
MATTING_PROVIDER=mock
SCRIPT_PROVIDER=mock
AVATAR_VIDEO_PROVIDER=mock
```

真实 Provider 失败不会自动回退 Mock，避免把 Mock 结果误认为真实结果。

## 回退与升级

- One Take 原前端保留在 `apps/web/`，仅用于回退。
- One Take 产品后端通过 Git Subtree 方式并入本仓库，GitHub 上只显示一个项目。
- 合并前回退标签：`onetake-pre-monorepo-merge`。
- 产品后端回退标签：`miniclaw-pre-monorepo-merge`。
- 后续同步内部平台上游时，使用 `git subtree pull --prefix=platform/one-take-backend <remote> <ref>`，解决冲突后必须同时运行 Core、产品后端和 Web 测试。

## 文档

- [架构设计](docs/架构设计.md)
- [方案档案](docs/方案档案.md)
- [仓库结构与开发说明](docs/仓库结构与开发说明.md)
- [MVP 验收报告](docs/MVP验收报告.md)
- [真实 S2V 启用手册](docs/真实S2V启用手册.md)
- [MCP Bridge](apps/mcp/README.md)

## 许可证

One Take 产品代码沿用仓库中的许可证。`platform/one-take-backend/` 保留其原始 MIT License 和版权声明。