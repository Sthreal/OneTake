# One Take MVP

One Take 商品 AI 视频生成 MVP 的工程仓库。

## 当前阶段

当前为 **M1-06：主图处理链路**。

已具备：

- React + TypeScript 响应式工作台
- FastAPI API、RQ Worker、PostgreSQL、Redis、MinIO
- Alembic 数据库迁移
- Project、Asset、Outbox、Recognition、Image Edit、Matting、Main Image 模块
- 项目创建、素材预签名、复核、列表和项目切换
- Mock 商品识别与人工确认
- 主图处理 Pipeline：图像编辑 → 智能去背 → Pillow 标准化 → 人工确认
- 2000 × 2000 透明 PNG 与 1000 × 1000 白底 JPG
- PNG/JPG 预览、重新生成和确认
- 苹果风三栏工作台、四段流程进度和最近项目恢复

默认启用 Mock Provider，不调用任何付费 AI 接口。真实 Qwen Image Edit 和 Photoroom Adapter 已预留，必须显式关闭 Mock 并配置 API Key 后才会启用。

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
→ 上传并复核素材
→ 开始识别
→ RQ Worker 执行 Mock 识别
→ 用户确认候选商品
→ 生成主图
→ 图像编辑、去背、标准化
→ 预览 PNG / JPG
→ 用户确认主图
→ Pipeline 进入 main_image_confirmed
```

## 架构与方案

- [架构设计](docs/架构设计.md)
- [方案档案](docs/方案档案.md)
