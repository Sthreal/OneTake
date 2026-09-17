# One Take MVP

One Take 商品 AI 视频生成 MVP 的工程仓库。

## 当前阶段

当前为 **M1-04：商品信息编辑**。

已具备：

- React + TypeScript 响应式工作台
- FastAPI API
- Worker
- PostgreSQL
- Redis
- MinIO
- Alembic 数据库迁移
- Project、Asset、Outbox 模块
- 项目创建、素材预签名、完成复核与列表 API
- 苹果风三栏工作台
- 顶部四段流程进度条
- 左侧项目列表与项目切换
- 创建后编辑商品名称和补充说明
- ProjectUpdated 事件与最近编辑排序
- 图片本地校验、MinIO 直传、进度和失败重试
- 最近项目恢复

默认启用 Mock Provider，不调用任何付费 AI 接口。

## 启动

```powershell
Copy-Item .env.example .env
docker compose up -d --build
```

访问：

- Web: http://localhost:5173
- API: http://localhost:8000/docs
- MinIO Console: http://localhost:9001

## 测试

后端：

```powershell
docker compose exec -T api pytest -q
```

前端：

```powershell
cd apps/web
npm run test:run
npm run build
```

## 页面流程

```text
填写商品名称
→ 创建项目
→ 项目加入左侧列表
→ 拖拽或选择图片
→ 本地校验
→ 预签名上传 MinIO
→ 服务端复核
→ 素材状态 ready
→ 点击左侧项目可切换
→ 刷新后恢复项目和素材
```

## 架构与方案

- [架构设计](docs/架构设计.md)
- [方案档案](docs/方案档案.md)