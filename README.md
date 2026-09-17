# One Take MVP

One Take 商品 AI 视频生成 MVP 的工程仓库。

## 当前阶段

当前为 **M1-02：素材注册与 MinIO 直传基线**。

已具备：

- React Web
- FastAPI API
- Worker
- PostgreSQL
- Redis
- MinIO
- Alembic 数据库迁移
- Project、Asset、Outbox 模块
- 项目创建与查询 API
- 图片预签名直传、完成复核与列表 API
- 请求 ID 和基础日志

默认启用 Mock Provider，不调用任何付费 AI 接口。

## 启动

```powershell
Copy-Item .env.example .env
docker compose up -d --build
```

`migrate` 服务会自动执行：

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

POST /api/v1/projects/{project_id}/assets/presign
POST /api/v1/projects/{project_id}/assets/{asset_id}/complete
GET  /api/v1/projects/{project_id}/assets
```

## 图片上传流程

```text
申请预签名 URL
→ 浏览器 PUT 图片到 MinIO
→ 调用 complete
→ 服务端复核大小、SHA-256、格式和尺寸
→ Asset 状态变为 ready
→ 写入 AssetRegistered Outbox 事件
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