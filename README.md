# One Take MVP

One Take 商品 AI 视频生成 MVP 的工程仓库。

## 当前阶段

当前为 **M1-01：项目创建与 ProjectCreated 事件基线**。

已具备：

- React Web
- FastAPI API
- Worker
- PostgreSQL
- Redis
- MinIO
- Alembic 数据库迁移
- Project 模块
- Outbox 模块
- 项目创建与查询 API
- 请求 ID 和基础日志

默认启用 Mock Provider，不调用任何付费 AI 接口。

## 启动

```powershell
Copy-Item .env.example .env
docker compose up -d --build
```

首次启动时，`migrate` 服务会自动执行：

```text
alembic upgrade head
```

访问：

- Web: http://localhost:5173
- API: http://localhost:8000/docs
- MinIO Console: http://localhost:9001

## API

```text
POST /api/v1/projects
GET  /api/v1/projects/{project_id}
```

创建项目：

```powershell
Invoke-RestMethod `
  -Uri http://localhost:8000/api/v1/projects `
  -Method Post `
  -ContentType application/json `
  -Body '{"product_name":"便携式榨汁杯","product_note":"白色杯身"}'
```

## 测试

```powershell
docker compose exec -T api pytest -q
```

## 停止

```powershell
docker compose down
```

保留数据卷：

```powershell
docker compose down
```

删除数据卷：

```powershell
docker compose down -v
```

## 架构与方案

- [架构设计](docs/架构设计.md)
- [方案档案](docs/方案档案.md)